from __future__ import annotations

from datetime import date

import httpx

from app.core.config import settings


AMAP_DIRECTION_URLS = {
    "walking": "https://restapi.amap.com/v5/direction/walking",
    "driving": "https://restapi.amap.com/v5/direction/driving",
    "public_transport": "https://restapi.amap.com/v5/direction/transit/integrated",
}
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
AMAP_NEARBY_PLACE_URL = "https://restapi.amap.com/v3/place/around"


def format_coordinate(latitude: float, longitude: float) -> str:
    return f"{longitude:.6f},{latitude:.6f}"


def parse_coordinate(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    try:
        longitude, latitude = (float(item) for item in value.split(",", 1))
    except (TypeError, ValueError):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def request_amap_geocode(address: str) -> dict | None:
    """Resolve a city name to a route endpoint coordinate without exposing the API key."""
    if not settings.amap_web_service_key or not address.strip():
        return None
    try:
        response = httpx.get(
            AMAP_GEOCODE_URL,
            params={"key": settings.amap_web_service_key, "address": address},
            timeout=12,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    geocodes = payload.get("geocodes") or []
    if payload.get("status") != "1" or not geocodes:
        return None
    geocode = geocodes[0]
    coordinate = parse_coordinate(geocode.get("location"))
    if not coordinate:
        return None
    return {"coordinate": coordinate, "citycode": geocode.get("citycode")}


def request_amap_weather(city_code: str | None, travel_date: date | None) -> dict:
    """Return the available forecast for the planned date without fabricating weather data."""
    if not travel_date:
        return {"status": "unknown", "reason": "未填写出行日期"}
    if not settings.amap_web_service_key or not city_code:
        return {"status": "unknown", "reason": "高德天气服务未配置或城市编码不可用", "date": travel_date.isoformat()}
    try:
        response = httpx.get(
            AMAP_WEATHER_URL,
            params={"key": settings.amap_web_service_key, "city": city_code, "extensions": "all"},
            timeout=12,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"status": "unknown", "reason": "高德天气服务暂时不可用", "date": travel_date.isoformat()}
    forecasts = payload.get("forecasts") or []
    casts = forecasts[0].get("casts") if forecasts else []
    matched = next((item for item in casts or [] if item.get("date") == travel_date.isoformat()), None)
    if not matched:
        return {"status": "unknown", "reason": "计划日期不在天气预报范围内", "date": travel_date.isoformat()}
    return {
        "status": "passed",
        "provider": "高德天气",
        "date": travel_date.isoformat(),
        "day_weather": matched.get("dayweather"),
        "night_weather": matched.get("nightweather"),
        "day_temp": matched.get("daytemp"),
        "night_temp": matched.get("nighttemp"),
        "day_wind": matched.get("daywind"),
        "day_power": matched.get("daypower"),
    }


def request_amap_nearby_food(coordinate: tuple[float, float], city: str, limit: int = 2) -> list[dict]:
    """Find traceable nearby food POIs for a planned stop."""
    if not settings.amap_web_service_key:
        return []
    try:
        response = httpx.get(
            AMAP_NEARBY_PLACE_URL,
            params={
                "key": settings.amap_web_service_key,
                "location": format_coordinate(*coordinate),
                "types": "餐饮服务",
                "city": city,
                "radius": "1500",
                "sortrule": "distance",
                "offset": str(max(1, min(limit, 10))),
                "page": "1",
                "extensions": "all",
            },
            timeout=12,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if payload.get("status") != "1":
        return []
    return [
        {
            "name": item.get("name"),
            "address": item.get("address"),
            "distance_meters": int(_number(item.get("distance"))),
            "type": item.get("type"),
            "rating": (item.get("biz_ext") or {}).get("rating"),
        }
        for item in (payload.get("pois") or [])[:limit]
        if item.get("name")
    ]


def request_amap_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    transport: str,
    city_code: str | None = None,
    destination_city_code: str | None = None,
    travel_date: date | None = None,
) -> dict | None:
    """Fetch one route segment and return a provider-neutral summary without credentials."""
    if not settings.amap_web_service_key:
        return None
    mode = transport if transport in AMAP_DIRECTION_URLS or transport == "taxi" else "public_transport"
    request_mode = "driving" if mode == "taxi" else mode
    params = {
        "key": settings.amap_web_service_key,
        "origin": format_coordinate(*origin),
        "destination": format_coordinate(*destination),
        "show_fields": "cost",
    }
    if request_mode == "public_transport":
        if not city_code:
            return None
        params.update({"city1": city_code, "city2": destination_city_code or city_code, "strategy": "0"})
        if travel_date:
            params["date"] = travel_date.isoformat()
            params["time"] = "09-00"
    try:
        response = httpx.get(AMAP_DIRECTION_URLS[request_mode], params=params, timeout=12, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if payload.get("status") != "1":
        return None
    route = payload.get("route") or {}
    paths = route.get("transits") if request_mode == "public_transport" else route.get("paths")
    schedule_date_fallback = False
    if not paths and request_mode == "public_transport" and travel_date:
        fallback_params = {key: value for key, value in params.items() if key not in {"date", "time"}}
        try:
            fallback_response = httpx.get(AMAP_DIRECTION_URLS[request_mode], params=fallback_params, timeout=12, follow_redirects=True)
            fallback_response.raise_for_status()
            fallback_payload = fallback_response.json()
        except (httpx.HTTPError, ValueError):
            fallback_payload = {}
        fallback_route = fallback_payload.get("route") or {}
        fallback_paths = fallback_route.get("transits") if fallback_payload.get("status") == "1" else []
        if fallback_paths:
            route, paths, schedule_date_fallback = fallback_route, fallback_paths, True
    if not paths:
        return None
    path = paths[0]
    cost = path.get("cost") or {}
    distance = int(_number(path.get("distance")))
    duration = int(_number(cost.get("duration") or path.get("duration")))
    if not distance or not duration:
        return None
    if mode == "public_transport":
        amount, source, cost_basis = _number(cost.get("transit_fee")), "高德公交票价", "per_person"
    elif mode == "taxi":
        amount, source, cost_basis = _number(route.get("taxi_cost")), "高德出租车预估", "vehicle"
    elif mode == "driving":
        amount, source, cost_basis = _number(cost.get("tolls")), "高德道路收费", "vehicle"
    else:
        amount, source, cost_basis = 0.0, "步行免费", "vehicle"
    return {
        "provider": "amap",
        "transport": mode,
        "distance_meters": distance,
        "duration_seconds": duration,
        "cost_yuan": round(amount, 2),
        "cost_source": source,
        "cost_basis": cost_basis,
        "schedule_date_fallback": schedule_date_fallback,
    }
