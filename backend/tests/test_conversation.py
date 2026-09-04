import os
import time
import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Attraction, City
from app.services import city_followup_response, extract_plan_request, is_city_overview_request, opening_window
from conftest import register_and_login


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
        suffix = str(uuid.uuid4().int)
        register_and_login(client, f"test{suffix}", f"test{suffix}@example.com")
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


def test_city_followups_use_context_instead_of_replaying_destination_overview():
    db = SessionLocal()
    try:
        chengdu = db.query(City).filter(City.name == "成都").one()
        food_reply = city_followup_response("有没有推荐的美食", chengdu, db)
        season_reply = city_followup_response("推荐什么时间去", chengdu, db)
    finally:
        db.close()
    assert is_city_overview_request("我想去成都") is True
    assert is_city_overview_request("有没有推荐的美食") is False
    assert is_city_overview_request("我想去成都，有什么好吃的") is False
    assert food_reply and "火锅" in food_reply and "宽窄巷子" in food_reply
    assert season_reply and "春秋" in season_reply


def test_opening_hours_uses_selected_travel_date_for_weekday_closure():
    db = SessionLocal()
    try:
        forbidden_city_stop = db.query(Attraction).filter(Attraction.name == "故宫博物院").one()
        opens_at, closes_at, issue = opening_window(forbidden_city_stop, date(2026, 9, 7))
    finally:
        db.close()
    assert (opens_at, closes_at) == (0, 0)
    assert issue and "周一闭馆" in issue


def test_plan_request_extracts_origin_and_destination_from_cross_city_phrase():
    db = SessionLocal()
    try:
        requirement = extract_plan_request("我想从北京去上海玩2天", db)
    finally:
        db.close()
    assert requirement["origin"] == "北京"
    assert requirement["destination"] == "上海"


def test_agent_only_starts_planning_after_explicit_request():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
        suffix = str(uuid.uuid4().int)
        register_and_login(client, f"test{suffix}", f"test{suffix}@example.com")
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

        admin_login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        assert admin_login.status_code == 200
        admin_csrf = client.cookies.get("csrf_token")
        admin_users = client.get("/api/v1/admin/users")
        assert admin_users.status_code == 200
        assert admin_users.json()["total"] >= 2
        assert len(admin_users.json()["items"]) <= 20
        searched_users = client.get("/api/v1/admin/users?page=1&page_size=10&status=active&search=admin")
        assert searched_users.status_code == 200
        assert searched_users.json()["total"] == 1
        assert searched_users.json()["items"][0]["username"] == "admin"
        deleted_sessions = client.get("/api/v1/admin/sessions?state=deleted&page=1&page_size=10").json()["items"]
        retained = next(item for item in deleted_sessions if item["id"] == second["id"])
        assert retained["title"] == "上海摄影周末"
        assert retained["message_count"] >= 2
        assert retained["job_count"] >= 1

        restored = client.post(f"/api/v1/admin/sessions/{second['id']}/restore", json={}, headers={"X-CSRF-Token": admin_csrf})
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None

        user_login = client.post("/api/v1/auth/login", json={"account": f"test{suffix}", "password": "test123456"})
        assert user_login.status_code == 200
        assert second["id"] in {item["id"] for item in client.get("/api/v1/sessions").json()}


