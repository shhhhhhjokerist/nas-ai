"""Document tracking model — analogous to FileNode for media files."""

import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text

from app.db import Base


class DocumentRecord(Base):
    __tablename__ = "document_records"

    id = Column(Integer, primary_key=True)
    file_path = Column(String(500), nullable=False, unique=True, comment="Absolute path on disk")
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False, comment="pdf / docx / txt / md")
    file_size = Column(BigInteger, default=0)
    file_mtime = Column(BigInteger, default=0, comment="os.path.getmtime as int — used to detect changes")
    chunk_count = Column(Integer, default=0)
    total_chars = Column(Integer, default=0)
    chroma_collection = Column(String(100), default="documents")
    status = Column(String(20), default="indexed", comment="indexed / failed / deleted")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "chunk_count": self.chunk_count,
            "total_chars": self.total_chars,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
