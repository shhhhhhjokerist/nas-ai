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
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".m4v",
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


# ═══════════════════════════════════════════════════════════════════
#  Query helpers
# ═══════════════════════════════════════════════════════════════════

def search_nodes(
    session: Session,
    keyword: str,
    only_directory: bool = False,
    only_file: bool = False,
    limit: int = 20,
    user_id: Optional[int] = None,
) -> List[FileNode]:
    """Search files/folders by keyword.  When *user_id* is given, only
    return nodes the user can see (owner or public)."""
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

    # Permission filter
    if user_id is not None:
        query = query.filter(
            or_(
                FileNode.owner_id == user_id,
                FileNode.visibility == "public",
            )
        )

    return query.order_by(FileNode.is_directory.desc(), FileNode.name.asc()).limit(limit).all()


def get_node_if_visible(
    session: Session,
    node_id: int,
    user_id: Optional[int] = None,
) -> Optional[FileNode]:
    """Return the node only if the given user can see it."""
    node = session.get(FileNode, node_id)
    if node is None or node.is_deleted:
        return None
    if user_id is None:
        return node
    if node.owner_id == user_id or node.visibility == "public":
        return node
    return None


def get_children_visible(
    session: Session,
    parent_id: int,
    user_id: Optional[int] = None,
    limit: int = 50,
) -> List[FileNode]:
    """Children of a directory, filtered by visibility."""
    q = (
        session.query(FileNode)
        .filter(FileNode.parent_id == parent_id, FileNode.is_deleted == False)
    )
    if user_id is not None:
        q = q.filter(
            or_(
                FileNode.owner_id == user_id,
                FileNode.visibility == "public",
            )
        )
    return q.order_by(FileNode.is_directory.desc(), FileNode.name.asc()).limit(limit).all()


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


# ═══════════════════════════════════════════════════════════════════
#  URL builders
# ═══════════════════════════════════════════════════════════════════

def build_file_urls(node: FileNode, base_url: str) -> Dict[str, str]:
    root = _normalize_base_url(base_url)
    urls = {"info_url": f"{root}/media/info?id={node.id}"}
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
        "owner_id": node.owner_id,
        "visibility": node.visibility,
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        "is_deleted": node.is_deleted,
    }


# ═══════════════════════════════════════════════════════════════════
#  Mutations
# ═══════════════════════════════════════════════════════════════════

def rename_node(session: Session, node: FileNode, new_name: str) -> FileNode:
    """Rename a file or folder (both on disk and in DB)."""
    old_path = Path(node.abs_path)
    new_path = old_path.parent / new_name

    if new_path.exists():
        raise ValueError(f"A file with the new name already exists: {new_name}")

    os.rename(old_path, new_path)

    old_rel = node.path
    node.name = new_name
    node.path = str((Path(old_rel).parent / new_name).as_posix())
    node.abs_path = str(new_path.resolve())

    if node.is_directory:
        # Update all descendants' paths
        descendants = (
            session.query(FileNode)
            .filter(FileNode.path.ilike(f"{old_rel}/%"))
            .all()
        )
        for child in descendants:
            child.path = child.path.replace(old_rel, node.path, 1)
            session.add(child)

    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def delete_node(session: Session, node: FileNode, permanent: bool = True) -> None:
    """Delete a file or folder.  Soft-delete sets is_deleted=True.
    Permanent-delete also removes the file from disk."""
    if permanent:
        if os.path.exists(node.abs_path):
            if node.is_directory:
                # Remove empty directory; for non-empty use shutil.rmtree
                try:
                    os.rmdir(node.abs_path)
                except OSError:
                    shutil.rmtree(node.abs_path)
            else:
                os.remove(node.abs_path)
        session.delete(node)
    else:
        node.is_deleted = True
        session.add(node)

    session.commit()


def move_node(session: Session, node: FileNode, destination: FileNode) -> FileNode:
    src_abs = Path(node.abs_path)
    dst_abs = Path(destination.abs_path) / node.name
    if dst_abs.exists():
        raise ValueError(f"Target already exists: {node.name}")
    if not src_abs.exists():
        raise ValueError(f"Source file does not exist: {node.abs_path}")

    old_rel = node.path
    new_rel = str((Path(destination.path) / node.name).as_posix())

    os.rename(src_abs, dst_abs)

    node.parent_id = destination.id
    node.abs_path = str(dst_abs.resolve())
    node.path = new_rel
    node.mime_type = node.mime_type or mimetypes.guess_type(node.name)[0]
    session.add(node)

    if node.is_directory:
        descendants = (
            session.query(FileNode)
            .filter(FileNode.path.ilike(f"{old_rel}/%"))
            .all()
        )
        for child in descendants:
            child.path = child.path.replace(old_rel + "/", new_rel + "/", 1)
            old_child_abs = Path(child.abs_path)
            if old_child_abs.is_absolute() and old_child_abs.exists():
                child.abs_path = str(old_child_abs.resolve())
            else:
                child.abs_path = str(
                    (dst_abs / Path(child.path).relative_to(new_rel)).resolve()
                )
            session.add(child)

    session.commit()
    session.refresh(node)
    return node


def copy_node(
    session: Session,
    node: FileNode,
    destination: FileNode,
    new_name: Optional[str] = None,
) -> FileNode:
    target_name = new_name or node.name
    target_abs = Path(destination.abs_path) / target_name
    target_rel = str((Path(destination.path) / target_name).as_posix())

    if target_abs.exists():
        raise ValueError(f"Target already exists: {target_name}")

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
            owner_id=node.owner_id,
            visibility=node.visibility,
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
        owner_id=node.owner_id,
        visibility=node.visibility,
        is_hidden=node.is_hidden,
        is_deleted=False,
    )
    session.add(copied)
    session.flush()
    return copied
