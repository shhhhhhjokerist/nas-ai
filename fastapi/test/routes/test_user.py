"""User management endpoint tests — self-service + admin CRUD."""
import pytest
from fastapi.testclient import TestClient


class TestUserSelfService:
    def test_get_me(self, client: TestClient, auth_headers):
        resp = client.get("/user/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "alice"

    def test_update_me(self, client: TestClient, auth_headers, db_session):
        resp = client.patch("/user/me", json={"username": "alice_new"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "alice_new"

    def test_update_me_email(self, client: TestClient, auth_headers):
        resp = client.patch("/user/me", json={"email": "newemail@test.com"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "newemail@test.com"

    def test_update_password(self, client: TestClient, auth_headers):
        resp = client.patch("/user/me/password", json={
            "old_password": "alicepass", "new_password": "new_alice_pass",
        }, headers=auth_headers)
        assert resp.status_code == 200
        login_resp = client.post("/auth/login", json={"username": "alice", "password": "alicepass"})
        assert login_resp.status_code == 401
        login_resp = client.post("/auth/login", json={"username": "alice", "password": "new_alice_pass"})
        assert login_resp.status_code == 200

    def test_update_password_wrong_old(self, client: TestClient, auth_headers):
        resp = client.patch("/user/me/password", json={
            "old_password": "wrong", "new_password": "irrelevant",
        }, headers=auth_headers)
        assert resp.status_code == 400

    def test_file_system_config_update(self, client: TestClient, auth_headers):
        config = "Photos -> Photos/YYYY/MM. Movies -> Movies/genre/."
        resp = client.patch("/user/me/file-system-config", json={
            "file_system_config": config,
        }, headers=auth_headers)
        assert resp.status_code == 200
        resp2 = client.get("/user/me", headers=auth_headers)
        assert resp2.json()["user"]["file_system_config"] == config

    def test_delete_me(self, client: TestClient, db_session):
        client.post("/auth/register", json={
            "username": "temp_user", "email": "temp@test.com", "password": "temp",
        })
        login = client.post("/auth/login", json={"username": "temp_user", "password": "temp"})
        token = login.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        resp = client.delete("/user/me", headers=h)
        assert resp.status_code == 200
        resp2 = client.get("/user/me", headers=h)
        assert resp2.status_code == 403


class TestAdminUserCRUD:
    def test_list_users(self, client: TestClient, admin_headers):
        resp = client.get("/user/users", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()["users"]) >= 1

    def test_create_user(self, client: TestClient, admin_headers):
        resp = client.post("/user/", json={
            "username": "created_by_admin",
            "email": "cba@test.com",
            "password": "secret123",
            "role": "user",
            "is_active": True,
        }, headers=admin_headers)
        assert resp.status_code == 201
        assert resp.json()["user"]["username"] == "created_by_admin"

    def test_update_user(self, client: TestClient, admin_headers, db_session):
        from app.models.user import User
        u = User(username="to_update", email="tu@test.com")
        u.set_password("pass")
        db_session.add(u)
        db_session.commit()
        resp = client.patch(f"/user/{u.id}", json={
            "username": "updated_name", "is_active": False,
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "updated_name"
        assert resp.json()["user"]["is_active"] is False

    def test_delete_user(self, client: TestClient, admin_headers, db_session):
        from app.models.user import User
        u = User(username="to_delete", email="td@test.com")
        u.set_password("pass")
        db_session.add(u)
        db_session.commit()
        resp = client.delete(f"/user/{u.id}", headers=admin_headers)
        assert resp.status_code == 200
        resp2 = client.get("/user/users", headers=admin_headers)
        usernames = [u2["username"] for u2 in resp2.json()["users"]]
        assert "to_delete" not in usernames

    def test_create_user_duplicate(self, client: TestClient, admin_headers):
        client.post("/user/", json={
            "username": "dup_user", "email": "dup@test.com", "password": "pass",
        }, headers=admin_headers)
        resp = client.post("/user/", json={
            "username": "dup_user", "email": "dup2@test.com", "password": "pass",
        }, headers=admin_headers)
        assert resp.status_code == 400


class TestAuthorization:
    def test_non_admin_cannot_list_users(self, client: TestClient, auth_headers):
        resp = client.get("/user/users", headers=auth_headers)
        assert resp.status_code == 403

    def test_non_admin_cannot_create_user(self, client: TestClient, auth_headers):
        resp = client.post("/user/", json={
            "username": "hacker", "email": "h@test.com", "password": "pass",
        }, headers=auth_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_access(self, client: TestClient):
        resp = client.get("/user/me")
        assert resp.status_code == 401
