import datetime
import mimetypes
import os
from pathlib import Path
from tkinter import Image
from sqlalchemy import select
from app.models.media import FileNode, Media
from app.db import Base, get_db

MEDIA_EXTENSIONS = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v']


class FileScanner:
    def __init__(self, root_path, session):
        self.root_path = Path(root_path).resolve()
        self.session = session  # 使用传入的 session

    def scan_and_sync(self):
        """扫描目录并同步数据库"""
        # 使用 self.session 查询已存在的路径
        stmt = select(FileNode.abs_path).where(FileNode.is_deleted == False)
        existing_paths = {row[0] for row in self.session.execute(stmt).all()}
        current_paths = set()

        self._scan_directory(self.root_path, None, current_paths)

        # 标记已删除的文件
        deleted_paths = existing_paths - current_paths
        for path in deleted_paths:
            stmt = select(FileNode).where(FileNode.abs_path == path)
            node = self.session.execute(stmt).scalar_one_or_none()
            if node:
                node.is_deleted = True
                self.session.add(node)

        self.session.commit()

        return {
            'scanned': len(current_paths),
            'deleted': len(deleted_paths)
        }
    
    def _scan_directory(self, current_path, parent_node, current_paths_set):
        """递归扫描目录"""
        try:
            for item in current_path.iterdir():
                # 跳过隐藏文件
                if self._is_hidden(item):
                    continue

                abs_path = str(item.resolve())
                current_paths_set.add(abs_path)

                # 查询节点是否存在
                stmt = select(FileNode).where(FileNode.abs_path == abs_path)
                node = self.session.execute(stmt).scalar_one_or_none()
                
                if node:
                    # 更新现有节点
                    node.name = item.name
                    node.size = item.stat().st_size if item.is_file() else 0
                    node.updated_at = datetime.datetime.now(datetime.timezone.utc)
                else:
                    # 创建新节点
                    node = FileNode(
                        name=item.name,
                        path=str(current_path.relative_to(self.root_path.parent)),
                        abs_path=abs_path,
                        parent_id=parent_node.id if parent_node else None,
                        is_directory=item.is_dir(),
                        size=item.stat().st_size if item.is_file() else 0,
                        file_type=item.suffix.lower() if item.is_file() else None,
                        mime_type=mimetypes.guess_type(str(item))[0] if item.is_file() else None,
                        create_at=datetime.datetime.now(datetime.timezone.utc)
                    )

                    # 设置媒体类型
                    if node.mime_type:
                        if node.mime_type.startswith('video'):
                            node.media_type = 'video'
                        elif node.mime_type.startswith('image'):
                            node.media_type = 'image'
                        else:
                            node.media_type = 'other'
                    
                    self.session.add(node)
                    self.session.flush()  # 获取 ID

                # 递归扫描子目录
                if item.is_dir():
                    self._scan_directory(item, node, current_paths_set)
                    
        except PermissionError:
            pass  # 忽略权限错误
        except Exception as e:
            print(f"Error scanning {current_path}: {e}")

    def extract_media_info(self, file_node):
        """提取媒体文件信息"""
        if not file_node.is_directory and file_node.media_type in ['image', 'video']:
            
            if file_node.media_type == 'image':
                self._extract_image_info(file_node)
            elif file_node.media_type == 'video':
                self._extract_video_info(file_node)
    
    def _extract_image_info(self, file_node):
        """提取图片信息"""
        try:
            from PIL import Image
            with Image.open(file_node.abs_path) as img:
                # 查询是否存在
                stmt = select(Media).where(Media.file_node_id == file_node.id)
                media = self.session.execute(stmt).scalar_one_or_none()

                if not media:
                    media = Media(
                        title=file_node.name,
                        file_path=file_node.path,
                        file_abs_path=file_node.abs_path,
                        file_node_id=file_node.id,
                        media_type='image',
                        width=img.width,
                        height=img.height
                    )
                    self.session.add(media)
                else:
                    media.width = img.width
                    media.height = img.height
                    media.update_at = datetime.datetime.now(datetime.timezone.utc)
                    self.session.add(media)
                
                self.session.commit()
                
        except Exception as e:
            print(f"Error extracting image info for {file_node.abs_path}: {e}")
    
    def _extract_video_info(self, file_node):
        """提取视频信息"""
        try:
            import ffmpeg
            probe = ffmpeg.probe(file_node.abs_path)
            video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
            
            if video_streams:
                video_stream = video_streams[0]
                
                # 查询是否存在
                stmt = select(Media).where(Media.file_node_id == file_node.id)
                media = self.session.execute(stmt).scalar_one_or_none()

                if not media:
                    media = Media(
                        title=file_node.name,
                        file_path=file_node.path,
                        file_abs_path=file_node.abs_path,
                        file_node_id=file_node.id,
                        media_type='video',
                        duration=int(float(video_stream.get('duration', 0))),
                        width=int(video_stream.get('width', 0)),
                        height=int(video_stream.get('height', 0))
                    )
                    self.session.add(media)
                else:
                    media.duration = int(float(video_stream.get('duration', 0)))
                    media.width = int(video_stream.get('width', 0))
                    media.height = int(video_stream.get('height', 0))
                    media.update_at = datetime.datetime.now(datetime.timezone.utc)
                    self.session.add(media)
                
                self.session.commit()
                
        except Exception as e:
            print(f"Error extracting video info for {file_node.abs_path}: {e}")
    
    @staticmethod
    def _is_hidden(filepath):
        """检查文件是否隐藏"""
        if os.name == 'nt':  # Windows
            try:
                return bool(os.stat(filepath).st_file_attributes & 2)
            except:
                return False
        else:  # Unix/Linux/Mac
            return os.path.basename(filepath).startswith('.')


# 保留原有的函数版本（用于向后兼容）
def scan_directory(path, session):
    """扫描目录并添加媒体文件（函数版本）"""
    def is_hidden(filepath):
        if os.name == 'nt':  # Windows
            try:
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

                # 使用传入的 session 查询
                stmt = select(Media).where(Media.file_abs_path == full_path)
                exists = session.execute(stmt).scalar_one_or_none()
                
                if not exists:
                    media = Media(
                        title=file,
                        file_path=os.path.relpath(full_path, path),
                        media_type='video',
                        file_abs_path=full_path
                    )
                    session.add(media)
                    new_files.append(full_path)

    session.commit()
    return new_files