import datetime
import mimetypes
import os
from pathlib import Path
from tkinter import Image
from app.models.media import FileNode, Media
from app import db

MEDIA_EXTENSIONS = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v']

def scan_directory(path):
    def is_hidden(filepath):
        if os.name == 'nt':  # Windows
            try:
                # print(bool(os.stat(filepath).st_file_attributes & os.stat.FILE_ATTRIBUTE_HIDDEN))
                # return bool(os.stat(filepath).st_file_attributes & os.stat.FILE_ATTRIBUTE_HIDDEN)
                return bool(os.stat(filepath).st_file_attributes & 2)
            except:
                return False
        else:  # Unix/Linux/Mac
            return os.path.basename(filepath).startswith('.')

    new_files = []
    
    for root, dirs, files in os.walk(path):
        
        dirs[:] = [d for d in dirs if not is_hidden(os.path.join(root, d))]
        for file in files:
            if any(file.endswith(ext) for ext in MEDIA_EXTENSIONS):
                full_path = os.path.join(root, file)

                exists = Media.query.filter_by(file_path=full_path).first()
                if not exists:
                    media = Media(
                        title=file,
                        file_path=os.path.relpath(full_path, path),
                        media_type='video',
                        file_abs_path=full_path
                    )
                    db.session.add(media)
                    new_files.append(full_path)

    db.session.commit()
    return new_files


class FileScanner:
    def __init__(self, root_path):
        self.root_path = Path(root_path).resolve()

    def scan_and_sync(self):
        existing_paths = {node.abs_path for node in FileNode.query.all()}
        current_paths = set()

        self._scan_directory(self.root_path, None, current_paths)

        deleted_paths = existing_paths - current_paths
        for path in deleted_paths:
            node = FileNode.query.filter_by(abs_path=path).first()
            if node:
                node.is_deleted = True
                db.session.add(node)

        return {
            'scanned': len(current_paths),
            'deleted': len(deleted_paths)
        }
    
    def _scan_directory(self, current_path, parent_node, current_paths_set):
        try:
            for item in current_path.iterdir():
                if bool(os.stat(item).st_file_attributes & 2):
                    continue

                abs_path = str(item.resolve())
                current_paths_set.add(abs_path)

                node = FileNode.query.filter_by(abs_path=abs_path).first()
                if node:
                    node.name = item.name
                    node.size = item.stat().st_size if item.is_file() else 0
                    node.updated_at = datetime.datetime.now(datetime.timezone.utc)
                else:
                    node = FileNode(
                        name=item.name,
                        path=str(current_path.relative_to(self.root_path.parent)),
                        abs_path=abs_path,
                        parent_id=parent_node.id if parent_node else None,
                        is_directory=item.is_dir(),
                        size=item.stat().st_size if item.is_file() else 0,
                        file_type=item.suffix.lower() if item.is_file() else None,
                        mime_type=mimetypes.guess_type(str(item))[0] if item.is_file() else None,
                        # mime_type=None,
                        create_at=datetime.datetime.now(datetime.timezone.utc)
                    )

                    if node.mime_type:
                        if node.mime_type.startswith('video'):
                            node.media_type = 'video'
                        elif node.mime_type.startswith('image'):
                            node.media_type = 'image'
                        else:
                            node.media_type = 'other'
                    
                    db.session.add(node)
                    db.session.flush()

                # 递归扫描子目录
                if item.is_dir():
                    self._scan_directory(item, node, current_paths_set)
        except PermissionError:
            pass  # 忽略权限错误
        except Exception as e:
            print(f"Error scanning {current_path}: {e}")

    def extract_media_info(self, file_node):
        if not file_node.is_directory and file_node.media_type in ['image', 'video']:
            
            if file_node.media_type == 'image':
                try:
                    with Image.open(file_node.abs_path) as img:
                        media = Media.query.filter_by(file_node_id=file_node.id).first()

                        if not media:
                            media = Media(
                                title=file_node.name,
                                file_path=file_node.path,
                                file_abs_path=file_node.abs_path,
                                media_type='image',
                                width=img.width,
                                height=img.height
                            )
                            db.session.add(media)
                        else:
                            media.width = img.width
                            media.height = img.height
                            media.update_at = datetime.datetime.now(datetime.timezone.utc)
                            db.session.add(media)
                except Exception as e:
                    print(f"Error extracting image info for {file_node.abs_path}: {e}")
            elif file_node.media_type == 'video':

                try:
                    import ffmpeg
                    probe = ffmpeg.probe(file_node.abs_path)
                    video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
                    if video_streams:
                        video_stream = video_streams[0]
                        media = Media.query.filter_by(file_node_id=file_node.id).first()

                        if not media:
                            media = Media(
                                title=file_node.name,
                                file_path=file_node.path,
                                file_abs_path=file_node.abs_path,
                                media_type='video',
                                duration=int(float(video_stream.get('duration', 0))),
                                width=int(video_stream.get('width', 0)),
                                height=int(video_stream.get('height', 0))
                            )
                            db.session.add(media)
                        else:
                            media.duration = int(float(video_stream.get('duration', 0)))
                            media.width = int(video_stream.get('width', 0))
                            media.height = int(video_stream.get('height', 0))
                            media.update_at = datetime.datetime.now(datetime.timezone.utc)
                            db.session.add(media)

                    # from mutagen.mp4 import MP4
                    # from mutagen.avi import AVI
                    
                    # # 简化处理，实际需要根据格式选择
                    # media = Media.query.filter_by(file_node_id=file_node.id).first()
                    # if not media:
                    #     media = Media(
                    #         title=file_node.name,
                    #         file_path=file_node.path,
                    #         file_abs_path=file_node.abs_path,
                    #         media_type='video'
                    #     )
                    #     db.session.add(media)
                    
                    # db.session.commit()
                except Exception as e:
                    print(f"Error extracting video info for {file_node.abs_path}: {e}")

                

                    