def test_bulk_session_management_requires_password_for_three_or_more_deletions():
    with TestClient(app) as client:
        suffix = str(uuid.uuid4().int)
        password = "test123456"
        register_and_login(client, f"bulk{suffix}", f"bulk{suffix}@example.com", password)
        headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        sessions = [client.post("/api/v1/sessions", json={}, headers=headers).json() for _ in range(3)]
        session_ids = [session["id"] for session in sessions]

        archived = client.post(
            "/api/v1/sessions/bulk",
            json={"session_ids": session_ids[:2], "action": "archive"},
            headers=headers,
        )
        assert archived.status_code == 200
        assert archived.json() == {"processed_count": 2, "action": "archive"}
        assert {item["id"] for item in client.get("/api/v1/sessions?archived=true").json()} == set(session_ids[:2])

        restored = client.post(
            "/api/v1/sessions/bulk",
            json={"session_ids": session_ids[:2], "action": "restore"},
            headers=headers,
        )
        assert restored.status_code == 200
        assert {item["id"] for item in client.get("/api/v1/sessions").json()} == set(session_ids)

        missing_password = client.post(
            "/api/v1/sessions/bulk",
            json={"session_ids": session_ids, "action": "delete"},
            headers=headers,
        )
        assert missing_password.status_code == 403
        wrong_password = client.post(
            "/api/v1/sessions/bulk",
            json={"session_ids": session_ids, "action": "delete", "password": "wrong-password"},
            headers=headers,
        )
        assert wrong_password.status_code == 403

        deleted = client.post(
            "/api/v1/sessions/bulk",
            json={"session_ids": session_ids, "action": "delete", "password": password},
            headers=headers,
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"processed_count": 3, "action": "delete"}
        assert client.get("/api/v1/sessions").json() == []
        assert client.get(f"/api/v1/sessions/{session_ids[0]}/messages").status_code == 404


def test_plan_requires_confirmation_and_idempotency():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
            "start_date": "2026-09-08",
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
        assert itinerary["validation"]["daily_load"]["status"] == "passed"
        assert itinerary["validation"]["travel"]["status"] == "partial"
        assert itinerary["budget_scope"] == "门票、景点间市内交通、餐饮和住宿估算；未覆盖跨城交通和购物"


