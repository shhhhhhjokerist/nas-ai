import datetime
from app import db


class FileNode(db.Model):
    __tablename__ = 'file_nodes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    path = db.Column(db.String(500), nullable=False, unique=True)
    abs_path = db.Column(db.String(500), nullable=False, unique=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('file_nodes.id'), nullable=True)
    is_directory = db.Column(db.Boolean, default=False)
    size = db.Column(db.BigInteger, default=0)
    file_type = db.Column(db.String(50))  # e.g., 'video', 'image', 'document'
    mime_type = db.Column(db.String(100))
    media_type = db.Column(db.String(50))  # e.g., 'movie', 'tv_show', 'music'

    duration = db.Column(db.Integer)
    thumbnail_path = db.Column(db.String(500)) # 缩略图路径
    _metadata = db.Column(db.JSON, default={})

    is_hidden = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    create_at = db.Column(db.DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    update_at = db.Column(db.DateTime, default=datetime.datetime.now(datetime.timezone.utc), onupdate=datetime.datetime.now(datetime.timezone.utc))

    parent = db.relationship('FileNode', remote_side=[id], backref='children')

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
    

class Media(db.Model):
    __tablename__ = 'medias'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    file_path = db.Column(db.String(500), unique=True)
    file_abs_path = db.Column(db.String(500), unique=True)
    media_type = db.Column(db.String(50))  # e.g., 'image', 'video'

    duration = db.Column(db.Integer)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    thunmbnail_path = db.Column(db.String(500)) # 缩略图路径

    play_count = db.Column(db.Integer, default=0)
    last_played_at = db.Column(db.DateTime)
    play_progress = db.Column(db.Float, default=0.0)

    is_hidden = db.Column(db.Boolean, default=False)
    create_at = db.Column(db.DateTime, default=datetime.datetime.now(datetime.timezone.utc))

    file_node_id = db.Column(db.Integer, db.ForeignKey('file_nodes.id'), nullable=True)
    file_node = db.relationship('FileNode', backref='media')
