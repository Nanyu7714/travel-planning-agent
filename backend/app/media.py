import html
import io
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import settings


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
AMAP_PLACE_SEARCH_URL = "https://restapi.amap.com/v3/place/text"

_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_PIL_FORMATS = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}
Image.MAX_IMAGE_PIXELS = 40_000_000


def sanitize_image_bytes(content: bytes, max_bytes: int = 8 * 1024 * 1024) -> tuple[bytes, str, str]:
    """Decode and re-encode an image to discard EXIF and reject malformed files."""
    if not content or len(content) > max_bytes:
        raise ValueError("图片文件超过大小限制")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            image_format = probe.format
            probe.verify()
        if image_format not in _PIL_FORMATS:
            raise ValueError("仅支持 JPEG、PNG 或 WebP 图片")
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("图片像素过大")
            output = io.BytesIO()
            if image_format == "JPEG":
                source.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
            else:
                source.convert("RGBA").save(output, format=image_format, lossless=image_format == "WEBP")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片内容无效或不安全") from exc
    cleaned = output.getvalue()
    if len(cleaned) > max_bytes:
        raise ValueError("处理后的图片超过大小限制")
    mime_type, suffix = _PIL_FORMATS[image_format]
    return cleaned, mime_type, suffix


def _plain_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"<[^>]+>", "", html.unescape(value)).strip()
    return text or None


def _safe_filename(value: str) -> str:
    """Turn a user supplied keyword into a filesystem safe fragment."""
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "-", value).strip("-._")
    return cleaned[:80] or "photo"


def _extension_from_url(url: str, mime_type: str | None = None) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _MIME_EXTENSIONS.values():
        return ".jpg" if suffix == ".jpeg" else suffix
    return _MIME_EXTENSIONS.get((mime_type or "").lower(), ".jpg")


