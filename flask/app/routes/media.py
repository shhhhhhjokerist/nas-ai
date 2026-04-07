import datetime
import os
from pathlib import Path

from flask import Blueprint, jsonify, request
from app.models.media import FileNode, Media
from app.services.scanner import FileScanner
from app.config import Config
from app import db

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


@bp.route("/scan", methods=['POST'])
def scan_files():
    try:
        media_root = request.json.get('media_root', Config.MEDIA_DIR)
        scanner = FileScanner(media_root)
        result = scanner.scan_and_sync()
        return jsonify({
            "msg": "scan_complete",
            "scanned": result['scanned'],
            "deleted": result['deleted']
        })
    except Exception as e:
        return jsonify({"msg": "scan_failed", "error": str(e)}), 500
    
@bp.route("/browse", methods=['GET'])
def browse_files():
    path = request.args.get('path', '')
    parent_id = request.args.get('parent_id', type=int)

    try:
        if parent_id:
            parent_node = FileNode.query.get(parent_id)
            if not parent_node or not parent_node.is_directory:
                return jsonify({"msg": "invalid parent_id"}), 400
            nodes = FileNode.query.filter_by(parent_id=parent_id, is_deleted=False).all()

            current_path = parent_node.path
        else:
            nodes = FileNode.query.filter_by(parent_id=None, is_deleted=False).all()
            current_path = '/'

        folders = [node.to_dict() for node in nodes if node.is_directory]
        files = [node.to_dict() for node in nodes if not node.is_directory]
        return jsonify({
            "current_path": current_path,
            "folders": [f.to_dict() for f in folders],
            "files": [f.to_dict() for f in files]
        })
    
    except Exception as e:
        return jsonify({"msg": "browse_failed", "error": str(e)}), 500
    
@bp.route("/info", methods=['GET'])
def get_file_info():
    node_id = request.args.get('id', type=int)
    path = request.args.get('path', '')

    try:
        if node_id:
            node = FileNode.query.get(node_id)
        elif path:
            node = FileNode.query.filter_by(path=path, is_deleted=False).first()
            if not node:
                return jsonify({"msg": "file not found"}), 404
        else:
            return jsonify({"msg": "missing id or path parameter"}), 400
        
    except Exception as e:
        return jsonify({"msg": "get_file_info_failed", "error": str(e)}), 500


@bp.route("/create-folder", methods=['POST'])
def create_folder():
    data = request.get_json()
    parent_id = data.get('parent_id')
    folder_name  = data.get('name')

    if not folder_name:
        return jsonify({"msg": "missing folder name"}), 400

    try:
        parent = FileNode.query.get(parent_id) if parent_id else None

        if parent:
            parent_path = Path(parent.abs_path)
            new_path = parent_path / folder_name
            relative_path = str(new_path.relative_to(Config.MEDIA_DIR))
        else:
            new_path = Config.MEDIA_DIR / folder_name
            relative_path = folder_name
            
        os.makedirs(new_path, exist_ok=True)

        new_folder = FileNode(
            name=folder_name,
            path=relative_path,
            abs_path=str(new_path.resolve()),
            parent_id=parent_id,
            is_directory=True,
            size=0,
            created_at=datetime.datetime.now(datetime.timezone.utc)
        )

        db.session.add(new_folder)
        db.session.commit()

        return jsonify({"msg": "folder created successfully", "folder": new_folder.to_dict()}), 201

    except FileExistsError:
        return jsonify({"msg": "folder already exists"}), 400
    except Exception as e:
        return jsonify({"msg": "create_folder_failed", "error": str(e)}), 500
    
@bp.route("/upload", methods=['POST'])
def upload_file():
    try:
        file = request.files.get('file')
        parent_id = request.form.get('parent_id', type=int)
        if not file:
            return jsonify({"msg": "no file uploaded"}), 400
        
        parent = FileNode.query.get(parent_id) if parent_id else None

        if parent:
            save_dir = Path(parent.abs_path)
            relative_path = parent.path / file.filename
        else:
            save_dir = Config.MEDIA_DIR
            relative_path = file.filename

        save_dir.mkdir(parents=True, exist_ok=True)

        file_path = save_dir / file.filename
        file.save(file_path)

        new_file = FileNode(
            name=file.filename,
            path=str(relative_path),
            abs_path=str(file_path.resolve()),
            parent_id=parent_id,
            is_directory=False,
            size=file_path.stat().st_size,
            filt_type=Path(file.name).suffix.lower()[1:],
            mime_type=file.mimetype,
            created_at=datetime.datetime.now(datetime.timezone.utc)
        )

        return jsonify({"msg": "file uploaded successfully", "file": new_file.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "upload_failed", "error": str(e)}), 500

@bp.route("/download/<int:file_id>", methods=['GET'])
def download_file(file_id):
    try:
        file_node = FileNode.query.get(file_id)
        if not file_node or file_node.is_directory:
            return jsonify({"msg": "file not found"}), 404
        
        if not os.path.exists(file_node.abs_path):
            return jsonify({"msg": "file not found on disk"}), 404
        
        return send_file(
            file_node.abs_path,
            as_attachment=True,
            download_name=file_node.name,
        )
    except Exception as e:
        return jsonify({"msg": "download_failed", "error": str(e)}), 500
    
@bp.route("/rename", methods=['PUT'])
def rename_file():
    data = request.get_json()
    node_id = data.get('id')
    new_name = data.get('new_name')

    if not node_id or not new_name:
        return jsonify({"msg": "missing id or new_name parameter"}), 400
    
    try:
        node = FileNode.query.get(node_id)
        old_path = Path(node.abs_path)
        new_path = old_path.parent / new_name

        if new_path.exists():
            return jsonify({"msg": "a file with the new name already exists"}), 400
        
        os.rename(old_path, new_path)

        node.name = new_name
        node.path = str(Path(node.path).parent / new_name)
        node.abs_path = str(new_path.resolve())

        if node.is_directory:
            old_prefix = node.path
            new_prefix = str(Path(node.path).parent / new_name)

            child_nodes = FileNode.query.filter(FileNode.path.startswith(old_prefix)).all()

            for child in child_nodes:
                child.path = child.path.replace(old_prefix, new_prefix, 1)
                child.abs_path = str(Path(child.abs_path).parent / new_name / Path(child.abs_path).relative_to(old_path.parent))

        db.session.commit()

        return jsonify({"msg": "rename successful", "node": node.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "rename_failed", "error": str(e)}), 500

@bp.route("/delete", methods=['DELETE'])
def delete_file():
    data = request.get_json()
    node_id = data.get('id')
    permanent = data.get('permanent', True)

    if not node_id:
        return jsonify({"msg": "missing id parameter"}), 400
    
    try:
        node = FileNode.query.get(node_id)

        if permanent:
            if os.path.exists(node.abs_path):
                if node.is_directory:
                    os.rmdir(node.abs_path)
                else:
                    os.remove(node.abs_path)

            db.session.delete(node)
        else:
            node.is_deleted = True
        
        db.session.commit()

        return jsonify({"msg": "delete successful"})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "delete_failed", "error": str(e)}), 500
    
@bp.route("/search")
def search_files():
    pass

@bp.route("/move", methods=['POST'])
def move_file():
    pass


