"""Media endpoint tests — browse, search, create-folder, delete, permissions."""
import tempfile
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings


@pytest.fixture
def media_dir():
    """Create a temporary media directory for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = get_settings()
        old_media = settings.MEDIA_DIR
        settings.MEDIA_DIR = tmp
        yield Path(tmp)
        settings.MEDIA_DIR = old_media


def _seed_files(db_session: Session, media_dir: Path, owner_id: int,
                visibility: str = "private") -> dict:
    """Create a minimal file tree in DB + disk."""
    from app.models.media import FileNode

    root = FileNode(
        name="test_root", path="test_root",
        abs_path=str(media_dir / "test_root"),
        is_directory=True, size=0,
        owner_id=owner_id, visibility=visibility,
    )
    db_session.add(root)
    db_session.flush()

    file_path = media_dir / "test_root" / "readme.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello")
    f = FileNode(
        name="readme.txt", path="test_root/readme.txt",
        abs_path=str(file_path), parent_id=root.id,
        is_directory=False, size=5, file_type="txt", mime_type="text/plain",
        owner_id=owner_id, visibility=visibility,
    )
    db_session.add(f)

    pub_dir = media_dir / "public_stuff"
    pub_dir.mkdir(exist_ok=True)
    pub = FileNode(
        name="public_stuff", path="public_stuff",
        abs_path=str(pub_dir), is_directory=True, size=0,
        owner_id=owner_id, visibility="public",
    )
    db_session.add(pub)
    db_session.flush()

    pub_file_path = pub_dir / "shared.txt"
    pub_file_path.write_text("shared")
    pub_file = FileNode(
        name="shared.txt", path="public_stuff/shared.txt",
        abs_path=str(pub_file_path), parent_id=pub.id,
        is_directory=False, size=6, file_type="txt", mime_type="text/plain",
        owner_id=owner_id, visibility="public",
    )
    db_session.add(pub_file)

    db_session.commit()
    return {"root": root, "file": f, "pub_dir": pub, "pub_file": pub_file}


class TestMediaAuth:
    def test_browse_no_auth(self, client: TestClient):
        assert client.get("/media/browse").status_code == 401

    def test_search_no_auth(self, client: TestClient):
        assert client.get("/media/search?q=test").status_code == 401

    def test_info_no_auth(self, client: TestClient):
        assert client.get("/media/info?id=1").status_code == 401

    def test_delete_no_auth(self, client: TestClient):
        resp = client.request("DELETE", "/media/delete", json={"id": 1})
        assert resp.status_code == 401


class TestBrowseAndSearch:
    def test_browse_root(self, client, auth_headers, db_session, media_dir, regular_user):
        _seed_files(db_session, media_dir, regular_user.id)
        resp = client.get("/media/browse", headers=auth_headers)
        assert resp.status_code == 200
        assert "folders" in resp.json()

    def test_search(self, client, auth_headers, db_session, media_dir, regular_user):
        _seed_files(db_session, media_dir, regular_user.id)
        resp = client.get("/media/search?q=readme", headers=auth_headers)
        assert resp.status_code == 200
        names = [r["name"] for r in resp.json()["results"]]
        assert "readme.txt" in names

    def test_search_empty(self, client, auth_headers):
        resp = client.get("/media/search?q=nonexistent_xyz", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestFileInfo:
    def test_get_info(self, client, auth_headers, db_session, media_dir, regular_user):
        nodes = _seed_files(db_session, media_dir, regular_user.id)
        resp = client.get(f"/media/info?id={nodes['file'].id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "readme.txt"

    def test_not_found(self, client, auth_headers):
        resp = client.get("/media/info?id=99999", headers=auth_headers)
        assert resp.status_code == 404


class TestCreateFolder:
    def test_create(self, client, auth_headers, media_dir):
        resp = client.post("/media/create-folder", json={"name": "new_folder"}, headers=auth_headers)
        assert resp.status_code == 200
        assert (media_dir / "new_folder").exists()

    def test_duplicate(self, client, auth_headers, media_dir):
        (media_dir / "existing").mkdir()
        resp = client.post("/media/create-folder", json={"name": "existing"}, headers=auth_headers)
        assert resp.status_code == 400


class TestDelete:
    def test_soft_delete(self, client, auth_headers, db_session, media_dir, regular_user):
        nodes = _seed_files(db_session, media_dir, regular_user.id)
        resp = client.request("DELETE", "/media/delete", json={"id": nodes["file"].id, "permanent": False}, headers=auth_headers)
        assert resp.status_code == 200

    def test_permanent_delete(self, client, auth_headers, db_session, media_dir, regular_user):
        nodes = _seed_files(db_session, media_dir, regular_user.id)
        resp = client.request("DELETE", "/media/delete", json={"id": nodes["pub_file"].id, "permanent": True}, headers=auth_headers)
        assert resp.status_code == 200
        assert not (media_dir / "public_stuff" / "shared.txt").exists()

    def test_not_found(self, client, auth_headers):
        resp = client.request("DELETE", "/media/delete", json={"id": 99999}, headers=auth_headers)
        assert resp.status_code == 404


class TestPermissionIsolation:
    def test_user_sees_public_not_others_private(self, client, db_session, media_dir, regular_user):
        from app.models.user import User
        _seed_files(db_session, media_dir, regular_user.id, visibility="private")

        bob = User(username="bob", email="bob@test.com", role="user", is_active=True)
        bob.set_password("bobpass")
        db_session.add(bob)
        db_session.commit()

        token = client.post("/auth/login", json={"username": "bob", "password": "bobpass"}).json()["access_token"]
        bob_h = {"Authorization": f"Bearer {token}"}

        resp = client.get("/media/browse", headers=bob_h)
        assert resp.status_code == 200
        all_names = [f["name"] for f in resp.json()["folders"] + resp.json()["files"]]
        assert "public_stuff" in all_names
        assert "test_root" not in all_names  # Alice's private folder
