"""Document management endpoints — scan, upload, list, delete."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models.document import DocumentRecord
from app.models.user import User
from app.services.document_parser import SUPPORTED_EXTENSIONS
from app.services.vector_store import DocumentIndexer

router = APIRouter(prefix="/documents", tags=["documents"])


class ScanResponse(BaseModel):
    msg: str
    indexed: int
    skipped: int
    failed: int
    deleted: int

    model_config = {"from_attributes": True}


@router.post("/scan", response_model=ScanResponse)
async def scan_documents(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Walk MEDIA_DIR and index all supported files."""
    try:
        indexer = DocumentIndexer(session)
        result = indexer.scan_and_index()
        return {"msg": "scan_complete", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scan_failed: {str(exc)}")


@router.get("/", response_model=list[dict])
async def list_documents(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all currently indexed documents."""
    indexer = DocumentIndexer(session)
    return indexer.list_documents()


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a document from the index."""
    record = session.query(DocumentRecord).get(doc_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")

    indexer = DocumentIndexer(session)
    indexer.remove_file(record.file_path)
    session.commit()
    return {"msg": "document removed from index", "file_name": record.file_name}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a single file and index it immediately."""
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    settings = get_settings()
    docs_dir = Path(settings.MEDIA_DIR)
    docs_dir.mkdir(parents=True, exist_ok=True)
    dest_path = docs_dir / file.filename
    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    indexer = DocumentIndexer(session)
    try:
        record = indexer._index_file(str(dest_path.resolve()))
        session.commit()
        return {"msg": "uploaded and indexed", "document": record.to_dict()}
    except Exception as exc:
        if dest_path.exists():
            dest_path.unlink()
        raise HTTPException(status_code=500, detail=f"index_failed: {str(exc)}")
