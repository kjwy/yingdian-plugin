"""影癫插件 Web 服务"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

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


@app.get("/rankings")
def rankings_page(request: Request, kind: str = "trending", source: str = "tmdb"):
    source = source if source in ("tmdb", "douban") else "tmdb"
    if source == "douban":
        items, err = tmdb.douban_rankings(kind, limit=24)
    else:
        items, err = tmdb.rankings(kind, limit=24)
    tmdb_labels = {
        "trending": "本周热门", "movie_popular": "电影热门", "movie_top": "电影高分",
        "movie_now": "正在上映", "tv_popular": "剧集热门", "tv_top": "剧集高分",
    }
    douban_labels = {
        "douban_movie_top": "豆瓣高分电影", "douban_movie_hot": "豆瓣热门电影",
        "douban_tv_hot": "豆瓣热门剧集", "douban_tv_domestic": "国产剧热门",
        "douban_tv_korean": "韩剧热门",
    }
    labels = douban_labels if source == "douban" else tmdb_labels
    if source == "tmdb":
        kinds = [
            ("trending", "本周热门"), ("movie_popular", "电影热门"),
            ("movie_top", "电影高分"), ("tv_popular", "剧集热门"), ("tv_top", "剧集高分"),
        ]
    else:
        kinds = [
            ("douban_movie_top", "豆瓣高分"), ("douban_movie_hot", "热门电影"),
            ("douban_tv_hot", "热门剧集"), ("douban_tv_domestic", "国产剧"),
            ("douban_tv_korean", "韩剧"),
        ]
    default_kind = kinds[0][0]
    if kind not in {key for key, _ in kinds}:
        kind = default_kind
        if source == "douban":
            items, err = tmdb.douban_rankings(kind, limit=24)
        else:
            items, err = tmdb.rankings(kind, limit=24)
    return render(request, "rankings.html", {
        "items": items, "err": err, "kind": kind, "label": labels.get(kind, "榜单"),
        "kinds": kinds, "source": source,
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
        ("pending_unlock_hours", int),
    ]:
        if key in form and str(form.get(key)).strip():
            try:
                cfg[key] = cast(str(form.get(key)).strip())
            except Exception:
                pass
    save_config(cfg)
    library.clear_cache()
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/subs")
def subs_page(request: Request):
    cfg = load_config()
    return render(request, "subs.html", {"cfg": cfg, "subs": store.list_subscriptions()})


@app.post("/subs/add")
def subs_add(title: str = Form(""), tmdb_id: str = Form(...), media_type: str = Form("movie"), season: int = Form(0)):
    store.add_subscription(title.strip() or f"TMDB {tmdb_id}", tmdb_id.strip(), media_type, int(season or 0))
    return RedirectResponse("/subs", status_code=303)


@app.post("/subs/{sid}/delete")
def subs_delete(sid: int):
    store.delete_subscription(sid)
    return RedirectResponse("/subs", status_code=303)


@app.post("/subs/{sid}/toggle")
def subs_toggle(sid: int, enabled: str = Form("0")):
    store.toggle_subscription(sid, enabled == "1")
    return RedirectResponse("/subs", status_code=303)


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

