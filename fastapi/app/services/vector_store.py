"""ChromaDB wrapper + DocumentIndexer (scan → parse → chunk → embed → store)."""

from __future__ import annotations

import datetime
import logging
import os
import uuid
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from sqlalchemy.orm import Session

from app.models.document import DocumentRecord
from app.services.document_parser import SUPPORTED_EXTENSIONS, parse_file
from app.services.chunker import chunk_text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  VectorStore — thin ChromaDB wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class VectorStore:
    """Manages a persisted ChromaDB collection for document chunks.

    Embeddings are computed externally (by *EmbeddingService*) and passed in
    explicitly — this keeps the store provider-agnostic.
    """

    def __init__(self, persist_dir: str, collection_name: str = "documents"):
        self.persist_dir = persist_dir
        self.collection_name = collection_name

        Path(persist_dir).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── CRUD ────────────────────────────────────────────────────────────────

    def add(
        self,
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
    ) -> list[str]:
        """Insert chunks with pre-computed embeddings.  Returns ChromaDB ids."""
        if not texts:
            return []
        ids = [str(uuid.uuid4()) for _ in texts]
        self.collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas or [{}] * len(texts),
        )
        return ids

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Semantic similarity search.

        Returns
        -------
        list[dict]  each with keys: *id*, *text*, *metadata*, *distance*
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                hits.append(
                    {
                        "id": doc_id,
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else None,
                    }
                )
        return hits

    def delete_by_filter(self, where: dict) -> int:
        """Delete all chunks matching a metadata filter.  Returns count deleted."""
        before = self.collection.count()
        self.collection.delete(where=where)
        after = self.collection.count()
        return before - after

    def count(self) -> int:
        return self.collection.count()


# ═══════════════════════════════════════════════════════════════════════════════
#  DocumentIndexer — scan → parse → chunk → embed → store
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentIndexer:
    """Scans *MEDIA_DIR* (NAS root) for documents, indexes new/modified files.

    Shares the same root as media files — any supported documents found
    under the NAS directory are indexed for RAG.

    Analogue of ``FileScanner`` for media — same pattern, different pipeline.
    """

    def __init__(
        self,
        session: Session,
        root_path: str | None = None,
        vector_store: VectorStore | None = None,
        embedding_service=None,
    ):
        from app.config import get_settings

        self.session: Session = session
        settings = get_settings()
        self.root_path = Path(root_path or settings.MEDIA_DIR).resolve()
        self.vector_store = vector_store or VectorStore(persist_dir=settings.CHROMA_DB_DIR)
        self.embedding_service = embedding_service

        self.chunk_size = settings.CHUNK_SIZE
        self.chunk_overlap = settings.CHUNK_OVERLAP

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get_embedding_service(self):
        if self.embedding_service is not None:
            return self.embedding_service
        from app.services.embedding_service import get_embedding_service
        return get_embedding_service()

    @staticmethod
    def _walk_documents(root: Path) -> set[str]:
        """Return absolute paths of all supported files under *root*."""
        current: set[str] = set()
        if not root.exists():
            return current
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for f in filenames:
                if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                    current.add(os.path.join(dirpath, f))
        return current

    # ── public API ───────────────────────────────────────────────────────────

    def scan_and_index(self) -> dict:
        """Walk *MEDIA_DIR*, index new/modified documents, mark deleted ones.

        Returns
        -------
        dict  ``{"indexed": int, "skipped": int, "failed": int, "deleted": int}``
        """
        current_files = self._walk_documents(self.root_path)

        existing: dict[str, DocumentRecord] = {
            r.file_path: r
            for r in self.session.query(DocumentRecord)
            .filter(DocumentRecord.status == "indexed")
            .all()
        }

        # ── deleted ──────────────────────────────────────────────────────
        deleted_paths = set(existing.keys()) - current_files
        for path in deleted_paths:
            self.remove_file(path)
        deleted_count = len(deleted_paths)

        # ── new / modified ───────────────────────────────────────────────
        indexed = skipped = failed = 0
        for file_path in current_files:
            record = existing.get(file_path)
            current_mtime = int(os.path.getmtime(file_path))

            if record and record.file_mtime == current_mtime:
                skipped += 1
                continue

            try:
                if record:
                    self._remove_chunks_for_file(file_path)
                self._index_file(file_path)
                indexed += 1
            except Exception as exc:
                logger.error("Failed to index %s: %s", file_path, exc)
                if record:
                    record.status = "failed"
                    record.error_message = str(exc)
                    self.session.add(record)
                else:
                    new_record = DocumentRecord(
                        file_path=file_path,
                        file_name=os.path.basename(file_path),
                        file_type=Path(file_path).suffix.lower().lstrip("."),
                        status="failed",
                        error_message=str(exc),
                    )
                    self.session.add(new_record)
                failed += 1

        self.session.commit()
        return {"indexed": indexed, "skipped": skipped, "failed": failed, "deleted": deleted_count}

    def _index_file(self, file_path: str) -> DocumentRecord:
        """Parse → chunk → embed → store a single file.  Caller must commit."""
        emb_svc = self._get_embedding_service()

        # 1. Parse
        text, metadata = parse_file(file_path)
        if not text.strip():
            raise ValueError("Document produced no readable text (scanned PDF perhaps?)")

        # 2. Chunk
        chunks = chunk_text(text, self.chunk_size, self.chunk_overlap)
        if not chunks:
            raise ValueError("Document produced zero chunks after splitting")

        # 3. Embed
        embeddings = emb_svc.embed(chunks)

        # 4. Store in ChromaDB
        metadatas = [
            {
                "file_path": file_path,
                "file_name": metadata["file_name"],
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i in range(len(chunks))
        ]
        self.vector_store.add(texts=chunks, embeddings=embeddings, metadatas=metadatas)

        # 5. Upsert DocumentRecord
        record = self.session.query(DocumentRecord).filter_by(file_path=file_path).first()
        current_mtime = int(os.path.getmtime(file_path))
        if record:
            record.file_size = metadata["file_size"]
            record.file_mtime = current_mtime
            record.chunk_count = len(chunks)
            record.total_chars = len(text)
            record.status = "indexed"
            record.error_message = None
            record.updated_at = datetime.datetime.now(datetime.timezone.utc)
        else:
            record = DocumentRecord(
                file_path=file_path,
                file_name=metadata["file_name"],
                file_type=metadata["file_type"],
                file_size=metadata["file_size"],
                file_mtime=current_mtime,
                chunk_count=len(chunks),
                total_chars=len(text),
                status="indexed",
            )
        self.session.add(record)
        self.session.flush()
        return record

    def _remove_chunks_for_file(self, file_path: str):
        """Remove all chunks for a single file from ChromaDB."""
        self.vector_store.delete_by_filter({"file_path": file_path})

    def remove_file(self, file_path: str) -> bool:
        """Soft-delete a document: remove chunks + mark record as deleted."""
        self._remove_chunks_for_file(file_path)
        record = self.session.query(DocumentRecord).filter_by(file_path=file_path).first()
        if record:
            record.status = "deleted"
            record.updated_at = datetime.datetime.now(datetime.timezone.utc)
            self.session.add(record)
        return True

    def list_documents(self) -> list[dict]:
        """All currently indexed documents, newest first."""
        records = (
            self.session.query(DocumentRecord)
            .filter(DocumentRecord.status == "indexed")
            .order_by(DocumentRecord.updated_at.desc())
            .all()
        )
        return [r.to_dict() for r in records]
