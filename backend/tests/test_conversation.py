import time
import uuid

from fastapi.testclient import TestClient

from app.main import app


def send(client: TestClient, session_id: int, csrf: str, content: str, expected_assistant_count: int) -> None:
    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": content},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202
    for _ in range(30):
        messages = client.get(f"/api/v1/sessions/{session_id}/messages").json()
        if sum(message["role"] == "assistant" for message in messages) >= expected_assistant_count:
            return
        time.sleep(0.1)
    raise AssertionError("Agent 未在预期时间返回回复")


def wait_for_job(client: TestClient, job_id: int) -> dict:
    for _ in range(50):
        job = client.get(f"/api/v1/planning-jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError("规划任务未在预期时间结束")


def test_agent_remembers_name_and_answers_identity():
    with TestClient(app) as client:
        suffix = uuid.uuid4().hex[:12]
        registration = client.post(
            "/api/v1/auth/register",
            json={"username": f"profile{suffix}", "email": f"profile{suffix}@example.com", "password": "test123456"},
        )
        assert registration.status_code == 201
        csrf = client.cookies.get("csrf_token")
        session = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf})
        session_id = session.json()["id"]

        send(client, session_id, csrf, "我是大鹏", 1)
        send(client, session_id, csrf, "我喜欢拍照", 2)
        send(client, session_id, csrf, "喜欢吃辣", 3)
        send(client, session_id, csrf, "我是谁", 4)

        messages = client.get(f"/api/v1/sessions/{session_id}/messages").json()
        assistant_replies = [message["content"] for message in messages if message["role"] == "assistant"]
        last_reply = [message for message in messages if message["role"] == "assistant"][-1]
        assert "你是大鹏" in last_reply["content"]
        assert "摄影" in last_reply["content"]
        assert "辣味美食" in last_reply["content"]
        assert assistant_replies[1] != assistant_replies[2]
        assert not any("北京、上海还是成都" in reply for reply in assistant_replies)
        assert not any((message.get("payload") or {}).get("type") == "plan_confirm" for message in messages)


def test_agent_only_starts_planning_after_explicit_request():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]

        send(client, session_id, csrf, "我喜欢逛博物馆", 1)
        messages = client.get(f"/api/v1/sessions/{session_id}/messages").json()
        assert not any((message.get("payload") or {}).get("type") == "plan_confirm" for message in messages)

        send(client, session_id, csrf, "请帮我规划成都2天，想轻松一点", 2)
        messages = client.get(f"/api/v1/sessions/{session_id}/messages").json()
        confirmation = next(message for message in messages if (message.get("payload") or {}).get("type") == "plan_confirm")
        assert confirmation["payload"]["destination"] == "成都"
        assert "历史文化" in confirmation["payload"]["interests"]


def test_clear_conversation_hides_session_without_removing_messages():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        csrf = client.cookies.get("csrf_token")
        session = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf})
        session_id = session.json()["id"]
        response = client.post(f"/api/v1/sessions/{session_id}/clear", json={}, headers={"X-CSRF-Token": csrf})
        assert login.status_code == 200
        assert response.status_code == 204
        assert client.get(f"/api/v1/sessions/{session_id}/messages").status_code == 404
        assert session_id not in {item["id"] for item in client.get("/api/v1/sessions").json()}


