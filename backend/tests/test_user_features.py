import re
import uuid
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import CommunityPost, Favorite, Itinerary, ItineraryDay, ItineraryStop, ShareLink, User, UserProfile
from conftest import register_and_login


def test_legacy_profile_null_lists_are_normalized():
    suffix = str(uuid.uuid4().int)
    with TestClient(app) as client:
        register_and_login(client, f"test{suffix}", f"test{suffix}@example.com")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == f"test{suffix}").one()
            db.add(UserProfile(user_id=user.id, preferences=None, avoid_places=None))
            db.commit()
        finally:
            db.close()

        profile = client.get("/api/v1/auth/profile")
        assert profile.status_code == 200
        assert profile.json()["preferences"] == []
        assert profile.json()["avoid_places"] == []


def test_user_content_profile_itinerary_share_and_feedback():
    suffix = str(uuid.uuid4().int)
    with TestClient(app) as client:
        register_and_login(client, f"test{suffix}", f"test{suffix}@example.com")
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
            user = db.query(User).filter(User.username == f"test{suffix}").one()
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


def test_itinerary_favorites_require_ownership_and_draft_cannot_be_shared():
    suffix = str(uuid.uuid4().int)
    owner_name = f"test{suffix}"
    other_name = f"test9{suffix}"
    with TestClient(app) as client:
        register_and_login(client, owner_name, f"{owner_name}@example.com")
        owner_csrf = client.cookies.get("csrf_token")

        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == owner_name).one()
            saved = Itinerary(user_id=owner.id, title="私有已保存行程", city_name="成都", days=1, status="saved", budget_total=300)
            draft = Itinerary(user_id=owner.id, title="私有草稿", city_name="成都", days=1, status="draft", budget_total=300)
            db.add_all([saved, draft])
            db.commit()
            saved_id = saved.id
            draft_id = draft.id
        finally:
            db.close()

        assert client.put(
            f"/api/v1/favorites/itinerary/{saved_id}", json={}, headers={"X-CSRF-Token": owner_csrf}
        ).status_code == 200
        draft_share = client.post(
            f"/api/v1/itineraries/{draft_id}/shares",
            json={"expires_days": 7},
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert draft_share.status_code == 409

        register_and_login(client, other_name, f"{other_name}@example.com")
        other_csrf = client.cookies.get("csrf_token")
        assert client.put(
            f"/api/v1/favorites/itinerary/{saved_id}", json={}, headers={"X-CSRF-Token": other_csrf}
        ).status_code == 404

        db = SessionLocal()
        try:
            other = db.query(User).filter(User.username == other_name).one()
            db.add(Favorite(user_id=other.id, target_type="itinerary", target_id=saved_id))
            db.commit()
        finally:
            db.close()
        assert all(item["target_id"] != saved_id for item in client.get("/api/v1/favorites").json())


def test_account_deletion_revokes_existing_itinerary_shares():
    suffix = str(uuid.uuid4().int)
    username = f"test{suffix}"
    with TestClient(app) as client:
        register_and_login(client, username, f"{username}@example.com")
        csrf = client.cookies.get("csrf_token")

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).one()
            itinerary = Itinerary(user_id=user.id, title="注销前分享行程", city_name="成都", days=1, status="saved", budget_total=300)
            db.add(itinerary)
            db.commit()
            itinerary_id = itinerary.id
        finally:
            db.close()

        share = client.post(
            f"/api/v1/itineraries/{itinerary_id}/shares",
            json={"expires_days": 7},
            headers={"X-CSRF-Token": csrf},
        )
        assert share.status_code == 200
        token = re.search(r"/share/itineraries/([^/]+)$", share.json()["share_url"]).group(1)
        assert client.get(f"/api/v1/shares/{token}").status_code == 200

        deleted = client.request(
            "DELETE",
            "/api/v1/auth/me",
            json={"password": "test123456"},
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/shares/{token}").status_code == 404

        db = SessionLocal()
        try:
            share_record = db.query(ShareLink).filter(ShareLink.itinerary_id == itinerary_id).one()
            assert share_record.revoked_at is not None
        finally:
            db.close()


def test_itinerary_soft_delete_admin_restore_and_protected_hard_delete():
    suffix = str(uuid.uuid4().int)
    username = f"test{suffix}"
    with TestClient(app) as client:
        register_and_login(client, username, f"{username}@example.com")
        user_csrf = client.cookies.get("csrf_token")
        user_headers = {"X-CSRF-Token": user_csrf}

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).one()
            retained = Itinerary(user_id=user.id, title="需要恢复的行程", city_name="成都", days=1, status="saved", budget_total=300)
            disposable = Itinerary(user_id=user.id, title="无关联临时行程", city_name="成都", days=1, status="saved", budget_total=100)
            db.add_all([retained, disposable])
            db.flush()
            day = ItineraryDay(itinerary_id=retained.id, day_number=1, title="第1天")
            disposable_day = ItineraryDay(itinerary_id=disposable.id, day_number=1, title="第1天")
            db.add_all([day, disposable_day])
            db.commit()
            retained_id = retained.id
            disposable_id = disposable.id
            retained_day_id = day.id
            disposable_day_id = disposable_day.id
        finally:
            db.close()

        assert client.put(f"/api/v1/favorites/itinerary/{retained_id}", json={}, headers=user_headers).status_code == 200
        share = client.post(f"/api/v1/itineraries/{retained_id}/shares", json={"expires_days": 7}, headers=user_headers)
        assert share.status_code == 200
        token = re.search(r"/share/itineraries/([^/]+)$", share.json()["share_url"]).group(1)

        assert client.delete(f"/api/v1/itineraries/{retained_id}", headers=user_headers).status_code == 204
        assert retained_id not in {item["id"] for item in client.get("/api/v1/itineraries").json()}
        assert client.get(f"/api/v1/itineraries/{retained_id}").status_code == 404
        assert client.get(f"/api/v1/shares/{token}").status_code == 404
        assert retained_id not in {item["target_id"] for item in client.get("/api/v1/favorites").json()}
        assert client.get("/api/v1/admin/itineraries").status_code == 403

        db = SessionLocal()
        try:
            assert db.get(Itinerary, retained_id).deleted_at is not None
            assert db.get(ItineraryDay, retained_day_id) is not None
            assert db.query(ShareLink).filter(ShareLink.itinerary_id == retained_id).one().revoked_at is not None
        finally:
            db.close()

        assert client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"}).status_code == 200
        admin_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        deleted_page = client.get("/api/v1/admin/itineraries?state=deleted&page=1&page_size=10")
        assert deleted_page.status_code == 200
        retained_row = next(item for item in deleted_page.json()["items"] if item["id"] == retained_id)
        assert retained_row["association_count"] >= 2
        assert retained_row["can_hard_delete"] is False
        assert client.delete(f"/api/v1/admin/itineraries/{retained_id}", headers=admin_headers).status_code == 409

        restored = client.post(f"/api/v1/admin/itineraries/{retained_id}/restore", json={}, headers=admin_headers)
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None
        assert client.get(f"/api/v1/shares/{token}").status_code == 404

        assert client.post("/api/v1/auth/login", json={"account": username, "password": "test123456"}).status_code == 200
        user_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        assert client.get(f"/api/v1/itineraries/{retained_id}").status_code == 200
        assert client.delete(f"/api/v1/itineraries/{disposable_id}", headers=user_headers).status_code == 204

        assert client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"}).status_code == 200
        admin_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        disposable_row = next(
            item for item in client.get("/api/v1/admin/itineraries?state=deleted&page=1&page_size=10").json()["items"]
            if item["id"] == disposable_id
        )
        assert disposable_row["can_hard_delete"] is True
        assert client.delete(f"/api/v1/admin/itineraries/{disposable_id}", headers=admin_headers).status_code == 204
        db = SessionLocal()
        try:
            assert db.get(Itinerary, disposable_id) is None
            assert db.get(ItineraryDay, disposable_day_id) is None
        finally:
            db.close()


