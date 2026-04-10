from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.user import User, TokenBlacklist
from app.db import get_db
from datetime import timedelta
import re

router = APIRouter(prefix="/auth", tags=["auth"])

# Pydantic模型
class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    username: str  # 或email
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class TokenResponse(BaseModel):
    msg: str
    access_token: str
    refresh_token: str
    user: dict

# 验证函数（保持不变）
def validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_username(username: str) -> bool:
    pattern = r'^[a-zA-Z0-9_]{3,20}$'
    return re.match(pattern, username) is not None


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: Session = Depends(get_db)):
    if not validate_username(request.username):
        raise HTTPException(status_code=400, detail="Invalid username format")
    if not validate_email(request.email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    # 检查用户名是否存在
    stmt = select(User).where(User.username == request.username)
    if session.execute(stmt).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # 检查邮箱是否存在
    stmt = select(User).where(User.email == request.email)
    if session.execute(stmt).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already exists")
    
    user = User(username=request.username, email=request.email)
    user.set_password(request.password)
    session.add(user)
    session.commit()
    session.refresh(user)  # 刷新获取生成的 ID
    
    return {"msg": "User created successfully", "user": user.to_dict()}


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, authorize: AuthJWT = Depends(), session: Session = Depends(get_db)):
    # 查询用户（用户名或邮箱）
    stmt = select(User).where(
        (User.username == request.username) | (User.email == request.username)
    )
    user = session.execute(stmt).scalar_one_or_none()
    
    if not user or not user.check_password(request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")
    
    access_token = authorize.create_access_token(subject=str(user.id), expires_time=timedelta(hours=24))
    refresh_token = authorize.create_refresh_token(subject=str(user.id), expires_time=timedelta(days=30))
    
    return {
        "msg": "login successful", 
        "access_token": access_token, 
        "refresh_token": refresh_token, 
        "user": user.to_dict()
    }


@router.post("/refresh")
async def refresh(authorize: AuthJWT = Depends(), session: Session = Depends(get_db)):
    authorize.jwt_refresh_token_required()
    current_user_id = authorize.get_jwt_subject()
    
    # 使用 session.get 获取用户
    user = session.get(User, int(current_user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Invalid user")
    
    new_access_token = authorize.create_access_token(subject=current_user_id, expires_time=timedelta(hours=24))
    return {"access_token": new_access_token}


@router.get("/me")
async def get_current_user(authorize: AuthJWT = Depends(), session: Session = Depends(get_db)):
    authorize.jwt_required()
    current_user_id = authorize.get_jwt_subject()
    
    # 使用 session.get 获取用户
    user = session.get(User, int(current_user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Invalid user")
    
    return {"user": user.to_dict()}


@router.post("/logout")
async def logout(authorize: AuthJWT = Depends(), session: Session = Depends(get_db)):
    authorize.jwt_required()
    jti = authorize.get_raw_jwt()["jti"]
    
    # 将 token 加入黑名单
    blacklisted_token = TokenBlacklist(jti=jti)
    session.add(blacklisted_token)
    session.commit()
    
    return {"msg": "Logged out"}


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest, 
    authorize: AuthJWT = Depends(), 
    session: Session = Depends(get_db)
):
    authorize.jwt_required()
    current_user_id = authorize.get_jwt_subject()
    
    # 使用 session.get 获取用户
    user = session.get(User, int(current_user_id))
    if not user or not user.check_password(request.old_password):
        raise HTTPException(status_code=401, detail="Invalid old password")
    
    if request.old_password == request.new_password:
        raise HTTPException(status_code=400, detail="New password same as old")
    
    user.set_password(request.new_password)
    session.commit()
    
    return {"msg": "Password changed"}