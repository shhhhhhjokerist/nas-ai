from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Float,
)
from sqlalchemy.orm import relationship
from app.db import Base


class FileNode(Base):
    __tablename__ = "file_nodes"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    path = Column(String(500), nullable=False)
    abs_path = Column(String(500), nullable=False)
    parent_id = Column(Integer, ForeignKey("file_nodes.id"), nullable=True)
    is_directory = Column(Boolean, default=False)
    size = Column(BigInteger, default=0)
    file_type = Column(String(50))
    mime_type = Column(String(100))
    media_type = Column(String(50))  # e.g. movie, tv_show, music

    duration = Column(Integer)
    thumbnail_path = Column(String(500))
    _metadata = Column(JSON, default={})

    # ── Permissions ──
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    visibility = Column(String(20), default="private")  # private | public | shared

    is_hidden = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ──
    parent = relationship("FileNode", remote_side=[id], backref="children")
    owner = relationship("User", backref="files")

    def to_dict(self, include_children: bool = False) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "abs_path": self.abs_path,
            "parent_id": self.parent_id,
            "is_directory": self.is_directory,
            "size": self.size,
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "media_type": self.media_type,
            "owner_id": self.owner_id,
            "visibility": self.visibility,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if not self.is_directory:
            result["duration"] = self.duration
            result["thumbnail_path"] = self.thumbnail_path
            result["metadata"] = self._metadata

        if include_children and self.is_directory:
            result["children"] = [
                child.to_dict()
                for child in self.children
                if not child.is_deleted
            ]

        return result


class Media(Base):
    __tablename__ = "medias"

    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    file_path = Column(String(500), unique=True)
    file_abs_path = Column(String(500), unique=True)
    media_type = Column(String(50))  # e.g. image, video

    duration = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)
    thumbnail_path = Column(String(500))

    play_count = Column(Integer, default=0)
    last_played_at = Column(DateTime)
    play_progress = Column(Float, default=0.0)

    is_hidden = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    file_node_id = Column(Integer, ForeignKey("file_nodes.id"), nullable=True)
    file_node = relationship("FileNode", backref="media")
