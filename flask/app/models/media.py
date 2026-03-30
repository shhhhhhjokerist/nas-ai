from app.extensions import db
import datetime

class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    filepath = db.Column(db.String(500), unique=True)
    media_type = db.Column(db.String(50))  # e.g., 'image', 'video'
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
