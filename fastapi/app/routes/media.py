import datetime
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.media import FileNode, Media
from app.services.scanner import FileScanner
from app.config import Config
from app.db import get_db

router = APIRouter(prefix="/media", tags=["media"])

# Pydantic models
class FileNodeResponse(BaseModel):
    id: int
    name: str
    path: str
    abs_path: str
    parent_id: Optional[int]
    is_directory: bool
    size: int
    file_type: Optional[str]
    mime_type: Optional[str]
    created_at: datetime.datetime
    is_deleted: bool

    class Config:
        from_attributes = True

class MediaResponse(BaseModel):
    id: int
    title: str
    file_path: str

class ScanRequest(BaseModel):
    media_root: Optional[str] = None

class CreateFolderRequest(BaseModel):
    parent_id: Optional[int] = None
    name: str

class RenameRequest(BaseModel):
    id: int
    new_name: str

class DeleteRequest(BaseModel):
    id: int
    permanent: bool = True

@router.get("/", response_model=List[MediaResponse])
async def list_media(session: Session = Depends(get_db)):
    data = session.query(Media).all()
    return data

@router.post("/scan")
async def scan_files(request: ScanRequest, session: Session = Depends(get_db)):
    try:
        media_root = request.media_root or Config.MEDIA_DIR
        scanner = FileScanner(media_root, session)
        result = scanner.scan_and_sync()
        return {"msg": "scan_complete", "scanned": result['scanned'], "deleted": result['deleted']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"scan_failed: {str(e)}")

@router.get("/browse")
async def browse_files(
    path: Optional[str] = Query(None),
    parent_id: Optional[int] = Query(None),
    session: Session = Depends(get_db)
):
    try:
        if parent_id:
            parent_node = session.query(FileNode).get(parent_id)
            if not parent_node or not parent_node.is_directory:
                raise HTTPException(status_code=400, detail="invalid parent_id")
            nodes = session.query(FileNode).filter_by(parent_id=parent_id, is_deleted=False).all()
            current_path = parent_node.path
        else:
            nodes = session.query(FileNode).filter_by(parent_id=None, is_deleted=False).all()
            current_path = '/'

        folders = [node for node in nodes if node.is_directory]
        files = [node for node in nodes if not node.is_directory]
        return {
            "current_path": current_path,
            "folders": folders,
            "files": files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"browse_failed: {str(e)}")

@router.get("/info", response_model=FileNodeResponse)
async def get_file_info(
    id: Optional[int] = Query(None),
    path: Optional[str] = Query(None),
    session: Session = Depends(get_db)
):
    try:
        if id:
            node = session.query(FileNode).get(id)
        elif path:
            node = session.query(FileNode).filter_by(path=path, is_deleted=False).first()
            if not node:
                raise HTTPException(status_code=404, detail="file not found")
        else:
            raise HTTPException(status_code=400, detail="missing id or path parameter")
        return node
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_file_info_failed: {str(e)}")

@router.post("/create-folder", response_model=FileNodeResponse)
async def create_folder(request: CreateFolderRequest, session: Session = Depends(get_db)):
    if not request.name:
        raise HTTPException(status_code=400, detail="missing folder name")

    try:
        parent = session.query(FileNode).get(request.parent_id) if request.parent_id else None

        if parent:
            parent_path = Path(parent.abs_path)
            new_path = parent_path / request.name
            relative_path = str(new_path.relative_to(Config.MEDIA_DIR))
        else:
            new_path = Config.MEDIA_DIR / request.name
            relative_path = request.name

        os.makedirs(new_path, exist_ok=True)

        new_folder = FileNode(
            name=request.name,
            path=relative_path,
            abs_path=str(new_path.resolve()),
            parent_id=request.parent_id,
            is_directory=True,
            size=0,
            created_at=datetime.datetime.now(datetime.timezone.utc)
        )

        session.add(new_folder)
        session.commit()
        session.refresh(new_folder)
        return new_folder

    except FileExistsError:
        raise HTTPException(status_code=400, detail="folder already exists")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"create_folder_failed: {str(e)}")

@router.post("/upload", response_model=FileNodeResponse)
async def upload_file(
    file: UploadFile = File(...),
    parent_id: Optional[int] = Form(None),
    session: Session = Depends(get_db)
):
    try:
        parent = session.query(FileNode).get(parent_id) if parent_id else None

        if parent:
            save_dir = Path(parent.abs_path)
            relative_path = Path(parent.path) / file.filename
        else:
            save_dir = Path(Config.MEDIA_DIR)
            relative_path = file.filename

        save_dir.mkdir(parents=True, exist_ok=True)

        file_path = save_dir / file.filename
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        new_file = FileNode(
            name=file.filename,
            path=str(relative_path),
            abs_path=str(file_path.resolve()),
            parent_id=parent_id,
            is_directory=False,
            size=file_path.stat().st_size,
            file_type=Path(file.filename).suffix.lower().lstrip('.'),
            mime_type=file.content_type,
            created_at=datetime.datetime.now(datetime.timezone.utc)
        )

        session.add(new_file)
        session.commit()
        session.refresh(new_file)
        return new_file
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"upload_failed: {str(e)}")

@router.get("/download/{file_id}")
async def download_file(file_id: int, session: Session = Depends(get_db)):
    try:
        file_node = session.query(FileNode).get(file_id)
        if not file_node or file_node.is_directory:
            raise HTTPException(status_code=404, detail="file not found")

        if not os.path.exists(file_node.abs_path):
            raise HTTPException(status_code=404, detail="file not found on disk")

        return FileResponse(
            path=file_node.abs_path,
            filename=file_node.name,
            media_type='application/octet-stream'
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"download_failed: {str(e)}")

@router.put("/rename", response_model=FileNodeResponse)
async def rename_file(request: RenameRequest, session: Session = Depends(get_db)):
    if not request.id or not request.new_name:
        raise HTTPException(status_code=400, detail="missing id or new_name parameter")

    try:
        node = session.query(FileNode).get(request.id)
        old_path = Path(node.abs_path)
        new_path = old_path.parent / request.new_name

        if new_path.exists():
            raise HTTPException(status_code=400, detail="a file with the new name already exists")

        os.rename(old_path, new_path)

        node.name = request.new_name
        node.path = str(Path(node.path).parent / request.new_name)
        node.abs_path = str(new_path.resolve())

        if node.is_directory:
            old_prefix = node.path
            new_prefix = str(Path(node.path).parent / request.new_name)

            child_nodes = session.query(FileNode).filter(FileNode.path.startswith(old_prefix)).all()

            for child in child_nodes:
                child.path = child.path.replace(old_prefix, new_prefix, 1)
                child.abs_path = str(Path(child.abs_path).parent / request.new_name / Path(child.abs_path).relative_to(old_path.parent))

        session.commit()
        session.refresh(node)
        return node
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"rename_failed: {str(e)}")

@router.delete("/delete")
async def delete_file(request: DeleteRequest, session: Session = Depends(get_db)):
    if not request.id:
        raise HTTPException(status_code=400, detail="missing id parameter")

    try:
        node = session.query(FileNode).get(request.id)

        if request.permanent:
            if os.path.exists(node.abs_path):
                if node.is_directory:
                    os.rmdir(node.abs_path)
                else:
                    os.remove(node.abs_path)

            session.delete(node)
        else:
            node.is_deleted = True

        session.commit()
        return {"msg": "delete successful"}

    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"delete_failed: {str(e)}")

@router.get("/search")
async def search_files():
    # 未实现
    pass

@router.post("/move")
async def move_file():
    # 未实现
    pass


