"""影癫插件 Web 服务"""
from __future__ import annotations

import calendar as calendar_module
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__, library, scheduler, service, store, tmdb
from .config import load_config, mask_secret, save_config
from .dian115 import client_status

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="影癫插件", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    """PWA 清单：让 iOS/Android 能「添加到主屏幕」并显示图标"""
    from fastapi.responses import JSONResponse

    data = {
        "name": "影癫插件 for Symedia",
        "short_name": "影癫插件",
        "description": "影癫签到、订阅搜索、自动解锁与 Symedia 转存",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0e1117",
        "theme_color": "#8b5cf6",
        "lang": "zh-CN",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "any"},
        ],
    }
    return JSONResponse(data, media_type="application/manifest+json")


@app.get("/api/poster", include_in_schema=False)
def poster_proxy(url: str):
    """代理豆瓣 / TMDB 海报，避免浏览器防盗链导致图片空白。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = (
        host.endswith(".doubanio.com")
        or host == "image.tmdb.org"
    )
    if parsed.scheme not in ("http", "https") or not allowed:
        return Response(status_code=400)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://movie.douban.com/"}
    try:
        import httpx

        with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as client:
            remote = client.get(url)
            remote.raise_for_status()
        return Response(
            content=remote.content,
            media_type=remote.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception:
        return Response(status_code=502)


def render(request: Request, name: str, ctx: dict | None = None):
    cfg = load_config()
    base = {
        "request": request,
        "status": client_status(),
        "checkin_ready": not store.has_checked_in(),
        "app_version": __version__,
        "site_name": "影癫插件",
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, name, base)


# ---------- 页面 ----------
@app.get("/")
def search_page(request: Request):
    """首页：搜索并转存"""
    return render(request, "search.html")


RANK_FILTERS = {
    "media_type": [("movie", "电影"), ("tv", "电视剧")],
    "sort": [("default", "综合排序"), ("latest", "最新上映"), ("hot", "近期热门"), ("rating", "高分优先")],
    "year": [("all", "全部")] + [(str(date.today().year - i), str(date.today().year - i)) for i in range(6)]
            + [("2020s", "2020年代"), ("2010s", "2010年代"), ("2000s", "2000年代"),
               ("1990s", "90年代"), ("1980s", "80年代")],
    "region": [("all", "全部"), ("zh", "华语"), ("en", "欧美"), ("ko", "韩国"), ("ja", "日本"),
               ("hk", "中国香港"), ("tw", "中国台湾"), ("uk", "英国"), ("fr", "法国"),
               ("de", "德国"), ("in", "印度")],
    "genre": [("all", "全部"), ("comedy", "喜剧"), ("romance", "爱情"), ("action", "动作"),
              ("scifi", "科幻"), ("animation", "动画"), ("mystery", "悬疑"), ("crime", "犯罪"),
              ("thriller", "惊悚"), ("adventure", "冒险"), ("music", "音乐"),
              ("history", "历史"), ("fantasy", "奇幻"), ("horror", "恐怖"),
              ("war", "战争"), ("documentary", "纪录片"), ("drama", "剧情")],
    "status": [("all", "全部"), ("in_library", "已入库"), ("not_in_library", "未入库")],
}


def _ranking_filter_groups(source: str, kind: str, current: dict, doulist_id: str = "") -> list[dict]:
    groups = []
    for name, choices in RANK_FILTERS.items():
        links = []
        for value, label in choices:
            params = {
                "source": source, "kind": kind,
                "media_type": current.get("media_type", "movie"),
                "sort": current.get("sort", "default"),
                "year": current.get("year", "all"),
                "region": current.get("region", "all"),
                "genre": current.get("genre", "all"),
                "status": current.get("status", "all"),
                "doulist_id": doulist_id,
            }
            params[name] = value
            links.append({"value": value, "label": label, "active": current.get(name, "") == value,
                          "href": "/rankings?" + urlencode(params)})
        groups.append({"name": name, "label": {
            "media_type": "类型", "sort": "排序", "year": "年代", "region": "地区",
            "genre": "风格", "status": "状态",
        }[name], "choices": links})
    return groups


def _enrich_ranking_library(items: list[dict]) -> list[dict]:
    if not items:
        return items

    def work(item: dict) -> dict:
        tmdb_id = item.get("tmdb_id")
        media_type = item.get("media_type") or "movie"
        if not tmdb_id and item.get("title"):
            found, _ = tmdb.search_ex(item["title"], media_type, limit=1)
            if found:
                tmdb_id = found[0]["tmdb_id"]
                item["tmdb_id"] = tmdb_id
                item["search_url"] = "/?" + urlencode({"tmdb_id": tmdb_id, "media_type": media_type})
        if tmdb_id:
            quick = library.quick_status(tmdb_id, media_type)
            item["library_checked"] = quick.get("checked", False)
            item["library_exists"] = quick.get("exists", False)
        return item

    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(work, items))


def _load_ranking_items(
    source: str,
    kind: str,
    media_type: str,
    sort: str,
    year: str,
    region: str,
    genre: str,
    status: str,
    doulist_id: str = "",
    page: int = 1,
) -> tuple[list[dict], str, bool]:
    if source == "tmdb":
        items, err = tmdb.discover_rankings(media_type, sort, year, region, genre, limit=24, page=page)
    elif source == "douban":
        items, err = tmdb.douban_discover(media_type, sort, year, region, genre, limit=24, page=page)
    elif source == "douban_rank":
        items, err = tmdb.douban_rankings(kind, limit=24, page=page)
    else:
        items, err = tmdb.douban_doulist(doulist_id, limit=24)
    raw_count = len(items)
    items = _enrich_ranking_library(items)
    if status == "in_library":
        items = [x for x in items if x.get("library_exists")]
    elif status == "not_in_library":
        items = [x for x in items if x.get("library_checked") and not x.get("library_exists")]
    has_more = source != "douban_list" and raw_count > 0
    return items, err, has_more


@app.get("/rankings")
def rankings_page(
    request: Request,
    kind: str = "trending",
    source: str = "tmdb",
    media_type: str = "movie",
    sort: str = "default",
    year: str = "all",
    region: str = "all",
    genre: str = "all",
    status: str = "all",
    doulist_id: str = "",
    page: int = 1,
):
    source = source if source in ("tmdb", "douban", "douban_rank", "douban_list") else "tmdb"
    media_type = media_type if media_type in ("movie", "tv") else "movie"
    current = {
        "media_type": media_type, "sort": sort, "year": year,
        "region": region, "genre": genre, "status": status,
    }
    page = max(1, int(page or 1))
    items, err, has_more = _load_ranking_items(
        source, kind, media_type, sort, year, region, genre, status, doulist_id, page,
    )

    labels = {
        "tmdb": "TMDB 发现", "douban": "豆瓣发现",
        "douban_rank": "豆瓣榜单", "douban_list": "豆瓣片单",
    }
    rank_kinds = [
        ("douban_movie_top", "豆瓣高分"), ("douban_movie_hot", "热门电影"),
        ("douban_tv_hot", "热门剧集"), ("douban_tv_domestic", "国产剧"),
        ("douban_tv_korean", "韩剧"),
    ]
    return render(request, "rankings.html", {
        "items": items,
        "err": err,
        "kind": kind,
        "label": labels[source],
        "source": source,
        "rank_kinds": rank_kinds,
        "filter_groups": _ranking_filter_groups(source, kind, current, doulist_id),
        "current": current,
        "doulist_id": doulist_id,
        "page": page,
        "has_more": has_more,
    })


@app.get("/dashboard")
def dashboard(request: Request):
    cfg = load_config()
    return render(
        request,
        "dashboard.html",
        {
            "cfg": cfg,
            "checkins": store.list_checkins(10),
            "unlocks": store.list_unlocks(10),
            "subs": store.list_subscriptions(),
        },
    )


@app.get("/settings")
def settings_page(request: Request):
    cfg = load_config()
    safe = dict(cfg)
    safe["dian_api_key_masked"] = mask_secret(cfg.get("dian_api_key", ""))
    safe["tg_bot_token_masked"] = mask_secret(cfg.get("tg_bot_token", ""))
    safe["tmdb_api_key_masked"] = mask_secret(cfg.get("tmdb_api_key", ""))
    safe["emby_api_key_masked"] = mask_secret(cfg.get("emby_api_key", ""))
    return render(request, "settings.html", {"cfg": safe})


@app.post("/settings")
async def settings_save(request: Request):
    cfg = load_config()
    form = await request.form()
    for key in [
        "mode", "cdp_host", "dian_base_url", "dian_api_key", "checkin_mode", "tg_bot_token", "tg_chat_id",
        "tg_template", "tg_proxy", "tg_api_id", "tg_api_hash", "tg_phone", "dian_password", "d115_cookie", "d115_cid", "dian_email", "tmdb_api_key", "tmdb_proxy", "tmdb_api_base", "tmdb_image_base", "timezone", "movie_filter", "tv_filter",
        "emby_host", "emby_api_key",
    ]:
        if key in form:
            val = str(form.get(key) or "").strip()
            # 密钥类字段：留空或仍是掩码时，保持原值不变（避免误清空）
            if key in ("dian_api_key", "tg_bot_token", "tmdb_api_key", "emby_api_key"):
                if (not val) or val.endswith("***"):
                    continue
            cfg[key] = val
    for key in [
        "d115_enabled", "tg_push_enabled", "checkin_enabled", "checkin_notify",
        "only_free", "unlock_official", "api_search_enabled", "rss_enabled",
        "expire_remind_enabled", "emby_enabled", "skip_in_library",
    ]:
        cfg[key] = key in form
    for key, cast in [
        ("max_unlock_points", int), ("unlock_rate_per_minute", int), ("max_unlock_points_sub", int),
        ("checkin_window_start", int), ("checkin_window_end", int), ("rss_interval_minutes", int),
        ("expire_remind_hours", int), ("cdp_port", int),
        ("pending_unlock_hours", int), ("subs_interval_minutes", int),
    ]:
        if key in form and str(form.get(key)).strip():
            try:
                cfg[key] = cast(str(form.get(key)).strip())
            except Exception:
                pass
    save_config(cfg)
    library.clear_cache()
    return RedirectResponse("/settings?saved=1", status_code=303)


def _subscription_calendar(month: str) -> tuple[dict, str, str]:
    today = date.today()
    try:
        year, month_no = (int(x) for x in month.split("-", 1))
        current = date(year, month_no, 1)
    except Exception:
        current = today.replace(day=1)
    prev_month = (current.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
    events = []
    for sub in store.list_subscriptions():
        if sub.get("media_type") != "tv" or not sub.get("tmdb_id"):
            continue
        for episode in tmdb.season_episodes(sub["tmdb_id"], int(sub.get("season") or 0)):
            air_date = episode.get("air_date") or ""
            if not air_date.startswith(current.strftime("%Y-%m")):
                continue
            events.append({
                "date": air_date,
                "title": sub.get("title") or "",
                "episode": episode.get("episode") or 0,
                "name": episode.get("name") or "",
                "subscription_id": sub.get("id"),
            })
    events.sort(key=lambda x: (x["date"], x["title"], x["episode"]))
    by_day = {}
    for event in events:
        try:
            day = int(event["date"][8:10])
        except Exception:
            continue
        by_day.setdefault(day, []).append(event)
    weeks = []
    for week in calendar_module.Calendar(firstweekday=0).monthdatescalendar(current.year, current.month):
        row = []
        for day in week:
            row.append({
                "day": day.day,
                "in_month": day.month == current.month,
                "today": day == today,
                "events": by_day.get(day.day, []) if day.month == current.month else [],
            })
        weeks.append(row)
    return {
        "month": current.strftime("%Y-%m"),
        "title": current.strftime("%Y年%m月"),
        "weeks": weeks,
        "events": events,
        "prev": prev_month,
        "next": next_month,
    }, prev_month, next_month


@app.get("/subs")
def subs_page(
    request: Request,
    tab: str = "tv",
    status: str = "all",
    cloud: str = "all",
    update: str = "all",
    q: str = "",
    month: str = "",
):
    cfg = load_config()
    tab = tab if tab in ("movie", "tv", "calendar", "rules", "config") else "tv"
    all_subs = store.list_subscriptions()
    counts = {
        "movie": sum(1 for s in all_subs if s.get("media_type") == "movie"),
        "tv": sum(1 for s in all_subs if s.get("media_type") == "tv"),
        "calendar": sum(1 for s in all_subs if s.get("media_type") == "tv"),
    }
    subs = all_subs
    if tab in ("movie", "tv"):
        subs = [s for s in subs if s.get("media_type") == tab]
        if status == "incomplete":
            subs = [s for s in subs if not s.get("completed")]
        elif status == "completed":
            subs = [s for s in subs if s.get("completed")]
        if cloud != "all":
            subs = [s for s in subs if (s.get("cloud_type") or "115") == cloud]
        if update != "all":
            now = datetime.now()
            days = 1 if update == "today" else (3 if update == "3d" else 7)
            since = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            subs = [
                s for s in subs
                if (s.get("last_checked_at") or s.get("created_at") or "") >= since
            ]
        if q.strip():
            needle = q.strip().lower()
            subs = [
                s for s in subs
                if needle in (s.get("title") or "").lower()
                or needle in str(s.get("tmdb_id") or "")
            ]
    calendar_data = _subscription_calendar(month)[0] if tab == "calendar" else None
    return render(request, "subs.html", {
        "cfg": cfg,
        "subs": subs,
        "all_subs": all_subs,
        "counts": counts,
        "tab": tab,
        "status": status,
        "cloud": cloud,
        "update": update,
        "q": q,
        "calendar": calendar_data,
    })


@app.post("/subs/add")
def subs_add(
    title: str = Form(""),
    tmdb_id: str = Form(...),
    media_type: str = Form("movie"),
    season: int = Form(0),
    start_episode: int = Form(1),
    total_episodes: int = Form(0),
    cloud_type: str = Form("115"),
    subscription_url: str = Form(""),
):
    store.add_subscription(
        title.strip() or f"TMDB {tmdb_id}",
        tmdb_id.strip(),
        media_type,
        int(season or 0),
        start_episode=int(start_episode or 1),
        total_episodes=int(total_episodes or 0),
        cloud_type=cloud_type,
        subscription_url=subscription_url.strip(),
    )
    return RedirectResponse(f"/subs?tab={media_type}", status_code=303)


@app.post("/subs/{sid}/edit")
def subs_edit(
    sid: int,
    title: str = Form(""),
    tmdb_id: str = Form(...),
    media_type: str = Form("movie"),
    season: int = Form(0),
    start_episode: int = Form(1),
    total_episodes: int = Form(0),
    cloud_type: str = Form("115"),
    subscription_url: str = Form(""),
):
    store.update_subscription(
        sid,
        title.strip() or f"TMDB {tmdb_id}",
        tmdb_id.strip(),
        media_type,
        int(season or 0),
        int(start_episode or 1),
        int(total_episodes or 0),
        cloud_type,
        subscription_url.strip(),
    )
    return RedirectResponse(f"/subs?tab={media_type}", status_code=303)


@app.post("/subs/{sid}/delete")
def subs_delete(sid: int):
    store.delete_subscription(sid)
    return RedirectResponse("/subs", status_code=303)


@app.post("/subs/{sid}/toggle")
def subs_toggle(sid: int, enabled: str = Form("0")):
    store.toggle_subscription(sid, enabled == "1")
    return RedirectResponse("/subs", status_code=303)


@app.post("/subs/{sid}/cloud")
def subs_cloud(sid: int, cloud_type: str = Form("115")):
    store.set_subscription_cloud(sid, cloud_type)
    return RedirectResponse("/subs", status_code=303)


@app.post("/subs/rules")
async def subs_rules(request: Request):
    cfg = load_config()
    form = await request.form()
    cfg["movie_filter"] = str(form.get("movie_filter") or "").strip()
    cfg["tv_filter"] = str(form.get("tv_filter") or "").strip()
    cfg["max_unlock_points_sub"] = int(form.get("max_unlock_points_sub") or 20)
    cfg["only_free"] = "only_free" in form
    save_config(cfg)
    return RedirectResponse("/subs?tab=rules&saved=1", status_code=303)


@app.post("/subs/config")
async def subs_config(request: Request):
    cfg = load_config()
    form = await request.form()
    cfg["skip_in_library"] = "skip_in_library" in form
    cfg["pending_unlock_hours"] = int(form.get("pending_unlock_hours") or 24)
    cfg["subs_interval_minutes"] = int(form.get("subs_interval_minutes") or 30)
    save_config(cfg)
    return RedirectResponse("/subs?tab=config&saved=1", status_code=303)


@app.get("/logs")
def logs_page(request: Request):
    return render(request, "logs.html", {"checkins": store.list_checkins(50), "unlocks": store.list_unlocks(100)})


# ---------- API ----------
@app.get("/api/status")
def api_status():
    return {"ok": True, "client": client_status(), "checked_in": store.has_checked_in()}


@app.post("/api/checkin")
def api_checkin(force: bool = False):
    return service.do_checkin(force=force)


@app.post("/api/tmdb/check")
def api_tmdb_check():
    """诊断：验证 TMDB Key 与网络连通性"""
    ok, msg = tmdb.check()
    return {"ok": ok, "message": msg}


@app.post("/api/tmdb/search")
def api_tmdb_search(payload: dict):
    q = (payload or {}).get("q", "")
    mt = (payload or {}).get("media_type", "movie")
    items, err = tmdb.search_ex(q, mt)
    return {"ok": not err, "items": items, "message": err}


@app.get("/api/tmdb/detail")
def api_tmdb_detail(tmdb_id: str, media_type: str = "movie", season: int = 1):
    detail = tmdb.details(tmdb_id, media_type)
    total = tmdb.season_episode_count(tmdb_id, season) if media_type == "tv" else 0
    return {"ok": bool(detail), "item": detail, "total_episodes": total}


@app.post("/api/search")
def api_search(payload: dict):
    """只输入 TMDB ID 或片名即可，类型自动识别"""
    payload = payload or {}
    raw = str(payload.get("tmdb_id") or payload.get("q") or "").strip()
    season = int(payload.get("season") or 0)
    if not raw:
        return {"ok": False, "message": "请输入 TMDB ID 或片名", "items": []}

    media_type = (payload.get("media_type") or "").strip()
    resolved_title = ""

    if raw.isdigit():
        tid = int(raw)
        # 类型未知：先试电影，再试剧集
        if media_type in ("movie", "tv"):
            order = [media_type]
        else:
            order = ["movie", "tv"]
        last_msg = ""
        for mt in order:
            data = service.search_shares(tid, mt, season)
            if data.get("ok") and data.get("items"):
                data["tmdb_id"] = tid
                data["media_type"] = mt
                data["media"] = tmdb.details(tid, mt)
                return data
            last_msg = data.get("message") or last_msg
        return {"ok": False, "message": last_msg or "没找到该 TMDB ID 的资源", "items": []}

    # 片名：多类型搜索
    if media_type in ("movie", "tv"):
        found, err = tmdb.search_ex(raw, media_type, limit=8)
    else:
        found, err = tmdb.search_multi_ex(raw, limit=8)
    if err:
        return {"ok": False, "message": f"TMDB 不可用 · {err} · 可直接填 TMDB ID", "items": []}
    if not found:
        return {"ok": False, "message": f"没搜到「{raw}」· 换个名字或直接填 TMDB ID", "items": []}

    last_msg = ""
    for item in found:
        data = service.search_shares(item["tmdb_id"], item["media_type"], season)
        if data.get("ok") and data.get("items"):
            data["tmdb_id"] = item["tmdb_id"]
            data["media_type"] = item["media_type"]
            data["resolved_title"] = f"{item['title']} {item.get('year','')}".strip()
            data["media"] = item
            return data
        last_msg = data.get("message") or last_msg
    return {"ok": False, "message": f"「{raw}」在影癫没有可解锁资源", "items": []}


@app.post("/api/unlock")
def api_unlock(payload: dict):
    payload = payload or {}
    if not payload.get("share_id"):
        return {"ok": False, "message": "缺少 share_id"}
    return service.unlock_share(
        payload,
        title=payload.get("title", ""),
        media_type=payload.get("media_type", ""),
        tmdb_id=payload.get("tmdb_id"),
        season=int(payload.get("season") or payload.get("season_number") or 0),
    )


@app.post("/api/subs/run")
def api_subs_run():
    return service.run_subscription_search()


@app.post("/api/rss/poll")
def api_rss_poll():
    return service.rss_poll()


@app.get("/api/rankings")
def api_rankings(
    source: str = "tmdb",
    kind: str = "trending",
    media_type: str = "movie",
    sort: str = "default",
    year: str = "all",
    region: str = "all",
    genre: str = "all",
    status: str = "all",
    doulist_id: str = "",
    page: int = 1,
):
    source = source if source in ("tmdb", "douban", "douban_rank", "douban_list") else "tmdb"
    media_type = media_type if media_type in ("movie", "tv") else "movie"
    items, err, has_more = _load_ranking_items(
        source, kind, media_type, sort, year, region, genre, status,
        doulist_id, max(1, int(page or 1)),
    )
    return {"ok": not bool(err), "items": items, "message": err, "has_more": has_more, "page": page}


@app.post("/api/client/check")
def api_client_check():
    """诊断当前运行模式是否可用"""
    st = client_status()
    return {"ok": bool(st.get("ready")), "message": st.get("message", ""), "mode": st.get("mode")}


@app.post("/api/emby/check")
def api_emby_check():
    ok, msg = library.check()
    return {"ok": ok, "message": msg}


@app.get("/api/library/status")
def api_library_status(tmdb_id: str, media_type: str = "movie", season: int = 0):
    return library.status(tmdb_id, media_type, season)


@app.get("/api/115/folders")
def api_115_folders(cid: str = "0"):
    from . import transfer115

    ok, folders, msg = transfer115.list_folders(cid)
    return {"ok": ok, "folders": folders, "message": msg}


@app.post("/api/115/check")
def api_115_check():
    from . import transfer115

    ok, msg = transfer115.check()
    return {"ok": ok, "message": msg}


@app.get("/api/tg/userbot/status")
def api_userbot_status():
    from . import userbot

    return userbot.status()


@app.post("/api/tg/userbot/start")
def api_userbot_start(payload: dict):
    from . import userbot

    return userbot.start_login((payload or {}).get("phone", ""))


@app.post("/api/tg/userbot/verify")
def api_userbot_verify(payload: dict):
    from . import userbot

    payload = payload or {}
    return userbot.verify_login(payload.get("phone", ""), payload.get("code", ""), payload.get("password", ""))


@app.post("/api/telegram/check")
def api_telegram_check():
    """诊断：只调用 getMe，不发消息，验证 token 与网络"""
    from . import notify

    ok, msg = notify.check()
    return {"ok": ok, "message": msg}


@app.post("/api/notify/test")
def api_notify_test():
    from . import notify

    ok, msg = notify.send("【影癫插件】Telegram 测试消息 ✅ 如果你看到这条，说明推送配置正确")
    return {"ok": ok, "message": msg}

