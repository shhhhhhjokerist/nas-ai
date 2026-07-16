from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class FileNodeResponse(BaseModel):
    id: int
    name: str
    path: str
    abs_path: str
    parent_id: Optional[int] = None
    is_directory: bool
    size: int
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    media_type: Optional[str] = None
    owner_id: Optional[int] = None
    visibility: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: bool = False

    model_config = {"from_attributes": True}


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


class MoveRequest(BaseModel):
    id: int
    destination_id: int


class CopyRequest(BaseModel):
    id: int
    destination_id: int
    new_name: Optional[str] = None
