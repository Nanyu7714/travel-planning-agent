import os

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "ok"}


def test_public_search_finds_cities_and_attractions():
    with TestClient(app) as client:
        cities = client.get("/api/v1/cities").json()
        city = cities[0]
        attractions = client.get(f"/api/v1/cities/{city['id']}/attractions").json()

        city_results = client.get("/api/v1/cities/search", params={"q": city["name"]}).json()
        attraction_results = client.get("/api/v1/attractions/search", params={"q": attractions[0]["name"]}).json()
        city_attraction_results = client.get("/api/v1/attractions/search", params={"q": city["name"]}).json()

        assert city_results[0]["id"] == city["id"]
        assert attractions[0]["id"] in {item["id"] for item in attraction_results}
        assert {item["city_id"] for item in city_attraction_results} == {city["id"]}


def test_attraction_rankings_are_filtered_by_city():
    with TestClient(app) as client:
        cities = client.get("/api/v1/cities").json()
        assert cities
        for city in cities:
            attractions = client.get(f"/api/v1/cities/{city['id']}/attractions").json()
            rankings = client.get(f"/api/v1/rankings?type=attraction&city_id={city['id']}").json()
            assert rankings
            assert {item["city_id"] for item in rankings} == {city["id"]}
            assert {item["attraction_id"] for item in rankings} <= {item["id"] for item in attractions}
            assert [item["rank"] for item in rankings] == list(range(1, len(rankings) + 1))


def test_global_attraction_ranking_returns_top_ten_from_all_cities():
    with TestClient(app) as client:
        cities = client.get("/api/v1/cities").json()
        attraction_count = sum(len(client.get(f"/api/v1/cities/{city['id']}/attractions").json()) for city in cities)
        rankings = client.get("/api/v1/rankings?type=attraction").json()

        assert len(rankings) == min(10, attraction_count)
        assert [item["rank"] for item in rankings] == list(range(1, len(rankings) + 1))
        assert [item["score"] for item in rankings] == sorted((item["score"] for item in rankings), reverse=True)
        assert len({item["city_id"] for item in rankings}) > 1
        assert {item["data_source"] for item in rankings} == {"initialization_heuristic"}


def test_media_assets_are_grouped_by_city_and_content():
    with TestClient(app) as client:
        cities = client.get("/api/v1/cities").json()
        all_assets = client.get("/api/v1/media-assets?include_inactive=true").json()
        assert len(all_assets) == 15

        for city in cities:
            city_assets = [item for item in all_assets if item["city_id"] == city["id"]]
            city_covers = [item for item in city_assets if item["purpose"] == "city_cover"]
            attraction_covers = [item for item in city_assets if item["purpose"] == "attraction_cover"]
            assert len(city_covers) == 1
            assert len(attraction_covers) == 4
            assert all(item["content_key"].startswith(f"{city['slug']}:") for item in city_assets)

        chengdu = next(city for city in cities if city["slug"] == "chengdu")
        chengdu_cover = next(item for item in all_assets if item["city_id"] == chengdu["id"] and item["purpose"] == "city_cover")
        assert chengdu["image_url"] == ""
        assert chengdu_cover["verification_status"] == "rejected_wrong_city"
        assert chengdu_cover["is_active"] is False


def test_admin_can_autofill_review_and_activate_attraction_image(monkeypatch):
    candidate = {
        "url": "https://upload.wikimedia.org/example.jpg",
        "mime_type": "image/jpeg",
        "alt_text": "景点测试图片",
        "source_name": "Wikimedia Commons",
        "source_author": "Example Author",
        "license_name": "CC BY-SA 4.0",
        "attribution_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    }
    monkeypatch.setattr("app.main.collect_photo_candidates", lambda *_args, **_kwargs: [candidate])
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"account": "admin", "password": os.environ["ADMIN_INITIAL_PASSWORD"]})
        assert login.status_code == 200
        headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
        assets = client.get("/api/v1/admin/media-assets").json()
        missing = next(asset for asset in assets if asset["attraction_id"] is not None and asset["verification_status"] == "missing")

        filled = client.post(f"/api/v1/admin/media-assets/{missing['id']}/autofill", json={}, headers=headers)
        assert filled.status_code == 200
        assert filled.json()["verification_status"] == "needs_review"
        assert filled.json()["is_active"] is False
        assert filled.json()["source_author"] == "Example Author"

        activated = client.patch(
            f"/api/v1/admin/media-assets/{missing['id']}",
            json={"verification_status": "approved", "is_active": True},
            headers=headers,
        )
        assert activated.status_code == 200
        attraction = client.get(f"/api/v1/attractions/{missing['attraction_id']}").json()
        assert attraction["image_url"] == candidate["url"]
