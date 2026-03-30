from flask import Blueprint, jsonify
from app.services.scanner import scan_directory

bp = Blueprint('scan', __name__, url_prefix='/scan')

MEDIA_DIR = '/Users/a1-6/Movies'

@bp.route("/", methods=['POST'])
def scan():
    files = scan_directory(MEDIA_DIR)
    return jsonify({
        "msg", "scan_complete",
        "new_files", len(files)
        })
