import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def disable_external_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", None)
