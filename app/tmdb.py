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


def rankings(kind: str = "trending", limit: int = 20, page: int = 1) -> tuple[list[dict], str]:
    """TMDB 榜单"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return [], "未填写 TMDB API Key"
    path, _label = RANKING_PATHS.get(kind, RANKING_PATHS["trending"])
    data, err = _get(path, {
        "api_key": key, "language": cfg.get("tmdb_language", "zh-CN"),
        "page": max(1, int(page)),
    })
    if data is None:
        return [], f"TMDB 连接失败 · {err}"
    out = []
    for it in (data.get("results") or [])[:limit]:
        mt = it.get("media_type") or ("tv" if path.startswith("tv/") else "movie")
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

TMDB_MOVIE_GENRES = {
    "action": "28", "adventure": "12", "animation": "16", "comedy": "35",
    "crime": "80", "documentary": "99", "drama": "18", "family": "10751",
    "fantasy": "14", "history": "36", "horror": "27", "music": "10402",
    "mystery": "9648", "romance": "10749", "scifi": "878", "thriller": "53",
    "war": "10752", "western": "37",
}
TMDB_TV_GENRES = {
    "action": "10759", "animation": "16", "comedy": "35", "crime": "80",
    "documentary": "99", "drama": "18", "family": "10751", "mystery": "9648",
    "scifi": "10765", "war": "10768", "western": "37",
}
LANGUAGE_MAP = {
    "zh": "zh", "en": "en", "ja": "ja", "ko": "ko", "fr": "fr",
    "de": "de", "es": "es", "it": "it", "ru": "ru", "pt": "pt",
    "ar": "ar", "hi": "hi", "th": "th",
}


def _date_range(year: str) -> tuple[str, str]:
    if not year or year == "all":
        return "", ""
    if year.endswith("s") and year[:-1].isdigit():
        start = int(year[:-1])
        return f"{start}-01-01", f"{start + 9}-12-31"
    if year.isdigit():
        return f"{year}-01-01", f"{year}-12-31"
    return "", ""


def discover_rankings(
    media_type: str = "movie",
    sort: str = "default",
    year: str = "all",
    region: str = "all",
    genre: str = "all",
    limit: int = 24,
    page: int = 1,
) -> tuple[list[dict], str]:
    """带筛选的 TMDB 发现列表。"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key:
        return [], "未填写 TMDB API Key"
    media_type = media_type if media_type in ("movie", "tv") else "movie"
    order = {
        "default": "popularity.desc",
        "hot": "popularity.desc",
        "latest": "primary_release_date.desc" if media_type == "movie" else "first_air_date.desc",
        "rating": "vote_average.desc",
    }.get(sort, "popularity.desc")
    params = {
        "api_key": key,
        "language": cfg.get("tmdb_language", "zh-CN"),
        "page": max(1, int(page)),
        "sort_by": order,
        "include_adult": "false",
    }
    start_date, end_date = _date_range(year)
    if start_date:
        if media_type == "movie":
            params["primary_release_date.gte"] = start_date
            params["primary_release_date.lte"] = end_date
        else:
            params["first_air_date.gte"] = start_date
            params["first_air_date.lte"] = end_date
    if region and region != "all" and region in LANGUAGE_MAP:
        params["with_original_language"] = LANGUAGE_MAP[region]
    genre_map = TMDB_MOVIE_GENRES if media_type == "movie" else TMDB_TV_GENRES
    if genre and genre != "all" and genre in genre_map:
        params["with_genres"] = genre_map[genre]
    if sort == "rating":
        params["vote_count.gte"] = "80"

    data, err = _get(f"discover/{media_type}", params)
    if data is None:
        return [], f"TMDB 连接失败 · {err}"
    out = []
    for it in (data.get("results") or [])[:limit]:
        poster = it.get("poster_path")
        poster_url = f"{_img_base('w342')}{poster}" if poster else ""
        out.append({
            "tmdb_id": it.get("id"),
            "title": it.get("title") or it.get("name") or "",
            "original_title": it.get("original_title") or it.get("original_name") or "",
            "year": (it.get("release_date") or it.get("first_air_date") or "")[:4],
            "media_type": media_type,
            "rating": round(float(it.get("vote_average") or 0), 1),
            "poster": poster_url,
            "proxy_poster": "/api/poster?url=" + quote(poster_url, safe="") if poster_url else "",
            "overview": (it.get("overview") or "")[:150],
            "search_url": "/?" + urlencode({"tmdb_id": it.get("id"), "media_type": media_type}),
        })
    return out, ""


