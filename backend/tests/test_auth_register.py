import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db import SessionLocal
from app.mail import AuthMail, MailDeliveryError, action_email_html, send_auth_mail, verification_email_html
from app.models import AuthActionToken, EmailOutbox, User
from conftest import ADMIN_INITIAL_PASSWORD, action_token, register_and_login, verification_code


def test_register_requires_email_verification_before_login():
    username = f"test{int(time.time() * 1000)}"
    password = "test123456"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": password},
        )
        assert response.status_code == 202
        assert response.json()["masked_email"].endswith("@example.com")
        assert response.json()["retry_after_seconds"] == 0
        assert response.json()["dev_verification_code"] is None
        assert f"{username}@example.com" not in response.json()["message"]
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/login", json={"account": username, "password": password}).status_code == 403
        sent = client.post("/api/v1/auth/send-verification-code", json={"email": f"{username}@example.com"})
        assert sent.status_code == 202
        assert sent.json()["expires_in_seconds"] == 180
        assert sent.json()["retry_after_seconds"] == 60
        with SessionLocal() as db:
            delivery = db.scalar(select(EmailOutbox).where(EmailOutbox.purpose == "verify_email").order_by(EmailOutbox.id.desc()))
            assert delivery is not None
            assert delivery.status == "simulated"
            assert delivery.attempt_count == delivery.retry_count == 0
            assert delivery.recipient_masked != f"{username}@example.com"
            assert not hasattr(delivery, "body")
        code = verification_code(sent)
        assert client.post("/api/v1/auth/verify-email", json={"email": f"{username}@example.com", "code": code}).status_code == 200
        assert client.post("/api/v1/auth/verify-email", json={"email": f"{username}@example.com", "code": code}).status_code == 400
        login = client.post("/api/v1/auth/login", json={"account": username, "password": password})
        assert login.status_code == 200
        assert login.json()["username"] == username
        assert login.json()["email_verified"] is True
        assert len(login.json()["public_id"]) == 4
        assert login.json()["public_id"].isdigit()


def test_auth_email_html_uses_code_panel_and_safe_action_button():
    verification_html = verification_email_html("123456", 3)
    assert "123456" in verification_html
    assert "letter-spacing:8px" in verification_html
    assert "#ff385c" in verification_html

    action_html = action_email_html("确认新邮箱", "确认新邮箱", "https://example.com/confirm?token=a&source=email", 30)
    assert "确认新邮箱" in action_html
    assert "https://example.com/confirm?token=a&amp;source=email" in action_html
    assert "background:#ff385c" in action_html
    assert "border-radius:8px" in action_html


def test_auth_mail_sends_plaintext_and_html_alternatives(monkeypatch):
    sent_messages = []

    class FakeSmtp:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            pass

        def login(self, *_args):
            pass

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr("app.mail.settings.mail_delivery_mode", "smtp")
    monkeypatch.setattr("app.mail.settings.smtp_host", "smtp.example.com")
    monkeypatch.setattr("app.mail.smtplib.SMTP", FakeSmtp)
    send_auth_mail(AuthMail(
        recipient="traveler@example.com",
        subject="验证你的邮箱",
        body="验证码：123456",
        html_body=verification_email_html("123456", 3),
    ))

    assert len(sent_messages) == 1
    assert {part.get_content_type() for part in sent_messages[0].walk()} >= {"text/plain", "text/html"}
    assert "123456" in sent_messages[0].get_body(preferencelist=("html",)).get_content()


def test_pending_registration_email_can_be_corrected_with_password():
    suffix = uuid.uuid4().hex
    username = f"test{suffix}"
    old_email = f"wrong-{suffix}@example.com"
    new_email = f"correct-{suffix}@example.com"
    password = "test123456"
    with TestClient(app) as client:
        first = client.post("/api/v1/auth/register", json={"username": username, "email": old_email, "password": password})
        old_sent = client.post("/api/v1/auth/send-verification-code", json={"email": old_email})
        old_code = verification_code(old_sent)
        corrected = client.post("/api/v1/auth/register", json={"username": username, "email": new_email, "password": password})
        assert corrected.status_code == 202
        assert corrected.json()["message"].startswith("邮箱已更正")
        assert new_email not in corrected.json()["message"]
        assert client.post("/api/v1/auth/verify-email", json={"email": old_email, "code": old_code}).status_code == 400
        new_sent = client.post("/api/v1/auth/send-verification-code", json={"email": new_email})
        assert client.post("/api/v1/auth/verify-email", json={"email": new_email, "code": verification_code(new_sent)}).status_code == 200
        assert client.post("/api/v1/auth/login", json={"account": new_email, "password": password}).status_code == 200
        with SessionLocal() as db:
            assert db.scalar(select(User.email).where(User.username == username)) == new_email


