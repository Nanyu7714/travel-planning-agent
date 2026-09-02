from fastapi.testclient import TestClient
import time

from app.main import app
from conftest import register_and_login


def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"account": "admin", "password": "123456"})
    assert response.status_code == 200
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def city_payload(slug: str, name: str) -> dict:
    return {
        "slug": slug,
        "name": name,
        "aliases": [f"{name}市"],
        "description": "用于管理员内容管理回归测试的城市资料。",
        "season": "春秋",
        "budget": "¥300-500/天",
        "recommended_days": "2-3天",
        "image_url": "",
    }


def test_admin_content_crud_import_ranking_and_audit():
    with TestClient(app) as client:
        headers = admin_headers(client)
        created_city = client.post("/api/v1/admin/cities", json=city_payload("admin-test-city", "测试城市"), headers=headers)
        assert created_city.status_code == 201
        city_id = created_city.json()["id"]

        updated_city = client.patch(f"/api/v1/admin/cities/{city_id}", json={"planning_enabled": False}, headers=headers)
        assert updated_city.status_code == 200
        assert updated_city.json()["planning_enabled"] is False

        attraction = client.post("/api/v1/admin/attractions", json={
            "city_id": city_id, "name": "测试景点", "description": "用于测试的景点。", "tags": ["文化"],
            "opening_hours": "09:00-17:00", "ticket_price": 10, "duration_minutes": 90, "area": "测试区",
        }, headers=headers)
        assert attraction.status_code == 201
        attraction_id = attraction.json()["id"]

        blocked_city_delete = client.delete(f"/api/v1/admin/cities/{city_id}", headers=headers)
        assert blocked_city_delete.status_code == 409

        ranking = client.post("/api/v1/admin/rankings", json={"ranking_type": "city", "city_id": city_id, "rank": 1, "score": 96, "reason": "管理员核验"}, headers=headers)
        assert ranking.status_code == 201
        ranking_id = ranking.json()["id"]
        assert client.get("/api/v1/rankings?type=city").json()[0]["name"] == "测试城市"

        imported = client.post("/api/v1/admin/cities/import", json={"items": [city_payload("admin-import-city", "导入城市")]}, headers=headers)
        assert imported.status_code == 200
        assert imported.json()["created"] == 1
        imported_city = next(item for item in client.get("/api/v1/admin/cities", headers=headers).json() if item["slug"] == "admin-import-city")

        duplicate_target = client.post("/api/v1/admin/rankings", json={"ranking_type": "city", "city_id": city_id, "rank": 2, "score": 90, "reason": "重复对象"}, headers=headers)
        assert duplicate_target.status_code == 409
        duplicate_rank = client.post("/api/v1/admin/rankings", json={"ranking_type": "city", "city_id": imported_city["id"], "rank": 1, "score": 90, "reason": "重复名次"}, headers=headers)
        assert duplicate_rank.status_code == 409

        audits = client.get("/api/v1/admin/audit-logs", headers=headers)
        assert audits.status_code == 200
        assert audits.json()["total"] >= 5

        assert client.delete(f"/api/v1/admin/rankings/{ranking_id}", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/admin/attractions/{attraction_id}", headers=headers).status_code == 409
        stopped_attraction = client.patch(f"/api/v1/admin/attractions/{attraction_id}", json={"is_active": False}, headers=headers)
        assert stopped_attraction.status_code == 200
        assert client.get(f"/api/v1/attractions/{attraction_id}").status_code == 404
        assert client.delete(f"/api/v1/admin/attractions/{attraction_id}", headers=headers).status_code == 204
        assert client.patch(f"/api/v1/admin/cities/{city_id}", json={"is_active": False}, headers=headers).status_code == 200
        assert city_id not in {item["id"] for item in client.get("/api/v1/cities").json()}
        assert client.delete(f"/api/v1/admin/cities/{city_id}", headers=headers).status_code == 204
        assert client.patch(f"/api/v1/admin/cities/{imported_city['id']}", json={"is_active": False}, headers=headers).status_code == 200
        assert client.delete(f"/api/v1/admin/cities/{imported_city['id']}", headers=headers).status_code == 204


def test_linked_content_stays_deactivated_and_admin_mutations_are_audited():
    with TestClient(app) as client:
        headers = admin_headers(client)
        cities = client.get("/api/v1/admin/cities", headers=headers).json()
        seeded_city = cities[0]
        seeded_attraction = client.get(f"/api/v1/admin/attractions?city_id={seeded_city['id']}", headers=headers).json()[0]

        assert client.patch(f"/api/v1/admin/attractions/{seeded_attraction['id']}", json={"is_active": False}, headers=headers).status_code == 200
        linked_delete = client.delete(f"/api/v1/admin/attractions/{seeded_attraction['id']}", headers=headers)
        assert linked_delete.status_code == 409
        assert "只能保持停用" in linked_delete.json()["detail"]

        asset = next(item for item in client.get("/api/v1/admin/media-assets", headers=headers).json() if not item["is_active"] and item["url"])
        assert client.patch(f"/api/v1/admin/media-assets/{asset['id']}", json={"alt_text": f"审计测试 {asset['id']}"}, headers=headers).status_code == 200

        suffix = str(time.time_ns())
        username = f"test{suffix}"
        register_and_login(client, username, f"{username}@example.com")
        user_csrf = client.cookies.get("csrf_token")
        session_id = client.post("/api/v1/sessions", json={}, headers={"X-CSRF-Token": user_csrf}).json()["id"]
        assert client.delete(f"/api/v1/sessions/{session_id}", headers={"X-CSRF-Token": user_csrf}).status_code == 204

        headers = admin_headers(client)
        admin_users = client.get(f"/api/v1/admin/users?search={username}&page=1&page_size=10", headers=headers).json()["items"]
        account = next(item for item in admin_users if item["username"] == username)
        assert client.patch(f"/api/v1/admin/users/{account['id']}", json={"is_active": False}, headers=headers).status_code == 200
        assert client.post(f"/api/v1/admin/sessions/{session_id}/restore", json={}, headers=headers).status_code == 200

        audit_items = client.get("/api/v1/admin/audit-logs?page=1&page_size=100", headers=headers).json()["items"]
        actions = {(item["action"], item["target_type"], item["target_id"]) for item in audit_items}
        assert ("update", "media_asset", asset["id"]) in actions
        assert ("deactivate", "user", account["id"]) in actions
        assert ("restore", "session", session_id) in actions
        assert client.patch(f"/api/v1/admin/attractions/{seeded_attraction['id']}", json={"is_active": True}, headers=headers).status_code == 200
