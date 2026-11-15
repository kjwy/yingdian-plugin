"""TMDB：片名 → tmdb_id / media_type

国内直连 api.themoviedb.org 常不通，所以支持：
- tmdb_proxy：HTTP 代理（留空则沿用 Telegram 的代理）
- tmdb_api_base：API 域名（可换成镜像，如 https://api.tmdb.org/3）
- tmdb_image_base：图片域名
"""
from __future__ import annotations

import httpx

from .config import load_config

DEFAULT_API = "https://api.themoviedb.org/3"
DEFAULT_IMG = "https://image.tmdb.org/t/p"


def _cfg():
    return load_config()


def _api_base() -> str:
    return (_cfg().get("tmdb_api_base") or DEFAULT_API).rstrip("/")


def _img_base(size: str = "w185") -> str:
    base = (_cfg().get("tmdb_image_base") or DEFAULT_IMG).rstrip("/")
    return f"{base}/{size}"


def _client(timeout: float = 15.0) -> httpx.Client:
    cfg = _cfg()
    proxy = (cfg.get("tmdb_proxy") or cfg.get("tg_proxy") or "").strip()
    if proxy:
        try:
            return httpx.Client(timeout=timeout, proxy=proxy)
        except TypeError:
            return httpx.Client(timeout=timeout, proxies=proxy)
    return httpx.Client(timeout=timeout)


def search(query: str, media_type: str = "movie", limit: int = 8) -> list[dict]:
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key or not query.strip():
        return []
    endpoint = "search/movie" if media_type == "movie" else "search/tv"
    try:
        with _client() as c:
            r = c.get(
                f"{_api_base()}/{endpoint}",
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
                "poster": f"{_img_base()}{poster}" if poster else "",
                "overview": (it.get("overview") or "")[:200],
            }
        )
    return out


def check() -> tuple[bool, str]:
    """诊断：调用 /configuration 验证 Key、域名与网络"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return False, "未填写 TMDB API Key"
    proxy = (cfg.get("tmdb_proxy") or cfg.get("tg_proxy") or "").strip()
    try:
        with _client(20) as c:
            r = c.get(f"{_api_base()}/configuration", params={"api_key": key})
            if r.status_code == 401:
                return False, "Key 无效（401），请检查是否复制完整"
            r.raise_for_status()
            data = r.json()
        img = (data.get("images") or {}).get("secure_base_url", "")
        extra = f"，代理 {proxy}" if proxy else "，直连"
        return True, f"连接正常{extra}" + (f"，图片域名 {img}" if img else "")
    except Exception as exc:  # noqa: BLE001
        hint = "网络不通，建议填代理或换 API 域名（如 https://api.tmdb.org/3）"
        return False, f"连接失败：{type(exc).__name__}: {exc}。{hint}"
