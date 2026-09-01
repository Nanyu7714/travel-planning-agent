from app.core.config import settings
from app.llm import generate_chat_reply, get_llm_status


def test_configured_llm_client_calls_compatible_chat_endpoint(monkeypatch):
    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "我记得你喜欢摄影。"}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            calls["timeout"] = kwargs["timeout"]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def post(self, url, **kwargs):
            calls.update(url=url, request=kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example/v1")
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr("app.llm.httpx.Client", FakeClient)

    reply = generate_chat_reply([{"role": "user", "content": "我喜欢拍照"}], {"preferences": ["摄影"]})

    assert reply == "我记得你喜欢摄影。"
    assert calls["url"] == "https://llm.example/v1/chat/completions"
    assert calls["request"]["model"] == "test-model"
    assert get_llm_status()["state"] == "connected"
