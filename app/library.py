"""Emby 入库检测：判断电影是否已入库，以及剧集已入库到哪些集。"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx

from .config import load_config
from .scoring import format_episode_numbers

_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.RLock()
_CACHE_TTL = 120.0


def _cfg() -> dict:
    return load_config()


def _headers(cfg: dict) -> dict:
    return {
        "X-Emby-Token": str(cfg.get("emby_api_key") or "").strip(),
        "Accept": "application/json",
    }


def _api_get(path: str, params: dict | None = None, cfg: dict | None = None) -> tuple[dict | None, str]:
    cfg = cfg or _cfg()
    base = str(cfg.get("emby_host") or "").strip().rstrip("/")
    key = str(cfg.get("emby_api_key") or "").strip()
    if not base:
        return None, "未填写 Emby 地址"
    if not key:
        return None, "未填写 Emby API Key"
    try:
        with httpx.Client(timeout=20, headers=_headers(cfg), follow_redirects=True) as client:
            response = client.get(f"{base}{path}", params=params or {})
            if response.status_code == 401:
                return None, "Emby API Key 无效"
            response.raise_for_status()
            return response.json(), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def check() -> tuple[bool, str]:
    cfg = _cfg()
    if not cfg.get("emby_enabled"):
        return False, "入库检测未启用"
    data, err = _api_get("/emby/System/Info", cfg=cfg)
    if data is None:
        return False, err
    name = data.get("ServerName") or "Emby"
    version = data.get("Version") or ""
    return True, f"{name} {version}".strip()


def _find_item(tmdb_id: str | int, media_type: str, cfg: dict) -> tuple[dict | None, str]:
    item_type = "Series" if media_type == "tv" else "Movie"
    data, err = _api_get(
        "/emby/Items",
        {
            "Recursive": "true",
            "IncludeItemTypes": item_type,
            "Fields": "ProviderIds,Path,ProductionYear,DateCreated",
            "AnyProviderIdEquals": f"tmdb.{int(tmdb_id)}",
            "Limit": 20,
        },
        cfg=cfg,
    )
    if data is None:
        return None, err
    items = data.get("Items") or []
    for item in items:
        provider_ids = item.get("ProviderIds") or {}
        if str(provider_ids.get("Tmdb") or "") == str(tmdb_id) and item.get("Type") == item_type:
            return item, ""
    return None, ""


def _series_episodes(series_id: str, cfg: dict) -> tuple[list[dict], str]:
    data, err = _api_get(
        f"/emby/Shows/{series_id}/Episodes",
        {
            "Fields": "Path,ProviderIds,ParentIndexNumber,IndexNumber",
            "EnableImages": "false",
        },
        cfg=cfg,
    )
    if data is None:
        return [], err
    return data.get("Items") or [], ""


def status(tmdb_id: str | int, media_type: str = "movie", season: int = 0) -> dict:
    """返回媒体库状态；未启用或未配置时 checked=False，不影响原有搜索。"""
    cfg = _cfg()
    if not cfg.get("emby_enabled"):
        return {"checked": False, "exists": False, "message": "入库检测未启用"}
    if not cfg.get("emby_host") or not cfg.get("emby_api_key"):
        return {"checked": False, "exists": False, "message": "未配置 Emby"}

    cache_key = (str(tmdb_id), media_type, int(season or 0))
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1])

    item, err = _find_item(tmdb_id, media_type, cfg)
    if err:
        return {"checked": False, "exists": False, "message": err}
    if not item:
        result = {
            "checked": True,
            "exists": False,
            "media_type": media_type,
            "tmdb_id": str(tmdb_id),
            "message": "未入库",
        }
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now + _CACHE_TTL, result)
        return result

    result = {
        "checked": True,
        "exists": True,
        "media_type": media_type,
        "tmdb_id": str(tmdb_id),
        "item_id": str(item.get("Id") or ""),
        "media_title": item.get("Name") or "",
        "path": item.get("Path") or "",
        "message": "已入库",
    }
    if media_type != "tv":
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now + _CACHE_TTL, result)
        return result

    episodes, err = _series_episodes(result["item_id"], cfg)
    if err:
        result["message"] = f"已入库，读取集数失败：{err}"
        return result

    by_season: dict[int, list[int]] = {}
    files: dict[str, dict[str, str]] = {}
    for episode in episodes:
        try:
            season_no = int(episode.get("ParentIndexNumber") or 0)
            episode_no = int(episode.get("IndexNumber") or 0)
        except Exception:
            continue
        if episode_no <= 0:
            continue
        by_season.setdefault(season_no, []).append(episode_no)
        path = str(episode.get("Path") or "")
        if path:
            files.setdefault(str(season_no), {})[str(episode_no)] = Path(path).name

    seasons: dict[str, dict] = {}
    for season_no, numbers in sorted(by_season.items()):
        unique = sorted(set(numbers))
        seasons[str(season_no)] = {
            "available": unique,
            "available_text": format_episode_numbers(unique),
            "episode_count": len(unique),
            "files": files.get(str(season_no), {}),
        }

    selected = int(season or 0)
    if not selected:
        selected = next((x for x in sorted(by_season) if x > 0), 0)
    selected_numbers = seasons.get(str(selected), {}).get("available") if selected else []
    if not selected_numbers:
        selected_numbers = sorted({x for values in by_season.values() for x in values})

    total_count = 0
    if selected:
        try:
            from . import tmdb

            total_count = tmdb.season_episode_count(int(tmdb_id), selected)
        except Exception:
            total_count = 0
        if total_count:
            season_data = seasons.setdefault(str(selected), {
                "available": [],
                "available_text": "",
                "episode_count": 0,
                "files": {},
            })
            season_data["total_count"] = total_count
            season_data["missing"] = [x for x in range(1, total_count + 1) if x not in set(season_data["available"])]
            season_data["missing_text"] = format_episode_numbers(season_data["missing"])

    result.update({
        "selected_season": selected,
        "seasons": seasons,
        "available": selected_numbers,
        "available_text": format_episode_numbers(selected_numbers),
        "total_count": total_count,
        "missing": [x for x in range(1, total_count + 1) if x not in set(selected_numbers)] if total_count else [],
    })
    result["missing_text"] = format_episode_numbers(result["missing"])
    result["complete"] = bool(total_count and not result["missing"])
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now + _CACHE_TTL, dict(result))
    return result


def quick_status(tmdb_id: str | int, media_type: str = "movie") -> dict:
    """榜单列表专用：只判断是否存在，不读取分集。"""
    cfg = _cfg()
    if not cfg.get("emby_enabled") or not cfg.get("emby_host") or not cfg.get("emby_api_key"):
        return {"checked": False, "exists": False}
    key = ("quick", str(tmdb_id), media_type)
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > now:
            return dict(cached[1])
    item, err = _find_item(tmdb_id, media_type, cfg)
    result = {
        "checked": not bool(err),
        "exists": bool(item),
        "message": err or ("已入库" if item else "未入库"),
    }
    with _CACHE_LOCK:
        _CACHE[key] = (now + _CACHE_TTL, dict(result))
    return result


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
