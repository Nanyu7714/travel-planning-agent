import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import AuthActionToken
from conftest import action_token, register_and_login


def test_register_requires_email_verification_before_login():
    username = f"test{int(time.time() * 1000)}"
    password = "test123456"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": password},
        )
        assert response.status_code == 202
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/login", json={"account": username, "password": password}).status_code == 403
        token = action_token(response)
        assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
        assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400
        login = client.post("/api/v1/auth/login", json={"account": username, "password": password})
        assert login.status_code == 200
        assert login.json()["username"] == username
        assert login.json()["email_verified"] is True
        assert len(login.json()["public_id"]) == 4
        assert login.json()["public_id"].isdigit()


def test_public_id_login_and_account_deletion_release_id(monkeypatch):
    suffix = str(uuid.uuid4().int)
    username = f"test{suffix}"
    with TestClient(app) as client:
        registered = register_and_login(client, username, f"{username}@example.com")
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
        replacement_name = f"test9{suffix}"
        replacement = register_and_login(client, replacement_name, f"{replacement_name}@example.com")
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


def test_logout_invalidates_access_token_immediately():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        assert login.status_code == 200
        old_access_token = client.cookies.get("access_token")
        csrf = client.cookies.get("csrf_token")

        logout = client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204

        client.cookies.set("access_token", old_access_token)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_invalidates_access_token_without_refresh_cookie():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        assert login.status_code == 200
        old_access_token = client.cookies.get("access_token")
        csrf = client.cookies.get("csrf_token")
        client.cookies.delete("refresh_token")

        logout = client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204

        client.cookies.set("access_token", old_access_token)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_change_password_invalidates_access_token_immediately():
    username = f"test{uuid.uuid4().int}"
    with TestClient(app) as client:
        registered = register_and_login(client, username, f"{username}@example.com")
        old_access_token = client.cookies.get("access_token")
        csrf = client.cookies.get("csrf_token")

        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "test123456", "new_password": "new1234567"},
            headers={"X-CSRF-Token": csrf},
        )
        assert changed.status_code == 204

        client.cookies.set("access_token", old_access_token)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_password_policy_requires_ten_characters():
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": f"test{suffix}", "email": f"test{suffix}@example.com", "password": "123456789"},
        )
        assert response.status_code == 422


def test_forgot_password_resets_password_and_revokes_sessions():
    suffix = uuid.uuid4().hex
    username = f"test{suffix}"
    email = f"{username}@example.com"
    old_password = "test123456"
    new_password = "reset123456"
    with TestClient(app) as client:
        register_and_login(client, username, email, old_password)
        old_access_token = client.cookies.get("access_token")

        requested = client.post("/api/v1/auth/forgot-password", json={"email": email})
        missing = client.post("/api/v1/auth/forgot-password", json={"email": f"missing-{suffix}@example.com"})
        assert requested.status_code == 202
        assert missing.status_code == 202
        assert requested.json()["message"] == missing.json()["message"]
        token = action_token(requested)

        reset = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_password})
        assert reset.status_code == 204
        assert client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_password}).status_code == 400
        client.cookies.set("access_token", old_access_token)
        assert client.get("/api/v1/auth/me").status_code == 401
        client.cookies.clear()
        assert client.post("/api/v1/auth/login", json={"account": username, "password": old_password}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"account": username, "password": new_password}).status_code == 200


def test_email_change_only_applies_after_confirmation():
    suffix = uuid.uuid4().hex
    username = f"test{suffix}"
    old_email = f"{username}@example.com"
    new_email = f"new-{suffix}@example.com"
    with TestClient(app) as client:
        register_and_login(client, username, old_email)
        csrf = client.cookies.get("csrf_token")
        requested = client.post(
            "/api/v1/auth/change-email",
            json={"password": "test123456", "email": new_email},
            headers={"X-CSRF-Token": csrf},
        )
        assert requested.status_code == 202
        assert client.get("/api/v1/auth/me").json()["email"] == old_email
        token = action_token(requested)
        confirmed = client.post("/api/v1/auth/change-email/confirm", json={"token": token})
        assert confirmed.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401
        client.cookies.clear()
        assert client.post("/api/v1/auth/login", json={"account": old_email, "password": "test123456"}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"account": new_email, "password": "test123456"}).status_code == 200


def test_expired_email_verification_token_is_rejected():
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"username": f"test{suffix}", "email": f"test{suffix}@example.com", "password": "test123456"},
        )
        token = action_token(registered)
        with SessionLocal() as db:
            record = db.query(AuthActionToken).filter(AuthActionToken.token_hash.is_not(None)).order_by(AuthActionToken.id.desc()).first()
            record.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            db.commit()
        assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400


def test_login_is_rate_limited_by_account():
    suffix = uuid.uuid4().hex
    username = f"test{suffix}"
    with TestClient(app) as client:
        register_and_login(client, username, f"{username}@example.com")
        client.cookies.clear()
        for _ in range(5):
            assert client.post("/api/v1/auth/login", json={"account": username, "password": "wrong-password"}).status_code == 401
        limited = client.post("/api/v1/auth/login", json={"account": username, "password": "test123456"})
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0


def test_csrf_must_match_current_auth_session_and_can_be_rotated():
    suffix = uuid.uuid4().hex
    username = f"test{suffix}"
    with TestClient(app) as client:
        register_and_login(client, username, f"{username}@example.com")
        client.cookies.delete("csrf_token")
        client.cookies.set("csrf_token", "forged-csrf-token")
        rejected = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": "forged-csrf-token"})
        assert rejected.status_code == 403

        client.cookies.delete("csrf_token")
        rotated = client.get("/api/v1/auth/csrf")
        assert rotated.status_code == 200
        csrf = rotated.json()["csrf_token"]
        assert client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).status_code == 201


def test_public_auth_rejects_untrusted_browser_origin():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "someone@example.com"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403
