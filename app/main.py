"""影癫插件 Web 服务"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import scheduler, service, store, tmdb
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


app = FastAPI(title="影癫插件", version="0.1.0", lifespan=lifespan)
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


def render(request: Request, name: str, ctx: dict | None = None):
    cfg = load_config()
    base = {
        "request": request,
        "status": client_status(),
        "checkin_ready": not store.has_checked_in(),
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, name, base)


# ---------- 页面 ----------
@app.get("/")
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
    return render(request, "settings.html", {"cfg": safe})


@app.post("/settings")
async def settings_save(request: Request):
    cfg = load_config()
    form = await request.form()
    for key in [
        "dian_base_url", "dian_api_key", "checkin_mode", "tg_bot_token", "tg_chat_id",
        "tg_template", "tg_proxy", "tmdb_api_key", "tmdb_proxy", "tmdb_api_base", "tmdb_image_base", "timezone", "movie_filter", "tv_filter",
    ]:
        if key in form:
            val = str(form.get(key) or "").strip()
            # 密钥类字段：留空或仍是掩码时，保持原值不变（避免误清空）
            if key in ("dian_api_key", "tg_bot_token", "tmdb_api_key"):
                if (not val) or val.endswith("***"):
                    continue
            cfg[key] = val
    for key in ["checkin_enabled", "checkin_notify", "only_free", "unlock_official", "api_search_enabled", "rss_enabled", "mock_mode", "expire_remind_enabled"]:
        cfg[key] = key in form
    for key, cast in [
        ("max_unlock_points", int), ("unlock_rate_per_minute", int), ("max_unlock_points_sub", int),
        ("checkin_window_start", int), ("checkin_window_end", int), ("rss_interval_minutes", int),
        ("expire_remind_hours", int),
    ]:
        if key in form and str(form.get(key)).strip():
            try:
                cfg[key] = cast(str(form.get(key)).strip())
            except Exception:
                pass
    save_config(cfg)
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
    return {"ok": True, "items": tmdb.search(q, mt)}


@app.post("/api/search")
def api_search(payload: dict):
    tmdb_id = (payload or {}).get("tmdb_id")
    if not tmdb_id:
        return {"ok": False, "message": "缺少 tmdb_id", "items": []}
    return service.search_shares(tmdb_id, (payload or {}).get("media_type", "movie"), int((payload or {}).get("season") or 0))


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
    )


@app.post("/api/subs/run")
def api_subs_run():
    return service.run_subscription_search()


@app.post("/api/rss/poll")
def api_rss_poll():
    return service.rss_poll()


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

