from fastapi import APIRouter, Depends
from app.services.scanner import FileScanner, scan_directory
from app.config import Config
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/scan", tags=["scan"])

@router.post("/")
async def scan(session: Session = Depends(get_db)):
    fileScanner = FileScanner(session)
    files = fileScanner.scan_directory(Config.MEDIA_DIR)
    return {
        "msg": "scan_complete",
        "new_files": len(files)
    }

@router.get("/")
async def scan(session: Session = Depends(get_db)):
    files = scan_directory(Config.MEDIA_DIR, session)
    return {
        "msg": "scan_complete",
        "new_files": len(files)
    }