def test_itinerary_edit_rejects_invalid_attractions_and_times():
    suffix = str(uuid.uuid4().int)
    with TestClient(app) as client:
        register_and_login(client, f"test{suffix}", f"test{suffix}@example.com")
        csrf = client.cookies.get("csrf_token")
        headers = {"X-CSRF-Token": csrf}

        cities = client.get("/api/v1/cities").json()
        first_attractions = client.get(f"/api/v1/cities/{cities[0]['id']}/attractions").json()
        other_attractions = client.get(f"/api/v1/cities/{cities[1]['id']}/attractions").json()
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == f"test{suffix}").one()
            itinerary = Itinerary(user_id=user.id, title="校验行程", city_name=cities[0]["name"], days=1, budget_total=100)
            db.add(itinerary)
            db.flush()
            day = ItineraryDay(itinerary_id=itinerary.id, day_number=1, title="第1天")
            db.add(day)
            db.flush()
            db.add(ItineraryStop(day_id=day.id, attraction_id=first_attractions[0]["id"], name=first_attractions[0]["name"], start_time="09:00", end_time="10:00", note=""))
            db.commit()
            itinerary_id = itinerary.id
        finally:
            db.close()

        def stop(attraction, start="09:00", end="10:00"):
            return {"attraction_id": attraction["id"], "name": attraction["name"], "start_time": start, "end_time": end, "note": ""}

        cross_city = client.put(
            f"/api/v1/itineraries/{itinerary_id}",
            json={"expected_version": 1, "itinerary_days": [{"day_number": 1, "title": "第1天", "stops": [stop(other_attractions[0])]}]},
            headers=headers,
        )
        assert cross_city.status_code == 422

        invalid_time = client.put(
            f"/api/v1/itineraries/{itinerary_id}",
            json={"expected_version": 1, "itinerary_days": [{"day_number": 1, "title": "第1天", "stops": [stop(first_attractions[0], "25:00", "26:00")]}]},
            headers=headers,
        )
        assert invalid_time.status_code == 422

        overlap = client.put(
            f"/api/v1/itineraries/{itinerary_id}",
            json={"expected_version": 1, "itinerary_days": [{"day_number": 1, "title": "第1天", "stops": [stop(first_attractions[0]), stop(first_attractions[1], "09:30", "10:30")]}]},
            headers=headers,
        )
        assert overlap.status_code == 422

        duplicate = client.put(
            f"/api/v1/itineraries/{itinerary_id}",
            json={"expected_version": 1, "itinerary_days": [{"day_number": 1, "title": "第1天", "stops": [stop(first_attractions[0]), stop(first_attractions[0], "11:00", "12:00")]}]},
            headers=headers,
        )
        assert duplicate.status_code == 422


