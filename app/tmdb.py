"""TMDB：片名 → tmdb_id / media_type

国内直连 api.themoviedb.org 经常不通，所以：
- 自动在多个域名间重试（themoviedb.org → api.tmdb.org）
- 支持代理
- search_ex 会区分"没搜到"和"网络失败"
"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote, urlencode

import httpx

from .config import load_config

DEFAULT_BASES = [
    "https://api.themoviedb.org/3",
    "https://api.tmdb.org/3",
]
DEFAULT_IMG = "https://image.tmdb.org/t/p"


def _cfg():
    return load_config()


def _bases() -> list[str]:
    cfg = _cfg()
    primary = (cfg.get("tmdb_api_base") or "").rstrip("/")
    out = []
    if primary:
        out.append(primary)
    for b in DEFAULT_BASES:
        if b not in out:
            out.append(b)
    return out


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


def _get(path: str, params: dict) -> tuple[dict | None, str]:
    """依次尝试多个域名，返回 (data, error)"""
    last_err = ""
    for base in _bases():
        try:
            with _client() as c:
                r = c.get(f"{base}/{path}", params=params)
                if r.status_code == 401:
                    return None, "TMDB Key 无效"
                r.raise_for_status()
                return r.json(), ""
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            continue
    return None, last_err


def search_ex(query: str, media_type: str = "movie", limit: int = 8) -> tuple[list[dict], str]:
    """返回 (结果列表, 错误信息)"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return [], "未填写 TMDB API Key"
    if not query.strip():
        return [], "请输入片名"

    endpoint = "search/movie" if media_type == "movie" else "search/tv"
    params = {
        "api_key": key,
        "query": query.strip(),
        "language": cfg.get("tmdb_language", "zh-CN"),
        "page": 1,
        "include_adult": "false",
    }
    data, err = _get(endpoint, params)
    if data is None:
        return [], f"TMDB 连接失败 · {err}"

    out = []
    for it in (data.get("results") or [])[:limit]:
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
    return out, ""


def search_multi_ex(query: str, limit: int = 8) -> tuple[list[dict], str]:
    """多类型搜索：一次搜出电影和剧集，自动带上 media_type"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return [], "未填写 TMDB API Key"
    if not query.strip():
        return [], "请输入片名"
    data, err = _get("search/multi", {
        "api_key": key, "query": query.strip(),
        "language": cfg.get("tmdb_language", "zh-CN"), "page": 1, "include_adult": "false",
    })
    if data is None:
        return [], f"TMDB 连接失败 · {err}"
    out = []
    for it in (data.get("results") or []):
        mt = it.get("media_type")
        if mt not in ("movie", "tv"):
            continue
        poster = it.get("poster_path")
        poster_url = f"{_img_base('w342')}{poster}" if poster else ""
        out.append({
            "tmdb_id": it.get("id"),
            "title": it.get("title") or it.get("name") or "",
            "original_title": it.get("original_title") or it.get("original_name") or "",
            "year": (it.get("release_date") or it.get("first_air_date") or "")[:4],
            "media_type": mt,
            "poster": f"{_img_base()}{poster}" if poster else "",
            "overview": (it.get("overview") or "")[:200],
        })
        if len(out) >= limit:
            break
    return out, ""


def search(query: str, media_type: str = "movie", limit: int = 8) -> list[dict]:
    items, _ = search_ex(query, media_type, limit)
    return items


def details(tmdb_id: int | str, media_type: str = "movie") -> dict:
    """读取媒体基础信息，用于搜索结果头部展示。"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return {}
    endpoint = f"movie/{int(tmdb_id)}" if media_type == "movie" else f"tv/{int(tmdb_id)}"
    data, _err = _get(
        endpoint,
        {"api_key": key, "language": cfg.get("tmdb_language", "zh-CN")},
    )
    if not data:
        return {}
    poster = data.get("poster_path")
    poster_url = f"{_img_base('w342')}{poster}" if poster else ""
    return {
        "tmdb_id": data.get("id"),
        "title": data.get("title") or data.get("name") or "",
        "original_title": data.get("original_title") or data.get("original_name") or "",
        "year": (data.get("release_date") or data.get("first_air_date") or "")[:4],
        "media_type": media_type,
        "rating": round(float(data.get("vote_average") or 0), 1),
        "poster": poster_url,
        "overview": (data.get("overview") or "")[:240],
    }


RANKING_PATHS = {
    "trending": ("trending/all/week", "本周热门"),
    "movie_popular": ("movie/popular", "电影热门"),
    "movie_top": ("movie/top_rated", "电影高分"),
    "movie_now": ("movie/now_playing", "正在上映"),
    "tv_popular": ("tv/popular", "剧集热门"),
    "tv_top": ("tv/top_rated", "剧集高分"),
}


