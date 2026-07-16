import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.jwt_helper import AuthJWT
from app.models.user import User, TokenBlacklist
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    ChangePasswordRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _validate_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def _validate_username(username: str) -> bool:
    pattern = r"^[a-zA-Z0-9_]{3,20}$"
    return bool(re.match(pattern, username))


# ═══════════════════════════════════════════════════════════════════
#  Auth endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: Session = Depends(get_db)):
    if not _validate_username(request.username):
        raise HTTPException(status_code=400, detail="Invalid username format")
    if not _validate_email(request.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    stmt = select(User).where(User.username == request.username)
    if session.execute(stmt).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    stmt = select(User).where(User.email == request.email)
    if session.execute(stmt).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already exists")

    user = User(username=request.username, email=request.email)
    user.set_password(request.password)
    session.add(user)
    session.commit()
    session.refresh(user)

    return {"msg": "User created successfully", "user": user.to_dict()}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    authorize: AuthJWT = Depends(),
    session: Session = Depends(get_db),
):
    stmt = select(User).where(
        (User.username == request.username) | (User.email == request.username)
    )
    user = session.execute(stmt).scalar_one_or_none()

    if not user or not user.check_password(request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    access_token = authorize.create_access_token(
        subject=str(user.id), expires_time=timedelta(hours=24)
    )
    refresh_token = authorize.create_refresh_token(
        subject=str(user.id), expires_time=timedelta(days=30)
    )

    return TokenResponse(
        msg="login successful",
        access_token=access_token,
        refresh_token=refresh_token,
        user=user.to_dict(),
    )


@router.post("/refresh")
async def refresh(
    authorize: AuthJWT = Depends(),
    session: Session = Depends(get_db),
):
    authorize.jwt_refresh_token_required()
    user_id = authorize.get_jwt_subject()

    user = session.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Invalid user")

    new_access_token = authorize.create_access_token(
        subject=user_id, expires_time=timedelta(hours=24)
    )
    return {"access_token": new_access_token}


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return {"user": current_user.to_dict()}


@router.post("/logout")
async def logout(
    authorize: AuthJWT = Depends(),
    session: Session = Depends(get_db),
):
    authorize.jwt_required()
    jti = authorize.get_raw_jwt()["jti"]
    blacklisted = TokenBlacklist(jti=jti)
    session.add(blacklisted)
    session.commit()
    return {"msg": "Logged out"}


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not current_user.check_password(request.old_password):
        raise HTTPException(status_code=401, detail="Invalid old password")
    if request.old_password == request.new_password:
        raise HTTPException(status_code=400, detail="New password same as old")

    current_user.set_password(request.new_password)
    session.commit()
    return {"msg": "Password changed"}
