import time
import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_register_creates_normal_user_and_logs_in():
    username = f"visitor_{int(time.time() * 1000)}"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": "123456"},
        )
        assert response.status_code == 201
        assert response.json()["username"] == username
        assert response.json()["role"] == "user"
        assert len(response.json()["public_id"]) == 4
        assert response.json()["public_id"].isdigit()
        assert client.get("/api/v1/auth/me").json()["username"] == username


def test_public_id_login_and_account_deletion_release_id(monkeypatch):
    suffix = uuid.uuid4().hex[:10]
    username = f"identity_{suffix}"
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": "test123456"},
        )
        assert registered.status_code == 201
        public_id = registered.json()["public_id"]
        internal_id = registered.json()["id"]
        csrf = client.cookies.get("csrf_token")
        old_access_token = client.cookies.get("access_token")
        old_refresh_token = client.cookies.get("refresh_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]

        client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf})
        id_login = client.post("/api/v1/auth/login", json={"account": public_id, "password": "test123456"})
        assert id_login.status_code == 200
        assert id_login.json()["id"] == internal_id

        csrf = client.cookies.get("csrf_token")
        deleted = client.request("DELETE", "/api/v1/auth/me", json={"password": "test123456"}, headers={"X-CSRF-Token": csrf})
        assert deleted.status_code == 204
        assert client.cookies.get("access_token") is None
        assert client.cookies.get("refresh_token") is None

        client.cookies.set("access_token", old_access_token)
        assert client.get("/api/v1/auth/me").status_code == 401
        client.cookies.delete("access_token")
        client.cookies.set("refresh_token", old_refresh_token)
        client.cookies.set("csrf_token", csrf)
        assert client.post("/api/v1/auth/refresh", json={}, headers={"X-CSRF-Token": csrf}).status_code == 401

        monkeypatch.setattr("app.main.secrets.randbelow", lambda _: int(public_id))
        replacement_name = f"replacement_{suffix}"
        replacement = client.post(
            "/api/v1/auth/register",
            json={"username": replacement_name, "email": f"{replacement_name}@example.com", "password": "test123456"},
        )
        assert replacement.status_code == 201
        assert replacement.json()["public_id"] == public_id
        assert replacement.json()["id"] != internal_id
        assert client.get(f"/api/v1/sessions/{session_id}/messages").status_code == 404


def test_four_digit_username_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": "1234", "email": f"numeric-{uuid.uuid4().hex[:10]}@example.com", "password": "test123456"},
        )
        assert response.status_code == 422


def test_refresh_rotates_token_and_restores_login():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        assert login.status_code == 200
        old_refresh_token = client.cookies.get("refresh_token")
        csrf = client.cookies.get("csrf_token")
        assert old_refresh_token

        client.cookies.delete("access_token")
        assert client.get("/api/v1/auth/me").status_code == 401

        refreshed = client.post("/api/v1/auth/refresh", json={}, headers={"X-CSRF-Token": csrf})
        assert refreshed.status_code == 200
        assert client.cookies.get("refresh_token") != old_refresh_token
        assert client.get("/api/v1/auth/me").json()["username"] == "admin"


def test_logout_revokes_refresh_session():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        refresh_token = client.cookies.get("refresh_token")
        csrf = client.cookies.get("csrf_token")

        logout = client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
        assert client.cookies.get("refresh_token") is None

        client.cookies.set("refresh_token", refresh_token)
        client.cookies.set("csrf_token", csrf)
        rejected = client.post("/api/v1/auth/refresh", json={}, headers={"X-CSRF-Token": csrf})
        assert rejected.status_code == 401
