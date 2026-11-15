"""TMDB 搜索：片名 → tmdb_id / media_type（影癫 OpenAPI 不做关键词搜索）"""
from __future__ import annotations

import httpx

from .config import load_config

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w185"


def search(query: str, media_type: str = "movie", limit: int = 8) -> list[dict]:
    cfg = load_config()
    key = cfg.get("tmdb_api_key", "")
    if not key or not query.strip():
        return []
    endpoint = "search/movie" if media_type == "movie" else "search/tv"
    try:
        with httpx.Client(timeout=15) as c:
            r = c.get(
                f"{BASE}/{endpoint}",
                params={"api_key": key, "query": query.strip(), "language": cfg.get("tmdb_language", "zh-CN")},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out = []
    for it in data.get("results", [])[:limit]:
        poster = it.get("poster_path")
        out.append(
            {
                "tmdb_id": it.get("id"),
                "title": it.get("title") or it.get("name") or "",
                "original_title": it.get("original_title") or it.get("original_name") or "",
                "year": (it.get("release_date") or it.get("first_air_date") or "")[:4],
                "media_type": media_type,
                "poster": f"{IMG}{poster}" if poster else "",
                "overview": (it.get("overview") or "")[:200],
            }
        )
    return out