def test_session_titles_and_management_actions():
    with TestClient(app) as client:
        suffix = uuid.uuid4().hex[:12]
        registration = client.post(
            "/api/v1/auth/register",
            json={"username": f"sessions{suffix}", "email": f"sessions{suffix}@example.com", "password": "test123456"},
        )
        assert registration.status_code == 201
        csrf = client.cookies.get("csrf_token")
        headers = {"X-CSRF-Token": csrf}
        first = client.post("/api/v1/sessions", json={}, headers=headers).json()
        second = client.post("/api/v1/sessions", json={}, headers=headers).json()

        first_message = client.post(
            f"/api/v1/sessions/{first['id']}/messages",
            json={"content": "请帮我规划成都三天美食之旅"},
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert first_message.status_code == 202
        assert first_message.json()["session_title"] == "请帮我规划成都三天美食之旅"
        wait_for_job(client, first_message.json()["job_id"])

        second_message = client.post(
            f"/api/v1/sessions/{second['id']}/messages",
            json={"content": "周末去上海拍建筑"},
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert second_message.status_code == 202
        wait_for_job(client, second_message.json()["job_id"])

        renamed = client.patch(f"/api/v1/sessions/{second['id']}", json={"title": "上海摄影周末", "is_pinned": True}, headers=headers)
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "上海摄影周末"
        assert renamed.json()["is_pinned"] is True
        active_sessions = client.get("/api/v1/sessions").json()
        assert active_sessions[0]["id"] == second["id"]

        archived = client.patch(f"/api/v1/sessions/{second['id']}", json={"archived": True}, headers=headers)
        assert archived.json()["archived_at"] is not None
        assert archived.json()["is_pinned"] is False
        assert second["id"] not in {item["id"] for item in client.get("/api/v1/sessions").json()}
        assert second["id"] in {item["id"] for item in client.get("/api/v1/sessions?archived=true").json()}

        restored = client.patch(f"/api/v1/sessions/{second['id']}", json={"archived": False}, headers=headers)
        assert restored.json()["archived_at"] is None
        deleted = client.delete(f"/api/v1/sessions/{second['id']}", headers=headers)
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/sessions/{second['id']}/messages").status_code == 404

        admin_login = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        assert admin_login.status_code == 200
        admin_csrf = client.cookies.get("csrf_token")
        admin_users = client.get("/api/v1/admin/users")
        assert admin_users.status_code == 200
        deleted_sessions = client.get("/api/v1/admin/sessions?state=deleted").json()
        retained = next(item for item in deleted_sessions if item["id"] == second["id"])
        assert retained["title"] == "上海摄影周末"
        assert retained["message_count"] >= 2
        assert retained["job_count"] >= 1

        restored = client.post(f"/api/v1/admin/sessions/{second['id']}/restore", json={}, headers={"X-CSRF-Token": admin_csrf})
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None

        user_login = client.post("/api/v1/auth/login", json={"account": f"sessions{suffix}", "password": "test123456"})
        assert user_login.status_code == 200
        assert second["id"] in {item["id"] for item in client.get("/api/v1/sessions").json()}


def test_plan_requires_confirmation_and_idempotency():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        message_key = str(uuid.uuid4())
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": message_key}

        first = client.post(f"/api/v1/sessions/{session_id}/messages", json={"content": "我想去成都玩2天，喜欢美食和慢节奏"}, headers=headers)
        repeated = client.post(f"/api/v1/sessions/{session_id}/messages", json={"content": "重复请求不应新增任务"}, headers=headers)
        assert first.status_code == 202
        assert repeated.json() == first.json()
        wait_for_job(client, first.json()["job_id"])

        messages = client.get(f"/api/v1/sessions/{session_id}/messages").json()
        confirmation = next(message for message in messages if (message.get("payload") or {}).get("type") == "plan_confirm")
        assert confirmation["payload"]["destination"] == "成都"
        assert client.get("/api/v1/itineraries").status_code == 200

        confirm_key = str(uuid.uuid4())
        confirm_headers = {"X-CSRF-Token": csrf, "Idempotency-Key": confirm_key}
        shanghai = next(city for city in client.get("/api/v1/cities").json() if city["name"] == "上海")
        requirement_patch = {
            "destination_city_id": shanghai["id"],
            "days": 3,
            "budget_total": 1800,
            "interests": ["摄影", "美食"],
            "avoid_places": ["过度拥挤"],
            "pace": "relaxed",
            "traveler_count": 2,
            "transport": "public_transport",
        }
        confirmed = client.post(f"/api/v1/sessions/{session_id}/plan-confirm", json={"confirmed": True, "patch": requirement_patch}, headers=confirm_headers)
        repeated_confirm = client.post(f"/api/v1/sessions/{session_id}/plan-confirm", json={"confirmed": True, "patch": requirement_patch}, headers=confirm_headers)
        assert confirmed.status_code == 202
        assert repeated_confirm.json() == confirmed.json()
        job = wait_for_job(client, confirmed.json()["job_id"])
        assert job["status"] == "completed"
        another_confirm = client.post(
            f"/api/v1/sessions/{session_id}/plan-confirm",
            json={"confirmed": True, "patch": {}},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert another_confirm.json()["job_id"] == job["id"]

        itinerary = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()
        assert itinerary["city_name"] == "上海"
        assert itinerary["days"] == 3
        assert itinerary["preferences"] == ["摄影", "美食"]
        assert itinerary["validation"]["daily_load"]["status"] == "partial"
        assert itinerary["validation"]["travel"]["status"] == "unknown"
        assert itinerary["budget_scope"] == "仅门票估算；交通和餐饮未计入"


def test_stop_cancels_queued_job():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        from app.core.config import settings

        previous = settings.inline_worker
        settings.inline_worker = False
        try:
            queued = client.post(
                f"/api/v1/sessions/{session_id}/messages",
                json={"content": "成都2天行程"},
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
            )
            stopped = client.post(f"/api/v1/sessions/{session_id}/stop", json={}, headers={"X-CSRF-Token": csrf})
        finally:
            settings.inline_worker = previous
        assert queued.status_code == 202
        assert stopped.json() == {"status": "cancelled", "job_id": queued.json()["job_id"]}


def test_sse_uses_standard_event_envelope():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "成都2天美食慢节奏行程"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        wait_for_job(client, response.json()["job_id"])

        stream = client.get(f"/api/v1/sessions/{session_id}/events?after=0")
        assert "retry: 3000" in stream.text
        assert "event: plan_confirm" in stream.text
        assert '"event_id":' in stream.text
        assert '"session_id":' in stream.text
        assert '"payload":' in stream.text


def test_longer_plan_uses_available_attractions_without_fabrication():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        message = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "成都4天美食慢节奏行程"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        wait_for_job(client, message.json()["job_id"])
        confirmed = client.post(
            f"/api/v1/sessions/{session_id}/plan-confirm",
            json={"confirmed": True, "patch": {}},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        job = wait_for_job(client, confirmed.json()["job_id"])
        assert job["status"] == "completed"
        itinerary = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()
        assert itinerary["days"] == 4
        assert itinerary["validation"]["daily_load"]["status"] == "partial"
        stops = [stop for day in itinerary["itinerary_days"] for stop in day["stops"]]
        assert len(stops) == len({stop["attraction_id"] for stop in stops}) == 4
