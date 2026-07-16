"""
Shared pytest fixtures for all tests.

Provides:
- ``client``              — FastAPI TestClient with in-memory SQLite
- ``auth_headers``        — Bearer token for a regular user (alice)
- ``admin_headers``       — Bearer token for an admin user (admin)
- ``db_session``          — raw SQLAlchemy session for test setup
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app
from app.db import Base, get_db
from app.models.user import User


# ═══════════════════════════════════════════════════════════════════
#  Engine & session factory (module-scoped)
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def engine():
    """In-memory SQLite engine shared across all tests."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def db_session(engine):
    """Per-test DB session — tables created once, data rolled back per test."""
    connection = engine.connect()
    transaction = connection.begin()
    TestingSession = sessionmaker(bind=connection)

    session = TestingSession()

    # Override the FastAPI dependency
    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    yield session

    # Teardown
    transaction.rollback()
    connection.close()
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════
#  Test client
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def client(db_session) -> TestClient:
    """TestClient wired to the overridden DB session."""
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════
#  Pre-built users + auth headers
# ═══════════════════════════════════════════════════════════════════

def _create_user(db_session, username: str, email: str, password: str, role: str = "user") -> User:
    user = User(username=username, email=email, role=role, is_active=True)
    user.set_password(password)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client, username: str, password: str) -> str:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def regular_user(db_session) -> User:
    return _create_user(db_session, "alice", "alice@test.com", "alicepass")


@pytest.fixture
def admin_user(db_session) -> User:
    return _create_user(db_session, "admin", "admin@test.com", "adminpass", role="admin")


@pytest.fixture
def auth_headers(client, db_session, regular_user) -> dict:
    token = _login(client, "alice", "alicepass")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client, db_session, admin_user) -> dict:
    token = _login(client, "admin", "adminpass")
    return {"Authorization": f"Bearer {token}"}
