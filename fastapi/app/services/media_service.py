import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.media import FileNode


VIDEO_EXTENSIONS = {
	".mp4",
	".mkv",
	".avi",
	".mov",
	".flv",
	".webm",
	".m4v",
}


def _normalize_base_url(base_url: str) -> str:
	return base_url.rstrip("/")


def _contains_video_hint(node: FileNode) -> bool:
	ext = Path(node.name).suffix.lower()
	return bool(
		(node.mime_type and node.mime_type.startswith("video"))
		or ext in VIDEO_EXTENSIONS
	)


def _safe_like_keyword(keyword: str) -> str:
	return keyword.strip().replace("%", "").replace("_", "")


def search_nodes(
	session: Session,
	keyword: str,
	only_directory: bool = False,
	only_file: bool = False,
	limit: int = 20,
) -> List[FileNode]:
	cleaned = _safe_like_keyword(keyword)
	if not cleaned:
		return []

	query = session.query(FileNode).filter(FileNode.is_deleted == False)
	query = query.filter(
		or_(
			FileNode.name.ilike(f"%{cleaned}%"),
			FileNode.path.ilike(f"%{cleaned}%"),
		)
	)

	if only_directory:
		query = query.filter(FileNode.is_directory == True)
	if only_file:
		query = query.filter(FileNode.is_directory == False)

	return query.order_by(FileNode.is_directory.desc(), FileNode.name.asc()).limit(limit).all()


def choose_best_match(
	nodes: List[FileNode],
	keyword: str,
	prefer_directory: Optional[bool] = None,
	prefer_video: bool = False,
) -> Optional[FileNode]:
	if not nodes:
		return None

	keyword_lower = keyword.lower()

	def score(node: FileNode) -> tuple:
		name_lower = node.name.lower()
		exact = 0 if name_lower == keyword_lower else 1
		name_contains = 0 if keyword_lower in name_lower else 1
		dir_penalty = 0
		if prefer_directory is True:
			dir_penalty = 0 if node.is_directory else 1
		elif prefer_directory is False:
			dir_penalty = 0 if not node.is_directory else 1

		video_penalty = 0
		if prefer_video:
			video_penalty = 0 if _contains_video_hint(node) else 1

		name_len = len(node.name)
		return (exact, name_contains, dir_penalty, video_penalty, name_len, node.id)

	return sorted(nodes, key=score)[0]


def build_file_urls(node: FileNode, base_url: str) -> Dict[str, str]:
	root = _normalize_base_url(base_url)
	urls = {
		"info_url": f"{root}/media/info?id={node.id}",
	}
	if node.is_directory:
		urls["browse_url"] = f"{root}/media/browse?parent_id={node.id}"
	else:
		urls["download_url"] = f"{root}/media/download/{node.id}"
		if _contains_video_hint(node):
			urls["play_url"] = f"{root}/media/play/{node.id}"
	return urls


def serialize_node(node: FileNode) -> Dict[str, Any]:
	return {
		"id": node.id,
		"name": node.name,
		"path": node.path,
		"abs_path": node.abs_path,
		"parent_id": node.parent_id,
		"is_directory": node.is_directory,
		"size": node.size,
		"file_type": node.file_type,
		"mime_type": node.mime_type,
		"media_type": node.media_type,
		"created_at": node.create_at.isoformat() if getattr(node, "create_at", None) else None,
		"update_at": node.update_at.isoformat() if getattr(node, "update_at", None) else None,
		"is_deleted": node.is_deleted,
	}


def move_node(session: Session, node: FileNode, destination: FileNode) -> FileNode:
	src_abs = Path(node.abs_path)
	dst_abs = Path(destination.abs_path) / node.name
	if dst_abs.exists():
		raise ValueError(f"目标目录已存在同名文件: {node.name}")
	if not src_abs.exists():
		raise ValueError(f"源文件不存在: {node.abs_path}")

	old_rel = node.path
	new_rel = str((Path(destination.path) / node.name).as_posix())

	os.rename(src_abs, dst_abs)

	node.parent_id = destination.id
	node.abs_path = str(dst_abs.resolve())
	node.path = new_rel
	node.mime_type = node.mime_type or mimetypes.guess_type(node.name)[0]
	session.add(node)

	if node.is_directory:
		descendants = session.query(FileNode).filter(FileNode.path.ilike(f"{old_rel}/%")).all()
		for child in descendants:
			child.path = child.path.replace(old_rel + "/", new_rel + "/", 1)
			old_child_abs = Path(child.abs_path)
			if old_child_abs.is_absolute() and old_child_abs.exists():
				child.abs_path = str(old_child_abs.resolve())
			else:
				child.abs_path = str((dst_abs / Path(child.path).relative_to(new_rel)).resolve())
			session.add(child)

	session.commit()
	session.refresh(node)
	return node


def copy_node(session: Session, node: FileNode, destination: FileNode, new_name: Optional[str] = None) -> FileNode:
	target_name = new_name or node.name
	target_abs = Path(destination.abs_path) / target_name
	target_rel = str((Path(destination.path) / target_name).as_posix())

	if target_abs.exists():
		raise ValueError(f"目标目录或文件已存在: {target_name}")

	if node.is_directory:
		os.makedirs(target_abs, exist_ok=False)
		copied = FileNode(
			name=target_name,
			path=target_rel,
			abs_path=str(target_abs.resolve()),
			parent_id=destination.id,
			is_directory=True,
			size=0,
			file_type=None,
			mime_type=None,
			media_type=node.media_type,
			duration=node.duration,
			thumbnail_path=node.thumbnail_path,
			_metadata=node._metadata,
			is_hidden=node.is_hidden,
			is_deleted=False,
		)
		session.add(copied)
		session.flush()

		children = (
			session.query(FileNode)
			.filter(FileNode.parent_id == node.id, FileNode.is_deleted == False)
			.order_by(FileNode.is_directory.desc(), FileNode.name.asc())
			.all()
		)
		for child in children:
			copy_node(session, child, copied)
		return copied

	shutil.copy2(node.abs_path, target_abs)
	copied = FileNode(
		name=target_name,
		path=target_rel,
		abs_path=str(target_abs.resolve()),
		parent_id=destination.id,
		is_directory=False,
		size=target_abs.stat().st_size,
		file_type=node.file_type or Path(target_name).suffix.lower().lstrip("."),
		mime_type=node.mime_type or mimetypes.guess_type(target_name)[0],
		media_type=node.media_type,
		duration=node.duration,
		thumbnail_path=node.thumbnail_path,
		_metadata=node._metadata,
		is_hidden=node.is_hidden,
		is_deleted=False,
	)
	session.add(copied)
	session.flush()
	return copied