def douban_discover(
    media_type: str = "movie",
    sort: str = "default",
    year: str = "all",
    region: str = "all",
    genre: str = "all",
    limit: int = 24,
    page: int = 1,
) -> tuple[list[dict], str]:
    """带筛选的豆瓣列表。"""
    media_type = media_type if media_type in ("movie", "tv") else "movie"
    tags = []
    if genre and genre != "all":
        tags.append({
            "action": "动作", "comedy": "喜剧", "romance": "爱情", "scifi": "科幻",
            "animation": "动画", "mystery": "悬疑", "crime": "犯罪", "thriller": "惊悚",
            "adventure": "冒险", "music": "音乐", "history": "历史", "fantasy": "奇幻",
            "horror": "恐怖", "war": "战争", "documentary": "纪录片", "drama": "剧情",
        }.get(genre, genre))
    elif region and region != "all":
        tags.append({
            "zh": "华语", "en": "欧美", "ko": "韩国", "ja": "日本",
            "hk": "中国香港", "tw": "中国台湾", "uk": "英国",
            "fr": "法国", "de": "德国", "in": "印度",
        }.get(region, region))
    elif year and year != "all":
        tags.append(year)
    if not tags:
        tags.append("豆瓣高分" if sort == "rating" else "热门")
    sort_value = {"default": "U", "latest": "R", "hot": "T", "rating": "S"}.get(sort, "U")
    cfg = _cfg()
    proxy = (cfg.get("tmdb_proxy") or cfg.get("tg_proxy") or "").strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Referer": "https://movie.douban.com/",
    }
    try:
        kwargs = {"timeout": 20, "headers": headers, "follow_redirects": True}
        try:
            client = httpx.Client(proxy=proxy, **kwargs) if proxy else httpx.Client(**kwargs)
        except TypeError:
            client = httpx.Client(proxies=proxy, **kwargs) if proxy else httpx.Client(**kwargs)
        with client as c:
            response = c.get(
                "https://movie.douban.com/j/search_subjects",
                params={
                    "type": media_type, "tag": ",".join(tags), "sort": sort_value,
                    "page_limit": max(1, limit),
                    "page_start": max(0, (max(1, int(page)) - 1) * limit),
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        return [], f"豆瓣连接失败 · {type(exc).__name__}: {exc}"
    out = []
    for it in (data.get("subjects") or [])[:limit]:
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        poster = it.get("cover") or ""
        rating = it.get("rate") or 0
        try:
            rating = round(float(rating), 1)
        except Exception:
            rating = 0
        out.append({
            "tmdb_id": None,
            "douban_id": str(it.get("id") or ""),
            "title": title,
            "original_title": "",
            "year": year if year.isdigit() else "",
            "media_type": media_type,
            "rating": rating,
            "poster": poster,
            "proxy_poster": "/api/poster?url=" + quote(str(poster), safe="") if poster else "",
            "overview": "",
            "search_url": "/?" + urlencode({"q": title, "media_type": media_type}),
        })
    return out, ""


def douban_doulist(doulist_id: str, limit: int = 24) -> tuple[list[dict], str]:
    """读取公开豆瓣片单页面。"""
    doulist_id = "".join(ch for ch in str(doulist_id or "") if ch.isdigit())
    if not doulist_id:
        return [], "请输入豆瓣片单 ID"
    url = f"https://www.douban.com/doulist/{doulist_id}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Referer": "https://www.douban.com/",
    }
    try:
        with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
    except Exception as exc:  # noqa: BLE001
        return [], f"豆瓣片单读取失败 · {type(exc).__name__}: {exc}"
    import html as html_lib
    import re

    rows = []
    pattern = re.compile(
        r'href="https://movie\.douban\.com/subject/(\d+)/[^"]*"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    for douban_id, raw_title in pattern.findall(html):
        title = html_lib.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        if not title:
            continue
        if any(x["douban_id"] == douban_id for x in rows):
            continue
        rows.append({
            "tmdb_id": None,
            "douban_id": douban_id,
            "title": title,
            "original_title": "",
            "year": "",
            "media_type": "movie",
            "rating": 0,
            "poster": "",
            "proxy_poster": "",
            "overview": "",
            "search_url": "/?" + urlencode({"q": title, "media_type": "movie"}),
        })
        if len(rows) >= limit:
            break
    return (rows, "") if rows else ([], "片单页面没有读取到影片，可能未公开或页面结构已变化")


def douban_rankings(
    kind: str = "douban_movie_top",
    limit: int = 24,
    page: int = 1,
) -> tuple[list[dict], str]:
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
                    "page_limit": max(1, limit),
                    "page_start": max(0, (max(1, int(page)) - 1) * limit),
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
            "search_url": "/?" + urlencode({"q": title, "media_type": media_type}),
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


def season_episodes(tmdb_id: int | str, season: int) -> list[dict]:
    """返回 TMDB 某季分集信息，用于订阅日历。"""
    cfg = _cfg()
    key = (cfg.get("tmdb_api_key") or "").strip()
    if not key or not season:
        return []
    data, _err = _get(
        f"tv/{int(tmdb_id)}/season/{int(season)}",
        {"api_key": key, "language": cfg.get("tmdb_language", "zh-CN")},
    )
    if not data:
        return []
    out = []
    for episode in data.get("episodes") or []:
        out.append({
            "episode": int(episode.get("episode_number") or 0),
            "name": episode.get("name") or "",
            "air_date": episode.get("air_date") or "",
            "overview": episode.get("overview") or "",
        })
    return out


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

