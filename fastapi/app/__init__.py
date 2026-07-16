"""
NAS-AI FastAPI application factory.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load .env before anything else
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

from app.jwt_helper import AuthJWT, AuthJWTException
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

    # ── CORS (allow Vue dev server) ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── JWT config ──
    @AuthJWT.load_config
    def get_config():
        return [
            ("authjwt_secret_key", settings.JWT_SECRET_KEY),
            ("authjwt_access_token_expires", settings.JWT_ACCESS_TOKEN_EXPIRES),
            ("authjwt_refresh_token_expires", settings.JWT_REFRESH_TOKEN_EXPIRES),
        ]

    # ── JWT exception handler ──
    @app.exception_handler(AuthJWTException)
    def authjwt_exception_handler(request, exc: AuthJWTException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    # ── Import models so SQLAlchemy Base.metadata knows about all tables ──
    from app.models.user import User, TokenBlacklist
    from app.models.media import FileNode, Media
    from app.models.document import DocumentRecord

    # ── Create tables on startup (dev convenience; use Alembic in production) ──
    from app.db import Base, engine
    Base.metadata.create_all(bind=engine)

    # ── Register routes ──
    from app.routes import auth, media, user
    app.include_router(auth.router)
    app.include_router(media.router)
    app.include_router(user.router)

    from app.routes import documents, rag
    app.include_router(documents.router)
    app.include_router(rag.router)

    from app.agents.router import agent_router
    app.include_router(agent_router)

    return app


# Module-level app instance (for uvicorn reload: "app:app")
app = create_app()