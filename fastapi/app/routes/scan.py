from fastapi import APIRouter, Depends
from app.services.scanner import FileScanner
from app.config import Config
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/scan", tags=["scan"])

@router.post("/")
async def scan(session: Session = Depends(get_db)):
    fileScanner = FileScanner(Config.MEDIA_DIR, session)
    result = fileScanner.scan_and_sync()
    return {
        "msg": "scan_complete",
        "scanned": result["scanned"],
        "deleted": result["deleted"],
    }

@router.get("/")
async def scan(session: Session = Depends(get_db)):
    fileScanner = FileScanner(Config.MEDIA_DIR, session)
    result = fileScanner.scan_and_sync()
    return {
        "msg": "scan_complete",
        "scanned": result["scanned"],
        "deleted": result["deleted"],
    }
