from flask import Blueprint, jsonify
from app.models.media import Media

bp = Blueprint('media', __name__, url_prefix='/media')

@bp.route("/", methods=['GET'])
def list_media():
    data = Media.query.all()

    return jsonify([
        {
        "id": m.id,
        "title": m.title,
        "path": m.file_path
        }
        for m in data
    ])
