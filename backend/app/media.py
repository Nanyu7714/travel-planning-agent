import html
import re
from typing import Any

import httpx


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"


def _plain_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"<[^>]+>", "", html.unescape(value)).strip()
    return text or None


def search_commons_image(search_term: str) -> dict | None:
    """Return one traceable Wikimedia Commons image candidate without approving it."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{search_term} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "5",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1600",
    }
    try:
        response = httpx.get(COMMONS_API_URL, params=params, timeout=12, follow_redirects=True)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
    except (httpx.HTTPError, ValueError):
        return None

    for page in pages.values():
        image_info = (page.get("imageinfo") or [None])[0]
        if not image_info or not image_info.get("url"):
            continue
        metadata = image_info.get("extmetadata") or {}
        author = _plain_text((metadata.get("Artist") or {}).get("value"))
        license_name = _plain_text((metadata.get("LicenseShortName") or {}).get("value"))
        return {
            "url": image_info.get("thumburl") or image_info["url"],
            "mime_type": image_info.get("mime"),
            "alt_text": _plain_text((metadata.get("ImageDescription") or {}).get("value")) or page.get("title", "").removeprefix("File:"),
            "source_name": "Wikimedia Commons",
            "source_author": author,
            "license_name": license_name,
            "attribution_url": image_info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{page.get('title', '').replace(' ', '_')}",
        }
    return None