def rankings(kind: str = "trending", limit: int = 20) -> tuple[list[dict], str]:
    """TMDB 榜单"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return [], "未填写 TMDB API Key"
    path, _label = RANKING_PATHS.get(kind, RANKING_PATHS["trending"])
    data, err = _get(path, {"api_key": key, "language": cfg.get("tmdb_language", "zh-CN"), "page": 1})
    if data is None:
        return [], f"TMDB 连接失败 · {err}"
    out = []
    for it in (data.get("results") or [])[:limit]:
        mt = it.get("media_type") or ("tv" if path.startswith("tv/") else "movie")
        if mt not in ("movie", "tv"):
            continue
        poster = it.get("poster_path")
        out.append({
            "tmdb_id": it.get("id"),
            "title": it.get("title") or it.get("name") or "",
            "original_title": it.get("original_title") or it.get("original_name") or "",
            "year": (it.get("release_date") or it.get("first_air_date") or "")[:4],
            "media_type": mt,
            "rating": round(float(it.get("vote_average") or 0), 1),
            "poster": poster_url,
            "proxy_poster": "/api/poster?url=" + quote(poster_url, safe="") if poster_url else "",
            "overview": (it.get("overview") or "")[:150],
            "search_url": "/?" + urlencode({"tmdb_id": it.get("id"), "media_type": mt}),
        })
    return out, ""


DOUBAN_LISTS = {
    "douban_movie_top": ("subjects", "movie", "豆瓣高分"),
    "douban_movie_hot": ("subjects", "movie", "热门"),
    "douban_tv_hot": ("subjects", "tv", "热门"),
    "douban_tv_domestic": ("subjects", "tv", "国产剧"),
    "douban_tv_korean": ("subjects", "tv", "韩剧"),
}


def douban_rankings(kind: str = "douban_movie_top", limit: int = 24) -> tuple[list[dict], str]:
    """豆瓣榜单。使用豆瓣公开网页接口，不依赖额外 API Key。"""
    mode, media_type, tag = DOUBAN_LISTS.get(kind, DOUBAN_LISTS["douban_movie_top"])
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://movie.douban.com/",
        "Accept": "application/json, text/plain, */*",
    }
    cfg = _cfg()
    proxy = (cfg.get("tmdb_proxy") or cfg.get("tg_proxy") or "").strip()
    try:
        kwargs = {"timeout": 20, "headers": headers, "follow_redirects": True}
        if proxy:
            try:
                client = httpx.Client(proxy=proxy, **kwargs)
            except TypeError:
                client = httpx.Client(proxies=proxy, **kwargs)
        else:
            client = httpx.Client(**kwargs)
        with client as c:
            response = c.get(
                "https://movie.douban.com/j/search_subjects",
                params={
                    "type": media_type, "tag": tag,
                    "sort": "rank" if tag == "豆瓣高分" else "recommend",
                    "page_limit": max(1, limit), "page_start": 0,
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        return [], f"豆瓣连接失败 · {type(exc).__name__}: {exc}"

    rows = data if isinstance(data, list) else (data.get("subjects") or [])
    current_year = date.today().year
    out = []
    for it in rows[:limit]:
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        release_date = str(it.get("release_date") or "")
        year = release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else ""
        if year and not (1900 <= int(year) <= current_year + 1):
            year = ""
        rating = it.get("score") or it.get("rate") or 0
        try:
            rating = round(float(rating), 1)
        except Exception:
            rating = 0
        poster = it.get("cover_url") or it.get("cover") or ""
        proxy_poster = "/api/poster?url=" + quote(str(poster), safe="") if poster else ""
        out.append({
            "tmdb_id": None,
            "douban_id": str(it.get("id") or ""),
            "title": title,
            "original_title": "",
            "year": year,
            "media_type": media_type,
            "rating": rating,
            "poster": poster,
            "proxy_poster": proxy_poster,
            "overview": "",
            "search_url": "/?q=" + quote(title),
        })
    return out, ""


def season_episode_count(tmdb_id: int | str, season: int) -> int:
    """返回 TMDB 某季总集数；失败时返回 0。"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key or not season:
        return 0
    data, _err = _get(
        f"tv/{int(tmdb_id)}/season/{int(season)}",
        {"api_key": key, "language": cfg.get("tmdb_language", "zh-CN")},
    )
    if not data:
        return 0
    return len(data.get("episodes") or [])


def check() -> tuple[bool, str]:
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return False, "未填写 TMDB API Key"
    data, err = _get("configuration", {"api_key": key})
    if data is None:
        return False, f"连接失败 · {err}"
    img = (data.get("images") or {}).get("secure_base_url", "")
    return True, f"连接正常 {img}".strip()

