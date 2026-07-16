"""
Shared FastAPI dependencies: DB session, current user, current admin.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.jwt_helper import AuthJWT
from app.models.user import User

# ── Shortcut for DB session ──
SessionDep = Annotated[Session, Depends(get_db)]


def get_current_user(
    session: SessionDep,
    authorize: AuthJWT = Depends(),
) -> User:
    """Require a valid access token and return the current User."""
    authorize.jwt_required()
    user_id = authorize.get_jwt_subject()

    user = session.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or inactive user")
    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require admin role on top of a valid token."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user
