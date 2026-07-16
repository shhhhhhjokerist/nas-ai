"""
File management routes — browse, search, upload, download, play, CRUD.
All endpoints require authentication.  Users can only access files they
own or that are marked public.
"""
import datetime
import mimetypes
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import SessionDep, get_current_user
from app.models.media import FileNode, Media
from app.models.user import User
from app.schemas.media import (
    CreateFolderRequest,
    DeleteRequest,
    MoveRequest,
    CopyRequest,
    RenameRequest,
    ScanRequest,
)
from app.services.media_service import (
    copy_node,
    delete_node,
    move_node,
    rename_node,
    search_nodes,
    serialize_node,
)

router = APIRouter(prefix="/media", tags=["media"])


# ═══════════════════════════════════════════════════════════════════
#  Permission helpers
# ═══════════════════════════════════════════════════════════════════

def _get_node_or_404(
    session: Session,
    node_id: int,
    user: User,
) -> FileNode:
    """Return the node, or 404 if not found or not visible to *user*."""
    node = session.get(FileNode, node_id)
    if not node or node.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")
    if node.owner_id is not None and node.owner_id != user.id and node.visibility != "public":
        raise HTTPException(status_code=404, detail="File not found")
    return node


def _visible_query(session: Session, user: User):
    """Base query for nodes visible to *user*."""
    return (
        session.query(FileNode)
        .filter(FileNode.is_deleted == False)
        .filter(
            or_(
                FileNode.owner_id == user.id,
                FileNode.visibility == "public",
                FileNode.owner_id == None,  # legacy / unscanned
            )
        )
    )


