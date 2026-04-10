import datetime

from sqlalchemy import Column, TEXT, INT, BIGINT, DATETIME, INTEGER, BOOLEAN, ForeignKey, BigInteger, JSON, FLOAT
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from app.db import Base

class FileNode(Base):
    __tablename__ = 'file_nodes'

    id = Column(INTEGER, primary_key=True)
    name = Column(TEXT(255), nullable=False)
    path = Column(TEXT(500), nullable=False, unique=False)
    abs_path = Column(TEXT(500), nullable=False, unique=False)
    parent_id = Column(INTEGER, ForeignKey('file_nodes.id'), nullable=True)
    is_directory = Column(BOOLEAN, default=False)
    size = Column(BigInteger, default=0)
    file_type = Column(TEXT(50))  # e.g., 'video', 'image', 'document'
    mime_type = Column(TEXT(100))
    media_type = Column(TEXT(50))  # e.g., 'movie', 'tv_show', 'music'

    duration = Column(INTEGER)
    thumbnail_path = Column(TEXT(500)) # 缩略图路径
    _metadata = Column(JSON, default={})

    is_hidden = Column(BOOLEAN, default=False)
    is_deleted = Column(BOOLEAN, default=False)
    create_at = Column(DATETIME, default=datetime.datetime.now(datetime.timezone.utc))
    update_at = Column(DATETIME, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

    parent = relationship('FileNode', remote_side=[id], backref='children')

    def to_dict(self, include_children=False):
        result = {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "is_directory": self.is_directory,
            "size": self.size,
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "media_type": self.media_type,
            "create_at": self.create_at.isoformat(),
            "update_at": self.update_at.isoformat()
        }

        if not self.is_directory:
            result["duration"] = self.duration
            result["thumbnail_path"] = self.thumbnail_path
            result["metadata"] = self.metadata

        if include_children and self.is_directory:
            result["children"] = [child.to_dict() for child in self.children if not child.is_deleted]

        return result
    

class Media(Base):
    __tablename__ = 'medias'

    id = Column(INTEGER, primary_key=True)
    title = Column(TEXT(255))
    file_path = Column(TEXT(500), unique=True)
    file_abs_path = Column(TEXT(500), unique=True)
    media_type = Column(TEXT(50))  # e.g., 'image', 'video'

    duration = Column(INTEGER)
    width = Column(INTEGER)
    height = Column(INTEGER)
    thunmbnail_path = Column(TEXT(500)) # 缩略图路径

    play_count = Column(INTEGER, default=0)
    last_played_at = Column(DATETIME)
    play_progress = Column(FLOAT, default=0.0)

    is_hidden = Column(BOOLEAN, default=False)
    create_at = Column(DATETIME, default=datetime.datetime.now(datetime.timezone.utc))

    file_node_id = Column(INTEGER, ForeignKey('file_nodes.id'), nullable=True)
    file_node = relationship('FileNode', backref='media')