def test_plan_uses_amap_segments_and_complete_budget(monkeypatch):
    calls: list[str] = []

    def fake_search_place(keyword: str, city: str | None = None, max_pois: int = 10):
        offset = sum(ord(char) for char in keyword) % 100
        return {"location": f"121.{offset:02d},31.{offset:02d}", "citycode": "021"}

    def fake_weather(city_code: str | None, travel_date: date | None):
        calls.append("weather")
        return {"status": "passed", "provider": "高德天气", "date": travel_date.isoformat(), "day_weather": "晴", "day_temp": "28"}

    def fake_geocode(address: str):
        calls.append(f"geocode:{address}")
        offset = sum(ord(char) for char in address) % 100
        return {"coordinate": (31 + offset / 1000, 121 + offset / 1000), "citycode": "021"}

    def fake_route(origin, destination, transport, city_code=None, destination_city_code=None, travel_date=None):
        calls.append(f"route:{transport}")
        return {
            "provider": "amap", "transport": transport, "distance_meters": 1800,
            "duration_seconds": 900, "cost_yuan": 3.0, "cost_source": "高德公交票价", "cost_basis": "per_person",
        }

    def fake_nearby_food(coordinate, city: str, limit: int = 2):
        calls.append("food")
        return [{"name": "测试餐厅", "address": "测试地址", "distance_meters": 320}]

    monkeypatch.setattr("app.services.search_amap_place", fake_search_place)
    monkeypatch.setattr("app.services.request_amap_weather", fake_weather)
    monkeypatch.setattr("app.services.request_amap_geocode", fake_geocode)
    monkeypatch.setattr("app.services.request_amap_route", fake_route)
    monkeypatch.setattr("app.services.request_amap_nearby_food", fake_nearby_food)
    with SessionLocal() as db:
        for attraction in db.query(Attraction).join(City).filter(City.name == "上海").all():
            attraction.latitude = None
            attraction.longitude = None
        db.commit()
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        drafted = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "请规划上海2天摄影美食行程"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        wait_for_job(client, drafted.json()["job_id"])
        shanghai = next(city for city in client.get("/api/v1/cities").json() if city["name"] == "上海")
        confirmed = client.post(
            f"/api/v1/sessions/{session_id}/plan-confirm",
            json={"confirmed": True, "patch": {
                "destination_city_id": shanghai["id"], "days": 2, "start_date": "2026-09-08",
                "attraction_count": 3, "budget_total": 3000, "interests": ["摄影", "美食"], "traveler_count": 2,
                "transport": "public_transport",
            }},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        job = wait_for_job(client, confirmed.json()["job_id"])
        assert job["status"] == "completed"
        itinerary = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()
        travel = itinerary["validation"]["travel"]
        budget = itinerary["validation"]["budget"]
        assert travel["status"] == "passed"
        assert travel["total_distance_meters"] == 1800
        assert travel["total_duration_seconds"] == 900
        assert budget["breakdown"]["local_transport"] == 6.0
        assert budget["breakdown"]["meals"] == 480
        assert budget["breakdown"]["hotel"] == 350
        assert budget["breakdown"]["total"] == itinerary["budget_total"]
        assert itinerary["validation"]["opening_hours"]["status"] == "passed"
        assert itinerary["validation"]["weather"]["status"] == "passed"
        assert len(itinerary["validation"]["driving_navigation"]["segments"]) == 2
        assert len(itinerary["validation"]["nearby_food"]) == 3
        assert len([stop for day in itinerary["itinerary_days"] for stop in day["stops"]]) == 3
        first_geocode = min(index for index, call in enumerate(calls) if call.startswith("geocode:"))
        first_driving_route = calls.index("route:driving")
        first_food = calls.index("food")
        assert calls.index("weather") < first_geocode < first_driving_route < first_food


def test_plan_includes_round_trip_intercity_route_and_budget(monkeypatch):
    def fake_search_place(keyword: str, city: str | None = None, max_pois: int = 10):
        return {"location": "121.470000,31.230000", "citycode": "021"}

    def fake_geocode(city_name: str):
        coordinates = {"北京": ((39.9042, 116.4074), "010"), "上海": ((31.2304, 121.4737), "021")}
        coordinate, citycode = coordinates[city_name]
        return {"coordinate": coordinate, "citycode": citycode}

    def fake_route(origin, destination, transport, city_code=None, destination_city_code=None, travel_date=None):
        is_intercity = city_code != destination_city_code
        return {
            "provider": "amap", "transport": transport,
            "distance_meters": 1200000 if is_intercity else 1800,
            "duration_seconds": 18000 if is_intercity else 900,
            "cost_yuan": 550.0 if is_intercity else 3.0,
            "cost_source": "高德公交票价", "cost_basis": "per_person",
        }

    monkeypatch.setattr("app.services.search_amap_place", fake_search_place)
    monkeypatch.setattr("app.services.request_amap_geocode", fake_geocode)
    monkeypatch.setattr("app.services.request_amap_route", fake_route)
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        drafted = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "请规划上海2天摄影美食行程"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        wait_for_job(client, drafted.json()["job_id"])
        cities = {city["name"]: city for city in client.get("/api/v1/cities").json()}
        confirmed = client.post(
            f"/api/v1/sessions/{session_id}/plan-confirm",
            json={"confirmed": True, "patch": {
                "origin_city_id": cities["北京"]["id"], "destination_city_id": cities["上海"]["id"],
                "days": 2, "start_date": "2026-09-08", "budget_total": 5000,
                "interests": ["摄影", "美食"], "traveler_count": 2, "transport": "public_transport",
            }},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        job = wait_for_job(client, confirmed.json()["job_id"])
        assert job["status"] == "completed"
        itinerary = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()
        intercity = itinerary["validation"]["intercity_travel"]
        budget = itinerary["validation"]["budget"]
        assert intercity["status"] == "passed"
        assert intercity["total_distance_meters"] == 2400000
        assert intercity["total_duration_seconds"] == 36000
        assert budget["breakdown"]["intercity_transport"] == 2200.0
        assert "intercity_round_trip" in budget["included"]
        assert itinerary["budget_scope"].startswith("往返跨城交通")


def test_stop_cancels_queued_job():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
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
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        message = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "成都4天美食慢节奏行程，安排4个景点"},
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
        assert itinerary["validation"]["daily_load"]["status"] == "passed"
        stops = [stop for day in itinerary["itinerary_days"] for stop in day["stops"]]
        assert len(stops) == len({stop["attraction_id"] for stop in stops}) == 4


def test_plan_persists_agent_tool_trace_and_repairs_ticket_budget():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": csrf}).json()["id"]
        message = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "帮我规划北京2天历史文化行程"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        wait_for_job(client, message.json()["job_id"])
        confirmed = client.post(
            f"/api/v1/sessions/{session_id}/plan-confirm",
            json={"confirmed": True, "patch": {"budget_total": 20, "traveler_count": 1}},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid.uuid4())},
        )
        job = wait_for_job(client, confirmed.json()["job_id"])
        assert job["status"] == "completed"

        trace = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}/agent-run")
        assert trace.status_code == 200
        payload = trace.json()
        assert payload["algorithm_version"] == "amap-route-v2"
        tool_names = [step["tool_name"] for step in payload["steps"]]
        assert tool_names[0] == "query_weather"
        assert {"repair_plan", "select_stops", "get_attraction_detail", "resolve_attraction_coordinates", "calculate_driving_navigation", "search_nearby_food", "calculate_amap_routes", "estimate_budget", "validate_schedule", "validate_plan", "save_itinerary_draft"}.issubset(tool_names)
        assert tool_names[-1] == "save_itinerary_draft"
        assert payload["summary"]["budget_repair_applied"] is True
        assert payload["summary"]["repair_attempts"] == 1
        assert payload["summary"]["budget_total_estimate"] >= 0

        itinerary = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()
        stop_id = itinerary["itinerary_days"][0]["stops"][0]["attraction_id"]
        replanned = client.post(
            f"/api/v1/itineraries/{job['result_itinerary_id']}/replan",
            json={"actions": [{"type": "remove_attraction", "attraction_id": stop_id}]},
            headers={"X-CSRF-Token": csrf},
        )
        assert replanned.status_code == 200
        assert stop_id not in {stop["attraction_id"] for day in replanned.json()["itinerary_days"] for stop in day["stops"]}

        before_preview = client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()
        preview = client.post(
            f"/api/v1/itineraries/{job['result_itinerary_id']}/replan/preview",
            json={"instruction": "把行程改成 3 天，预算调整为 1200 元"},
        )
        assert preview.status_code == 200
        assert preview.json()["status"] == "ready"
        assert {action["type"] for action in preview.json()["actions"]} == {"set_days", "set_budget"}
        assert client.get(f"/api/v1/itineraries/{job['result_itinerary_id']}").json()["days"] == before_preview["days"]

        confirmed_replan = client.post(
            f"/api/v1/itineraries/{job['result_itinerary_id']}/replan",
            json={"instruction": "把行程改成 3 天，预算调整为 1200 元", "actions": preview.json()["actions"]},
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed_replan.status_code == 200
        assert confirmed_replan.json()["days"] == 3
        assert confirmed_replan.json()["budget_total"] == 1200

        clarification = client.post(
            f"/api/v1/itineraries/{job['result_itinerary_id']}/replan/preview",
            json={"instruction": "安排得轻松一点"},
        )
        assert clarification.status_code == 200
        assert clarification.json()["status"] == "needs_clarification"
        assert clarification.json()["questions"]

        unconfirmed = client.post(
            f"/api/v1/itineraries/{job['result_itinerary_id']}/replan",
            json={"instruction": "改成 4 天"},
            headers={"X-CSRF-Token": csrf},
        )
        assert unconfirmed.status_code == 409


def test_model_failure_diagnostics_are_restricted_to_administrators():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        response = client.get("/api/v1/admin/agent-status")
        assert response.status_code == 200
        payload = response.json()
        assert {"mode", "state", "last_error", "last_failure_at", "runs"}.issubset(payload)
        assert {"completed", "failed", "running"}.issubset(payload["runs"])

    with TestClient(app) as client:
        suffix = str(uuid.uuid4().int)
        register_and_login(client, f"test{suffix}", f"test{suffix}@example.com")
        assert client.get("/api/v1/admin/agent-status").status_code == 403
