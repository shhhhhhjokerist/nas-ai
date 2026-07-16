"""Auth endpoint tests — register, login, refresh, logout, change-password."""
import pytest
from fastapi.testclient import TestClient


class TestRegister:
    def test_register_success(self, client: TestClient, db_session):
        resp = client.post("/auth/register", json={
            "username": "newuser", "email": "new@test.com", "password": "secret123",
        })
        assert resp.status_code == 201
        assert resp.json()["msg"] == "User created successfully"

    def test_register_duplicate_username(self, client: TestClient):
        client.post("/auth/register", json={
            "username": "dup", "email": "a@test.com", "password": "secret123",
        })
        resp = client.post("/auth/register", json={
            "username": "dup", "email": "b@test.com", "password": "secret123",
        })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"].lower()

    def test_register_duplicate_email(self, client: TestClient):
        client.post("/auth/register", json={
            "username": "user_a", "email": "same@test.com", "password": "secret123",
        })
        resp = client.post("/auth/register", json={
            "username": "user_b", "email": "same@test.com", "password": "secret123",
        })
        assert resp.status_code == 400

    @pytest.mark.parametrize("username,email,password", [
        ("ab", "good@test.com", "secret123"),
        ("gooduser", "not-an-email", "secret123"),
    ])
    def test_register_validation(self, client, username, email, password):
        resp = client.post("/auth/register", json={
            "username": username, "email": email, "password": password,
        })
        # Pydantic EmailStr validation returns 422; our manual check returns 400
        assert resp.status_code in (400, 422)


class TestLogin:
    def test_login_success(self, client: TestClient, auth_headers):
        assert auth_headers  # fixture already logged in successfully

    def test_login_wrong_password(self, client: TestClient, regular_user):
        resp = client.post("/auth/login", json={
            "username": "alice", "password": "wrong",
        })
        assert resp.status_code == 401

    def test_login_inactive_user(self, client: TestClient, db_session):
        from app.models.user import User
        u = User(username="inactive", email="inactive@test.com", role="user", is_active=False)
        u.set_password("pass")
        db_session.add(u)
        db_session.commit()
        resp = client.post("/auth/login", json={"username": "inactive", "password": "pass"})
        assert resp.status_code == 403

    def test_login_with_email(self, client: TestClient, regular_user):
        resp = client.post("/auth/login", json={
            "username": "alice@test.com", "password": "alicepass",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()


class TestMe:
    def test_get_me(self, client: TestClient, auth_headers):
        resp = client.get("/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "alice"

    def test_get_me_no_auth(self, client: TestClient):
        resp = client.get("/auth/me")
        assert resp.status_code == 401


class TestRefresh:
    def test_refresh_token(self, client: TestClient, db_session):
        from app.models.user import User
        u = User(username="refresh_test", email="rt@test.com")
        u.set_password("pass")
        db_session.add(u)
        db_session.commit()

        login_resp = client.post("/auth/login", json={"username": "refresh_test", "password": "pass"})
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post("/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()


class TestLogout:
    def test_logout(self, client: TestClient, auth_headers):
        resp = client.post("/auth/logout", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["msg"] == "Logged out"


class TestChangePassword:
    def test_change_password_success(self, client: TestClient, db_session):
        from app.models.user import User
        u = User(username="cp_test", email="cp@test.com")
        u.set_password("oldpass")
        db_session.add(u)
        db_session.commit()

        login = client.post("/auth/login", json={"username": "cp_test", "password": "oldpass"})
        token = login.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        resp = client.post("/auth/change-password", json={
            "old_password": "oldpass", "new_password": "newpass",
        }, headers=h)
        assert resp.status_code == 200

        resp2 = client.post("/auth/login", json={"username": "cp_test", "password": "oldpass"})
        assert resp2.status_code == 401

        resp3 = client.post("/auth/login", json={"username": "cp_test", "password": "newpass"})
        assert resp3.status_code == 200

    def test_change_password_wrong_old(self, client: TestClient, auth_headers):
        resp = client.post("/auth/change-password", json={
            "old_password": "wrong_old", "new_password": "newpass",
        }, headers=auth_headers)
        assert resp.status_code == 401