def search_commons_images(search_term: str, limit: int = 5) -> list[dict]:
    """Return traceable Wikimedia Commons image candidates without approving them."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{search_term} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": str(max(1, min(limit, 20))),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1600",
    }
    try:
        response = httpx.get(COMMONS_API_URL, params=params, timeout=12, follow_redirects=True)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
    except (httpx.HTTPError, ValueError):
        return []

    candidates: list[dict] = []
    for page in pages.values():
        image_info = (page.get("imageinfo") or [None])[0]
        if not image_info or not image_info.get("url"):
            continue
        metadata = image_info.get("extmetadata") or {}
        candidates.append(
            {
                "url": image_info.get("thumburl") or image_info["url"],
                "mime_type": image_info.get("mime"),
                "alt_text": _plain_text((metadata.get("ImageDescription") or {}).get("value"))
                or page.get("title", "").removeprefix("File:"),
                "source_name": "Wikimedia Commons",
                "source_author": _plain_text((metadata.get("Artist") or {}).get("value")),
                "license_name": _plain_text((metadata.get("LicenseShortName") or {}).get("value")),
                "attribution_url": image_info.get("descriptionurl")
                or f"https://commons.wikimedia.org/wiki/{page.get('title', '').replace(' ', '_')}",
            }
        )
    return candidates


def search_commons_image(search_term: str) -> dict | None:
    """Return one traceable Wikimedia Commons image candidate without approving it."""
    candidates = search_commons_images(search_term, limit=1)
    return candidates[0] if candidates else None


def search_unsplash_images(search_term: str, limit: int = 5) -> list[dict]:
    """Return Unsplash candidates. Requires UNSPLASH_ACCESS_KEY, otherwise returns nothing."""
    if not settings.unsplash_access_key:
        return []
    params = {"query": search_term, "per_page": str(max(1, min(limit, 20)))}
    headers = {"Authorization": f"Client-ID {settings.unsplash_access_key}"}
    try:
        response = httpx.get(UNSPLASH_SEARCH_URL, params=params, headers=headers, timeout=12, follow_redirects=True)
        response.raise_for_status()
        results = response.json().get("results") or []
    except (httpx.HTTPError, ValueError):
        return []

    return [
        {
            "url": item.get("urls", {}).get("regular") or item.get("urls", {}).get("full"),
            "mime_type": "image/jpeg",
            "alt_text": item.get("alt_description") or item.get("description") or search_term,
            "source_name": "Unsplash",
            "source_author": (item.get("user") or {}).get("name"),
            "license_name": "Unsplash License",
            "attribution_url": (item.get("links") or {}).get("html"),
        }
        for item in results
        if (item.get("urls") or {}).get("regular")
    ]


def search_pexels_images(search_term: str, limit: int = 5) -> list[dict]:
    """Return Pexels candidates. Requires PEXELS_API_KEY, otherwise returns nothing."""
    if not settings.pexels_api_key:
        return []
    params = {"query": search_term, "per_page": str(max(1, min(limit, 20)))}
    headers = {"Authorization": settings.pexels_api_key}
    try:
        response = httpx.get(PEXELS_SEARCH_URL, params=params, headers=headers, timeout=12, follow_redirects=True)
        response.raise_for_status()
        photos = response.json().get("photos") or []
    except (httpx.HTTPError, ValueError):
        return []

    return [
        {
            "url": item.get("src", {}).get("large") or item.get("src", {}).get("original"),
            "mime_type": "image/jpeg",
            "alt_text": item.get("alt") or search_term,
            "source_name": "Pexels",
            "source_author": item.get("photographer"),
            "license_name": "Pexels License",
            "attribution_url": item.get("url"),
        }
        for item in photos
        if (item.get("src") or {}).get("large")
    ]


def search_amap_place(keyword: str, city: str | None = None, max_pois: int = 10) -> dict | None:
    """Return AMap scenic spot details plus photos gathered from several top POIs.

    Photos are collected from the first few POI results (deduplicated) so that
    searching a keyword like a city name can surface photos of different spots.
    Needs AMAP_WEB_SERVICE_KEY.
    """
    if not settings.amap_web_service_key:
        return None
    params = {
        "key": settings.amap_web_service_key,
        "keywords": keyword,
        "types": "风景名胜",
        "offset": str(max(1, max_pois)),
        "page": "1",
        "extensions": "all",
    }
    if city:
        params["city"] = city
    try:
        response = httpx.get(AMAP_PLACE_SEARCH_URL, params=params, timeout=12, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
        pois = payload.get("pois") or []
    except (httpx.HTTPError, ValueError):
        return None
    if payload.get("status") != "1" or not pois:
        return None

    place = pois[0]
    biz_ext = place.get("biz_ext") or {}
    photos: list[dict] = []
    seen_urls: set[str] = set()
    for poi in pois[:max_pois]:
        poi_name = poi.get("name") or keyword
        attribution = poi.get("website") or f"https://www.amap.com/detail/{poi.get('id', '')}"
        for photo in poi.get("photos") or []:
            url = photo.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            photos.append(
                {
                    "url": url,
                    "mime_type": "image/jpeg",
                    "alt_text": photo.get("title") or poi_name,
                    "source_name": "高德地图",
                    "source_author": None,
                    "license_name": "高德地图开放平台",
                    "attribution_url": attribution,
                }
            )
    # AMap place/text returns name, address, type, biz_ext and photos; it does not return an intro field.
    return {
        "name": place.get("name"),
        "address": place.get("address"),
        "type": place.get("type"),
        "location": place.get("location"),
        "citycode": place.get("citycode"),
        "adcode": place.get("adcode"),
        "amap_id": place.get("id"),
        "rating": biz_ext.get("rating"),
        "cost": biz_ext.get("cost"),
        "photos": photos,
    }


def collect_photo_candidates(query: str, limit: int = 6, city: str | None = None) -> list[dict]:
    """Search every configured provider in order and return deduplicated candidates."""
    candidates: list[dict] = []
    # AMap is tried first because it usually matches Chinese attractions best.
    amap_place = search_amap_place(query, city)
    if amap_place:
        candidates.extend(amap_place.get("photos") or [])
    providers = (search_commons_images, search_unsplash_images, search_pexels_images)
    for provider in providers:
        if len(candidates) >= limit:
            break
        try:
            candidates.extend(provider(query, limit=limit - len(candidates)))
        except Exception:  # noqa: BLE001 - one broken provider must not block the others
            continue

    deduplicated: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = candidate.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        deduplicated.append(candidate)
    return deduplicated[:limit]


def download_image(url: str, media_root: Path, relative_dir: str, file_stem: str, mime_type: str | None = None) -> str | None:
    """Download one remote image into media_root/relative_dir and return its relative path."""
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    try:
        cleaned, _, suffix = sanitize_image_bytes(response.content)
    except ValueError:
        return None
    file_name = f"{_safe_filename(file_stem)}-{uuid.uuid4().hex}{suffix}"
    target = media_root / relative_dir / file_name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cleaned)
    except OSError:
        return None
    return str(Path(relative_dir) / file_name).replace("\\", "/")