def test_verification_code_cannot_be_resent_during_cooldown():
    suffix = uuid.uuid4().hex
    payload = {"username": f"test{suffix}", "email": f"test{suffix}@example.com", "password": "test123456"}
    with TestClient(app) as client:
        registered = client.post("/api/v1/auth/register", json=payload)
        assert registered.status_code == 202
        first = client.post("/api/v1/auth/send-verification-code", json={"email": payload["email"]})
        assert first.status_code == 202
        with SessionLocal() as db:
            first_token_id = db.scalar(select(AuthActionToken.id).order_by(AuthActionToken.id.desc()))
        repeated = client.post("/api/v1/auth/send-verification-code", json={"email": payload["email"]})
        assert repeated.status_code == 202
        assert 1 <= repeated.json()["retry_after_seconds"] <= 60
        assert repeated.json()["dev_verification_code"] is None
        with SessionLocal() as db:
            assert db.scalar(select(AuthActionToken.id).order_by(AuthActionToken.id.desc())) == first_token_id


def test_pending_username_cannot_be_changed_with_wrong_password():
    suffix = uuid.uuid4().hex
    username = f"test{suffix}"
    with TestClient(app) as client:
        client.post("/api/v1/auth/register", json={"username": username, "email": f"old-{suffix}@example.com", "password": "test123456"})
        rejected = client.post("/api/v1/auth/register", json={"username": username, "email": f"new-{suffix}@example.com", "password": "wrong123456"})
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "用户名已被使用，请更换用户名"


def test_verification_code_reports_mail_delivery_failure(monkeypatch):
    suffix = uuid.uuid4().hex

    def fail_delivery(_message):
        raise MailDeliveryError("test_failure")

    monkeypatch.setattr("app.main.send_auth_mail", fail_delivery)
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"username": f"test{suffix}", "email": f"test{suffix}@example.com", "password": "test123456"},
        )
        assert registered.status_code == 202
        response = client.post("/api/v1/auth/send-verification-code", json={"email": f"test{suffix}@example.com"})
        assert response.status_code == 503
        assert response.json()["detail"] == "验证码暂时发送失败，请稍后重试"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == f"test{suffix}"))
            assert user is not None
            assert db.scalar(select(AuthActionToken).where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == "verify_email",
                AuthActionToken.used_at.is_(None),
            )) is None
            delivery = db.scalar(select(EmailOutbox).where(EmailOutbox.user_id == user.id).order_by(EmailOutbox.id.desc()))
            assert delivery is not None
            assert delivery.status == "failed"
            assert delivery.last_error_code == "test_failure"


def test_email_outbox_is_redacted_and_admin_only():
    suffix = uuid.uuid4().hex
    email = f"outbox-{suffix}@example.com"
    with TestClient(app) as client:
        registered = client.post("/api/v1/auth/register", json={"username": f"outbox{suffix}", "email": email, "password": "test123456"})
        assert registered.status_code == 202
        assert client.post("/api/v1/auth/send-verification-code", json={"email": email}).status_code == 202
        assert client.get("/api/v1/admin/email-outbox").status_code == 401

        admin_login = client.post("/api/v1/auth/login", json={"account": "admin", "password": ADMIN_INITIAL_PASSWORD})
        assert admin_login.status_code == 200
        listed = client.get("/api/v1/admin/email-outbox?status=simulated")
        assert listed.status_code == 200
        item = next(record for record in listed.json()["items"] if record["purpose"] == "verify_email")
        assert item["recipient_masked"] != email
        assert "recipient_fingerprint" not in item
        assert "123456" not in str(item)


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
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        assert login.status_code == 200
        old_access_token = client.cookies.get("access_token")
        csrf = client.cookies.get("csrf_token")

        logout = client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204

        client.cookies.set("access_token", old_access_token)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_invalidates_access_token_without_refresh_cookie():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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


def test_expired_email_verification_code_is_rejected():
    suffix = uuid.uuid4().hex
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"username": f"test{suffix}", "email": f"test{suffix}@example.com", "password": "test123456"},
        )
        email = f"test{suffix}@example.com"
        sent = client.post("/api/v1/auth/send-verification-code", json={"email": email})
        code = verification_code(sent)
        with SessionLocal() as db:
            record = db.query(AuthActionToken).filter(AuthActionToken.token_hash.is_not(None)).order_by(AuthActionToken.id.desc()).first()
            record.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            db.commit()
        assert client.post("/api/v1/auth/verify-email", json={"email": email, "code": code}).status_code == 400


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