# ═══════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.get("/")
async def list_media(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    return session.query(Media).all()


@router.post("/scan")
async def scan_files(
    request: ScanRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    settings = get_settings()
    media_root = request.media_root or settings.MEDIA_DIR
    if not media_root:
        raise HTTPException(status_code=400, detail="MEDIA_DIR not configured")

    from app.services.scanner import FileScanner

    scanner = FileScanner(media_root, session)
    result = scanner.scan_and_sync()
    return {
        "msg": "scan_complete",
        "scanned": result["scanned"],
        "deleted": result["deleted"],
    }


@router.get("/browse")
async def browse_files(
    session: SessionDep,
    parent_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
):
    if parent_id:
        parent = _get_node_or_404(session, parent_id, current_user)
        if not parent.is_directory:
            raise HTTPException(status_code=400, detail="Not a directory")
        nodes = (
            _visible_query(session, current_user)
            .filter(FileNode.parent_id == parent_id)
            .all()
        )
        current_path = parent.path
    else:
        nodes = (
            _visible_query(session, current_user)
            .filter(FileNode.parent_id == None)
            .all()
        )
        current_path = "/"

    folders = [serialize_node(n) for n in nodes if n.is_directory]
    files = [serialize_node(n) for n in nodes if not n.is_directory]
    return {"current_path": current_path, "folders": folders, "files": files}


@router.get("/info")
async def get_file_info(
    session: SessionDep,
    id: Optional[int] = Query(None),
    path: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    if id:
        node = _get_node_or_404(session, id, current_user)
    elif path:
        node = (
            _visible_query(session, current_user)
            .filter(FileNode.path == path)
            .first()
        )
        if not node:
            raise HTTPException(status_code=404, detail="File not found")
    else:
        raise HTTPException(status_code=400, detail="Missing id or path parameter")
    return serialize_node(node)


@router.post("/create-folder")
async def create_folder(
    request: CreateFolderRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    if not request.name:
        raise HTTPException(status_code=400, detail="Missing folder name")

    settings = get_settings()
    media_dir = Path(settings.MEDIA_DIR)

    parent = session.get(FileNode, request.parent_id) if request.parent_id else None

    if parent:
        parent_path = Path(parent.abs_path)
        new_path = parent_path / request.name
        relative_path = str((Path(parent.path) / request.name).as_posix())
    else:
        new_path = media_dir / request.name
        relative_path = request.name

    if new_path.exists():
        raise HTTPException(status_code=400, detail="Folder already exists")

    new_path.mkdir(parents=True, exist_ok=True)

    folder = FileNode(
        name=request.name,
        path=relative_path,
        abs_path=str(new_path.resolve()),
        parent_id=request.parent_id,
        is_directory=True,
        size=0,
        owner_id=current_user.id,
        visibility="private",
    )
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return serialize_node(folder)


@router.post("/upload")
async def upload_file(
    session: SessionDep,
    file: UploadFile = File(...),
    parent_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
):
    parent = session.get(FileNode, parent_id) if parent_id else None

    if parent:
        save_dir = Path(parent.abs_path)
        relative_path = str((Path(parent.path) / file.filename).as_posix())
    else:
        settings = get_settings()
        save_dir = Path(settings.MEDIA_DIR)
        relative_path = file.filename

    save_dir.mkdir(parents=True, exist_ok=True)

    file_path = save_dir / file.filename
    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)

    new_file = FileNode(
        name=file.filename,
        path=relative_path,
        abs_path=str(file_path.resolve()),
        parent_id=parent_id,
        is_directory=False,
        size=file_path.stat().st_size,
        file_type=Path(file.filename).suffix.lower().lstrip("."),
        mime_type=file.content_type,
        owner_id=current_user.id,
        visibility="private",
    )
    session.add(new_file)
    session.commit()
    session.refresh(new_file)
    return serialize_node(new_file)


@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    node = _get_node_or_404(session, file_id, current_user)
    if node.is_directory:
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    if not os.path.exists(node.abs_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=node.abs_path,
        filename=node.name,
        media_type="application/octet-stream",
    )


@router.get("/play/{file_id}")
async def play_media(
    file_id: int,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    node = _get_node_or_404(session, file_id, current_user)
    if node.is_directory:
        raise HTTPException(status_code=400, detail="Cannot play a directory")
    if not os.path.exists(node.abs_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_type = (
        node.mime_type
        or mimetypes.guess_type(node.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(
        path=node.abs_path,
        filename=node.name,
        media_type=media_type,
        headers={"Accept-Ranges": "bytes"},
    )


@router.put("/rename")
async def rename_file(
    request: RenameRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    node = _get_node_or_404(session, request.id, current_user)
    try:
        renamed = rename_node(session, node, request.new_name)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return serialize_node(renamed)


@router.delete("/delete")
async def delete_file(
    request: DeleteRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    node = _get_node_or_404(session, request.id, current_user)
    try:
        delete_node(session, node, permanent=request.permanent)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"msg": "delete successful"}


@router.get("/search")
async def search_files(
    session: SessionDep,
    q: str = Query(..., min_length=1),
    only_directory: bool = Query(False),
    only_file: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    nodes = search_nodes(
        session=session,
        keyword=q,
        only_directory=only_directory,
        only_file=only_file,
        limit=limit,
        user_id=current_user.id,
    )
    return {
        "keyword": q,
        "count": len(nodes),
        "results": [serialize_node(n) for n in nodes],
    }


@router.post("/move")
async def move_file(
    request: MoveRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    if request.id == request.destination_id:
        raise HTTPException(status_code=400, detail="Cannot move to itself")

    node = _get_node_or_404(session, request.id, current_user)
    dest = _get_node_or_404(session, request.destination_id, current_user)
    if not dest.is_directory:
        raise HTTPException(status_code=400, detail="Destination must be a directory")

    try:
        moved = move_node(session, node, dest)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "msg": "move successful",
        "node": serialize_node(moved),
        "destination": serialize_node(dest),
    }


@router.post("/copy")
async def copy_file(
    request: CopyRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    if request.id == request.destination_id:
        raise HTTPException(status_code=400, detail="Cannot copy to itself")

    node = _get_node_or_404(session, request.id, current_user)
    dest = _get_node_or_404(session, request.destination_id, current_user)
    if not dest.is_directory:
        raise HTTPException(status_code=400, detail="Destination must be a directory")

    try:
        copied = copy_node(session, node, dest, request.new_name)
        session.commit()
        session.refresh(copied)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "msg": "copy successful",
        "node": serialize_node(copied),
        "destination": serialize_node(dest),
    }
