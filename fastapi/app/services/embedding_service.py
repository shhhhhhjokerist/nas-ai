"""BGE embedding model wrapper — lazy singleton to avoid blocking startup."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_embedding_service: Optional["EmbeddingService"] = None


class EmbeddingService:
    """Wraps a sentence-transformers model for embedding documents and queries."""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        logger.info("Loading embedding model: %s", model_name)
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()
        logger.info("Embedding model loaded.  Dimension: %d", self.dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.  Returns a list of float vectors."""
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self.embed([text])[0]


def get_embedding_service(model_name: str = None) -> EmbeddingService:
    """Lazy singleton factory — model is loaded once and reused.

    Parameters
    ----------
    model_name : str or None
        Override the default model.  Only used on the *first* call.
    """
    global _embedding_service
    if _embedding_service is None:
        from app.config import get_settings

        name = model_name or get_settings().EMBEDDING_MODEL_NAME
        _embedding_service = EmbeddingService(model_name=name)
    return _embedding_service
