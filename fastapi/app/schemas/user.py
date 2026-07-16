from typing import Optional
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "user"
    is_active: bool = True


class UserUpdateMe(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None


class UserUpdatePassword(BaseModel):
    old_password: str
    new_password: str


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class FileSystemConfigUpdate(BaseModel):
    """Update the user's file system framework description."""
    file_system_config: str
