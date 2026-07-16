"""
User management routes — admin CRUD + self-service profile.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import SessionDep, get_current_user, get_current_admin
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserUpdateMe,
    UserUpdatePassword,
    UserUpdate,
    FileSystemConfigUpdate,
)

router = APIRouter(prefix="/user", tags=["user"])


# ═══════════════════════════════════════════════════════════════════
#  Self-service
# ═══════════════════════════════════════════════════════════════════

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user": current_user.to_dict()}


@router.patch("/me")
def update_me(
    user_in: UserUpdateMe,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    if user_in.username is not None:
        current_user.username = user_in.username
    if user_in.email is not None:
        current_user.email = user_in.email
    session.commit()
    session.refresh(current_user)
    return {"user": current_user.to_dict()}


@router.patch("/me/password")
def update_my_password(
    user_in: UserUpdatePassword,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    if not current_user.check_password(user_in.old_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    current_user.password_hash_old = current_user.password_hash
    current_user.set_password(user_in.new_password)
    session.commit()
    return {"msg": "Password updated successfully"}


@router.patch("/me/file-system-config")
def update_file_system_config(
    body: FileSystemConfigUpdate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Update your file system framework description (used by the AI agent)."""
    current_user.file_system_config = body.file_system_config
    session.commit()
    session.refresh(current_user)
    return {
        "msg": "File system config updated",
        "file_system_config": current_user.file_system_config,
    }


@router.delete("/me")
def delete_me(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    session.delete(current_user)
    session.commit()
    return {"msg": "User deleted successfully"}


# ═══════════════════════════════════════════════════════════════════
#  Admin
# ═══════════════════════════════════════════════════════════════════

@router.get("/users")
def list_users(
    session: SessionDep,
    offset: int = 0,
    limit: int = 10,
    current_admin: User = Depends(get_current_admin),
):
    users = session.query(User).offset(offset).limit(limit).all()
    return {"users": [u.to_dict() for u in users]}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    session: SessionDep,
    current_admin: User = Depends(get_current_admin),
):
    # Check unique constraints
    existing = session.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    existing = session.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    new_user = User(
        username=user_in.username,
        email=user_in.email,
        role=user_in.role,
        is_active=user_in.is_active,
    )
    new_user.set_password(user_in.password)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return {"user": new_user.to_dict()}


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    user_in: UserUpdate,
    session: SessionDep,
    current_admin: User = Depends(get_current_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_in.username is not None:
        user.username = user_in.username
    if user_in.email is not None:
        user.email = user_in.email
    if user_in.role is not None:
        user.role = user_in.role
    if user_in.is_active is not None:
        user.is_active = user_in.is_active

    session.commit()
    session.refresh(user)
    return {"user": user.to_dict()}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    session: SessionDep,
    current_admin: User = Depends(get_current_admin),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session.delete(user)
    session.commit()
    return {"msg": "User deleted successfully"}
