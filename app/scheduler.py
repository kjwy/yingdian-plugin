"""定时任务：随机签到、订阅搜索、RSS 轮询"""
from __future__ import annotations

import random
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import service, store
from .config import load_config

_scheduler: BackgroundScheduler | None = None


def _checkin_target() -> str:
    """当天随机签到目标时间（HH:MM）"""
    cfg = load_config()
    today = date.today().isoformat()
    key = f"checkin_target_{today}"
    val = store.kv_get(key)
    if val:
        return val
    start = int(cfg.get("checkin_window_start") or 8)
    end = int(cfg.get("checkin_window_end") or 23)
    if end <= start:
        end = start + 1
    minutes = random.randint(start * 60, end * 60 - 1)
    val = f"{minutes // 60:02d}:{minutes % 60:02d}"
    store.kv_set(key, val)
    return val


def tick_checkin() -> None:
    cfg = load_config()
    if not cfg.get("checkin_enabled"):
        return
    today = date.today().isoformat()
    if store.has_checked_in(today):
        return
    target = _checkin_target()
    now_hm = datetime.now().strftime("%H:%M")
    if now_hm >= target:
        res = service.do_checkin()
        print(f"[checkin] {res.get('message')}")


def tick_subscriptions() -> None:
    try:
        res = service.run_subscription_search()
        done = [r for r in res.get("results", []) if r.get("ok")]
        if done:
            print(f"[subs] 处理 {len(done)} 条订阅")
    except Exception as exc:  # noqa: BLE001
        print(f"[subs] 异常: {exc}")


def tick_rss() -> None:
    cfg = load_config()
    if not cfg.get("rss_enabled"):
        return
    try:
        res = service.rss_poll()
        if res.get("handled"):
            print(f"[rss] 处理 {len(res['handled'])} 条")
    except Exception as exc:  # noqa: BLE001
        print(f"[rss] 异常: {exc}")


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler
    cfg = load_config()
    tz = cfg.get("timezone") or "Asia/Shanghai"
    sch = BackgroundScheduler(timezone=tz)
    sch.add_job(tick_checkin, "interval", minutes=10, id="checkin", replace_existing=True)
    sch.add_job(tick_subscriptions, "interval", minutes=30, id="subs", replace_existing=True)
    sch.add_job(tick_rss, "interval", minutes=int(cfg.get("rss_interval_minutes") or 5), id="rss", replace_existing=True)
    sch.start()
    _scheduler = sch
    return sch


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
