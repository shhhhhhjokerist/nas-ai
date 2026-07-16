"""
Application configuration via pydantic-settings.
All values can be overridden by environment variables or a .env file.
"""
import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──
    APP_NAME: str = "NAS-AI"
    DEBUG: bool = False

    # ── Database ──
    DATABASE_URL: str = "sqlite:///./test.db"

    # ── JWT ──
    JWT_SECRET_KEY: str = "change-me-in-production-use-a-strong-secret"
    JWT_ACCESS_TOKEN_EXPIRES: int = 24 * 60 * 60       # 24 hours
    JWT_REFRESH_TOKEN_EXPIRES: int = 30 * 24 * 60 * 60  # 30 days

    # ── NAS / Media ──
    MEDIA_DIR: str = ""  # NAS root — MUST be set in .env / env

    # ── RAG / ChromaDB ──
    CHROMA_DB_DIR: str = ""
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-zh-v1.5"
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    RETRIEVAL_TOP_K: int = 5

    # ── AI Agent (DeepSeek / OpenAI-compatible) ──
    AGENT_MODEL: str = "deepseek-v4-flash"
    AGENT_BASE_URL: str = "https://api.deepseek.com/v1"
    AGENT_API_KEY: str = ""  # MUST be set in .env / env
    AGENT_TEMPERATURE: float = 0.2
    AGENT_MAX_TOKENS: int = 1024

    # ── App base URL (for building file URLs returned by agent) ──
    AGENT_BASE_APP_URL: str = "http://127.0.0.1:8000"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Compute CHROMA_DB_DIR default relative to the fastapi/ dir
        if not self.CHROMA_DB_DIR:
            fastapi_dir = Path(__file__).resolve().parent.parent
            self.CHROMA_DB_DIR = str(fastapi_dir / "chroma_db")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
