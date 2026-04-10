from fastapi import FastAPI
from fastapi_jwt_auth import AuthJWT
from fastapi_jwt_auth.exceptions import AuthJWTException
from fastapi.responses import JSONResponse
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from app.config import config
import os
from app.db import Base, engine

from app.models.user import User
from app.models.media import FileNode, Media

# FastAPI app
app = FastAPI()

Base.metadata.create_all(bind=engine)

# JWT 配置
@AuthJWT.load_config
def get_config():
    return [
        ("authjwt_secret_key", "jwt-secret-key-change-this-need-32-bytes"),
        ("authjwt_access_token_expires", 24 * 60 * 60),  # 24 hours
        ("authjwt_refresh_token_expires", 30 * 24 * 60 * 60),  # 30 days
    ]

# JWT 异常处理
@app.exception_handler(AuthJWTException)
def authjwt_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message}
    )

# 包含路由
from app.routes import auth, media, scan
app.include_router(auth.router)
app.include_router(media.router)
app.include_router(scan.router)

from app.agents import router
app.include_router(router.agent_router)