def test_community_post_snapshot_interactions_and_withdrawal():
    suffix = str(uuid.uuid4().int)
    owner_name = f"test{suffix}"
    other_name = f"test8{suffix}"
    with TestClient(app) as client:
        owner_registration = client.post(
            "/api/v1/auth/register",
            json={"username": owner_name, "email": f"{owner_name}@example.com", "password": "test123456"},
        )
        assert owner_registration.status_code == 202
        owner_token = parse_qs(urlparse(owner_registration.json()["dev_action_url"]).query)["token"][0]
        assert client.post("/api/v1/auth/verify-email", json={"token": owner_token}).status_code == 200
        assert client.post("/api/v1/auth/login", json={"account": owner_name, "password": "test123456"}).status_code == 200
        owner_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}

        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == owner_name).one()
            itinerary = Itinerary(user_id=owner.id, title="社区行程", city_name="成都", days=1, status="saved", budget_total=320)
            db.add(itinerary)
            db.flush()
            day = ItineraryDay(itinerary_id=itinerary.id, day_number=1, title="第1天")
            db.add(day)
            db.flush()
            db.add(ItineraryStop(day_id=day.id, attraction_id=None, name="宽窄巷子", start_time="09:00", end_time="11:00", note="不应公开的私人备注"))
            db.commit()
            itinerary_id = itinerary.id
        finally:
            db.close()

        created = client.post(
            "/api/v1/community/posts",
            json={"itinerary_id": itinerary_id, "title": "成都慢游两日", "body": "在茶馆和街巷里慢慢走。"},
            headers=owner_headers,
        )
        assert created.status_code == 201
        post = created.json()
        post_id = post["id"]
        assert post["itinerary"]["itinerary_days"][0]["stops"][0].get("note") is None
        assert client.get("/api/v1/community/posts").json()["items"][0]["id"] == post_id

        other_registration = client.post(
            "/api/v1/auth/register",
            json={"username": other_name, "email": f"{other_name}@example.com", "password": "test123456"},
        )
        assert other_registration.status_code == 202
        other_token = parse_qs(urlparse(other_registration.json()["dev_action_url"]).query)["token"][0]
        assert client.post("/api/v1/auth/verify-email", json={"token": other_token}).status_code == 200
        assert client.post("/api/v1/auth/login", json={"account": other_name, "password": "test123456"}).status_code == 200
        other_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        assert client.put(f"/api/v1/community/posts/{post_id}/like", json={}, headers=other_headers).status_code == 200
        assert client.put(f"/api/v1/community/posts/{post_id}/like", json={}, headers=other_headers).status_code == 200
        assert client.put(f"/api/v1/community/posts/{post_id}/favorite", json={}, headers=other_headers).status_code == 200
        comment = client.post(f"/api/v1/community/posts/{post_id}/comments", json={"body": "路线很有参考价值"}, headers=other_headers)
        assert comment.status_code == 201
        detail = client.get(f"/api/v1/community/posts/{post_id}").json()
        assert detail["like_count"] == 1
        assert detail["favorite_count"] == 1
        assert detail["comment_count"] == 1
        assert detail["comments"][0]["body"] == "路线很有参考价值"
        assert client.post("/api/v1/community/reports", json={"target_type": "post", "target_id": post_id, "reason": "测试举报"}, headers=other_headers).status_code == 201

        assert client.post("/api/v1/auth/login", json={"account": owner_name, "password": "test123456"}).status_code == 200
        owner_headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        assert client.delete(f"/api/v1/community/posts/{post_id}", headers=owner_headers).status_code == 204
        assert client.get(f"/api/v1/community/posts/{post_id}").status_code == 404
        db = SessionLocal()
        try:
            assert db.get(CommunityPost, post_id).status == "hidden"
        finally:
            db.close()
