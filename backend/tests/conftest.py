import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic import command
from alembic.config import Config


_ORIGINAL_DATABASE_URL = os.environ.get("DATABASE_URL")
_ORIGINAL_MAIL_DELIVERY_MODE = os.environ.get("MAIL_DELIVERY_MODE")
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="travel-agent-tests-"))
_TEST_DB_PATH = _TEST_DB_DIR / "test.db"
_TEST_DATABASE_URL = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
_SENT_VERIFICATION_CODES: list[str] = []

# This must run before test modules import app.db and create the SQLAlchemy engine.
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
os.environ["MAIL_DELIVERY_MODE"] = "console"
ADMIN_INITIAL_PASSWORD = secrets.token_urlsafe(24)
os.environ["ADMIN_INITIAL_PASSWORD"] = ADMIN_INITIAL_PASSWORD


def _upgrade_test_database() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", _TEST_DATABASE_URL)
    command.upgrade(config, "head")


_upgrade_test_database()


@pytest.fixture(autouse=True)
def disable_external_llm(monkeypatch):
    from app.core.config import settings
    from app.mail import MailDeliveryResult
    import app.main

    if settings.database_url != _TEST_DATABASE_URL:
        raise RuntimeError(f"Tests must use the isolated database: {_TEST_DATABASE_URL}")
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "amap_web_service_key", None)
    _SENT_VERIFICATION_CODES.clear()

    def capture_auth_mail(message):
        if message.subject == "你的行旅邮箱验证码":
            match = re.search(r"验证码是：(\d{6})", message.body)
            assert match
            _SENT_VERIFICATION_CODES.append(match.group(1))
        return MailDeliveryResult(status="simulated", attempt_count=0)

    monkeypatch.setattr(app.main, "send_auth_mail", capture_auth_mail)
    yield

    from sqlalchemy import delete
    from app.db import SessionLocal
    from app.models import AuthRateLimitBucket

    with SessionLocal() as db:
        db.execute(delete(AuthRateLimitBucket))
        db.commit()


def action_token(response) -> str:
    action_url = response.json().get("dev_action_url")
    assert action_url
    return parse_qs(urlsplit(action_url).query)["token"][0]


def verification_code(response) -> str:
    assert "dev_verification_code" not in response.json()
    assert _SENT_VERIFICATION_CODES
    return _SENT_VERIFICATION_CODES[-1]


def register_and_login(client, username: str, email: str, password: str = "test123456"):
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert registered.status_code == 202
    sent = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert sent.status_code == 202
    verified = client.post("/api/v1/auth/verify-email", json={"email": email, "code": verification_code(sent)})
    assert verified.status_code == 200
    logged_in = client.post("/api/v1/auth/login", json={"account": username, "password": password})
    assert logged_in.status_code == 200
    return logged_in


def pytest_sessionfinish(session, exitstatus):
    """Dispose the test engine and remove only this session's temporary database."""
    db_module = __import__("sys").modules.get("app.db")
    if db_module is not None:
        db_module.engine.dispose()

    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)
    if _ORIGINAL_DATABASE_URL is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = _ORIGINAL_DATABASE_URL
    if _ORIGINAL_MAIL_DELIVERY_MODE is None:
        os.environ.pop("MAIL_DELIVERY_MODE", None)
    else:
        os.environ["MAIL_DELIVERY_MODE"] = _ORIGINAL_MAIL_DELIVERY_MODE
