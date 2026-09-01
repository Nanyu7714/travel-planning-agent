import re
import uuid

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Itinerary, ItineraryDay, ItineraryStop, User, UserProfile


def test_legacy_profile_null_lists_are_normalized():
    suffix = uuid.uuid4().hex[:10]
    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={"username": f"legacy{suffix}", "email": f"legacy{suffix}@example.com", "password": "test123456"},
        )
        assert registration.status_code == 201
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == f"legacy{suffix}").one()
            db.add(UserProfile(user_id=user.id, preferences=None, avoid_places=None))
            db.commit()
        finally:
            db.close()

        profile = client.get("/api/v1/auth/profile")
        assert profile.status_code == 200
        assert profile.json()["preferences"] == []
        assert profile.json()["avoid_places"] == []


def test_user_content_profile_itinerary_share_and_feedback():
    suffix = uuid.uuid4().hex[:10]
    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={"username": f"feature{suffix}", "email": f"feature{suffix}@example.com", "password": "test123456"},
        )
        assert registration.status_code == 201
        csrf = client.cookies.get("csrf_token")
        headers = {"X-CSRF-Token": csrf}

        city = client.get("/api/v1/cities").json()[0]
        attractions = client.get(f"/api/v1/cities/{city['id']}/attractions").json()
        ranking = client.get(f"/api/v1/rankings?type=attraction&city_id={city['id']}").json()
        assert ranking and len(ranking) <= 10
        assert all(item["city_id"] == city["id"] for item in ranking)
        assert [item["score"] for item in ranking] == sorted((item["score"] for item in ranking), reverse=True)

        profile = client.patch(
            "/api/v1/auth/profile",
            json={"display_name": "大鹏", "preferences": ["摄影", "美食"], "avoid_places": ["过度拥挤"]},
            headers=headers,
        )
        assert profile.status_code == 200
        assert profile.json()["avoid_places"] == ["过度拥挤"]
        assert client.put(f"/api/v1/favorites/city/{city['id']}", json={}, headers=headers).status_code == 200
        assert client.post(f"/api/v1/recent-views?target_type=city&target_id={city['id']}", json={}, headers=headers).status_code == 204
        assert client.get("/api/v1/favorites").json()[0]["name"] == city["name"]
        assert client.get("/api/v1/recent-views").json()[0]["name"] == city["name"]

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == f"feature{suffix}").one()
            itinerary = Itinerary(user_id=user.id, title="成都周末", city_name=city["name"], days=1, budget_total=300)
            db.add(itinerary)
            db.flush()
            day = ItineraryDay(itinerary_id=itinerary.id, day_number=1, title="第1天")
            db.add(day)
            db.flush()
            db.add(ItineraryStop(day_id=day.id, attraction_id=attractions[0]["id"], name=attractions[0]["name"], start_time="09:00", end_time="11:00", note="原安排"))
            db.commit()
            itinerary_id = itinerary.id
        finally:
            db.close()

        updated = client.put(
            f"/api/v1/itineraries/{itinerary_id}",
            json={"title": "成都摄影周末", "budget_total": 500, "expected_version": 1, "itinerary_days": [{"day_number": 1, "title": "第1天 · 摄影", "stops": [{"attraction_id": attractions[0]["id"], "name": attractions[0]["name"], "start_time": "10:00", "end_time": "12:00", "note": "已调整"}]}]},
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "成都摄影周末"
        assert client.get(f"/api/v1/itineraries/{itinerary_id}/revisions").json()
        assert client.put(f"/api/v1/itineraries/{itinerary_id}/feedback", json={"rating": 9, "comment": "路线清晰"}, headers=headers).status_code == 200

        share = client.post(f"/api/v1/itineraries/{itinerary_id}/shares", json={"expires_days": 7}, headers=headers)
        assert share.status_code == 200
        token = re.search(r"/share/itineraries/([^/]+)$", share.json()["share_url"]).group(1)
        assert client.get(f"/api/v1/shares/{token}").json()["title"] == "成都摄影周末"
