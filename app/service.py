"""业务逻辑：签到、订阅搜索、解锁、推送"""
from __future__ import annotations

import json
import hashlib
import re
from datetime import date, datetime
from typing import Any

from . import library, notify, store
from .config import load_config
from .dian115 import get_client
from .scoring import annotate_library, format_episode_numbers, parse_episode_numbers, rank_shares


def _match_filter(pattern: str, *texts: str) -> bool:
    if not pattern.strip():
        return True
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        return True
    return any(rx.search(t or "") for t in texts)


def do_checkin(force: bool = False) -> dict:
    cfg = load_config()
    today = date.today().isoformat()
    if not force and store.has_checked_in(today):
        return {"ok": False, "message": "今日已签到"}
    client, mode = get_client()
    before = None
    try:
        me = client.me({}) or {}
        before = me.get("points") or (me.get("entitlements") or {}).get("points")
    except Exception:
        pass
    try:
        res = client.signin(cfg.get("checkin_mode", "normal"))
    except Exception as exc:  # noqa: BLE001
        store.add_checkin(today, cfg.get("checkin_mode", "normal"), False, str(exc), before, None)
        return {"ok": False, "message": f"签到失败：{exc}"}

    code = str(res.get("code", ""))
    ok = code == "ok"
    if code == "already_signed":
        store.add_checkin(today, cfg.get("checkin_mode", "normal"), True, "今日已签到", before, before)
        return {"ok": False, "message": "今日已签到", "raw": res}
    msg = res.get("msg") or res.get("message") or (f"签到成功 +{res.get('points_awarded')} 积分" if ok else code)
    after = res.get("points_after") or res.get("points")
    store.add_checkin(today, cfg.get("checkin_mode", "normal"), ok, str(msg), before, after)

    if ok and cfg.get("checkin_notify"):
        notify.send(f"【影癫插件】签到成功\n{msg}")
    return {"ok": ok, "message": msg, "mode": mode, "raw": res}


def _filter_candidates(
    items: list[dict],
    cfg: dict,
    for_sub: bool = True,
    cloud_type: str = "115",
) -> list[dict]:
    max_points = int(cfg.get("max_unlock_points_sub" if for_sub else "max_unlock_points") or 20)
    only_free = bool(cfg.get("only_free")) if for_sub else False
    out = []
    for it in items:
        cost = it.get("unlock_cost")
        try:
            cost_i = int(cost) if cost is not None else 0
        except Exception:
            cost_i = 0
        if only_free and cost_i > 0:
            continue
        if cost_i > max_points:
            continue
        if store.already_unlocked(it.get("share_id")):
            continue
        if for_sub and cfg.get("skip_in_library") and it.get("library_checked"):
            if it.get("already_complete"):
                continue
            if it.get("media_type") == "tv" and not it.get("episode_numbers"):
                continue
        out.append(it)
    if for_sub and cloud_type == "all":
        return out
    if for_sub and cloud_type:
        preferred = [it for it in out if (it.get("share_kind") or "115") == cloud_type]
        return preferred
    if for_sub and cfg.get("d115_enabled"):
        auto_transfer = [it for it in out if (it.get("share_kind") or "115") == "115"]
        if auto_transfer:
            return auto_transfer
    return out


def search_shares(
    tmdb_id: str | int,
    media_type: str = "movie",
    season: int = 0,
    rank: bool = True,
    cloud_type: str = "",
    for_subscription: bool = False,
) -> dict:
    cfg = load_config()
    client, mode = get_client()
    payload: dict[str, Any] = {"tmdb_id": int(tmdb_id), "media_type": media_type}
    if season:
        payload["season"] = int(season)
    try:
        res = client.list_shares(payload)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"查询失败：{exc}", "items": []}
    items = (res or {}).get("items") or []
    lib_status = library.status(tmdb_id, media_type, season)
    pending = store.recent_tv_pending(tmdb_id, int(cfg.get("pending_unlock_hours") or 24)) if media_type == "tv" else []
    items = annotate_library(
        items,
        lib_status,
        requested_season=season,
        pending=pending,
        combine_pending=(cloud_type == "all"),
        respect_pending=for_subscription,
    )
    if rank:
        items = rank_shares(
            items,
            for_tv=(media_type == "tv"),
            skip_complete=bool(cfg.get("skip_in_library")),
        )
    return {
        "ok": True, "mode": mode, "items": items, "library": lib_status,
        "pending": pending,
    }


def unlock_share(
    share: dict,
    title: str = "",
    media_type: str = "",
    tmdb_id: Any = None,
    season: int = 0,
    max_cost: int | None = None,
) -> dict:
    cfg = load_config()
    if cfg.get("skip_in_library") and share.get("library_checked") and share.get("already_complete"):
        return {"ok": False, "message": "已入库或正在转存，无需重复解锁"}
    limit = int(cfg.get("unlock_rate_per_minute") or 3)
    if limit > 0 and store.unlocks_in_last_minute() >= limit:
        return {"ok": False, "message": f"触发解锁速率限制 {limit} 次/分钟，稍后再试"}

    client, mode = get_client()
    payload = {"share_id": share.get("share_id")}
    if share.get("resource_id"):
        payload["resource_id"] = share.get("resource_id")
    if share.get("index") is not None:
        payload["index"] = share.get("index")
    payload["max_cost"] = int(
        max_cost if max_cost is not None else (cfg.get("max_unlock_points") or 20)
    )
    # 浏览器模式需要 /r/<key> 才能打开资源页
    if mode == "browser" and tmdb_id and media_type:
        try:
            from .browser_client import encode_portal_key
            payload["key"] = "/r/" + encode_portal_key(tmdb_id, media_type, season)
        except Exception:
            pass
    try:
        res = client.unlock(payload)
    except Exception as exc:  # noqa: BLE001
        store.add_unlock(
            share_id=share.get("share_id"), resource_id=share.get("resource_id"), tmdb_id=tmdb_id,
            media_type=media_type, season=season, title=title, episode=share.get("episode"),
            cloud_type=(share.get("share_kind") or "115"),
            tag=share.get("tag_raw"), size=share.get("total_size_human"),
            cost=share.get("unlock_cost"), link="", ok=False, message=str(exc),
        )
        return {"ok": False, "message": f"解锁失败：{exc}"}

    link = (res or {}).get("url_115") or (res or {}).get("url") or ""
    pwd = (res or {}).get("receive_code") or ""
    ok = bool(link)
    store.add_unlock(
        share_id=share.get("share_id"), resource_id=share.get("resource_id"), tmdb_id=tmdb_id,
        media_type=media_type, season=season, title=title, episode=share.get("episode"),
        cloud_type=(share.get("share_kind") or "115"),
        tag=share.get("tag_raw"), size=share.get("total_size_human"),
        cost=share.get("unlock_cost"), link=link, ok=ok, message=(res or {}).get("code", ""),
    )
    extra = ""
    if ok:
        # ① 115 直连转存（推荐，不依赖 Telegram）
        if cfg.get("d115_enabled") and cfg.get("d115_cookie"):
            try:
                from .transfer115 import add_offline, is_offline_link, receive as receive115

                if is_offline_link(link):
                    # 115 的离线下载接口已下线，ED2K/磁力 只能给出链接让用户手动添加
                    ok115, msg115 = True, "ED2K/磁力链接已获取 · 请在 115 里手动添加离线任务"
                else:
                    ok115, msg115 = receive115(link, cfg.get("d115_cookie"), cfg.get("d115_cid"))
                extra = (" | " + msg115) if ok115 else (" | 115转存失败：" + msg115)
                if ok115:
                    cloud_type = share.get("share_kind") or "115"
                    transfer_tag = (
                        "115直连转存" if cloud_type == "115"
                        else ("ED2K链接获取" if cloud_type == "ed2k" else "磁力链接获取")
                    )
                    store.add_unlock(
                        share_id=share.get("share_id"), resource_id=share.get("resource_id"), tmdb_id=tmdb_id,
                        media_type=media_type, season=season, title=title, episode=share.get("episode"),
                        cloud_type=cloud_type, tag=transfer_tag, size="", cost=0,
                        link=link, ok=True, message=msg115,
                    )
            except Exception as exc:  # noqa: BLE001
                extra = f" | 115转存异常：{exc}"

        # ② Telegram 推送（可选，Symedia 只认真人消息，默认关掉）
        if cfg.get("tg_push_enabled", True):
            notify.send_transfer(title, link, pwd)
    return {"ok": ok, "link": link, "password": pwd, "raw": res, "mode": mode, "message": (("已解锁" + extra) if ok else "")}


def _run_manual_subscription(sub: dict, cfg: dict) -> dict | None:
    """检查订阅中手动填写的 115 分享链接，只转存新增集数。"""
    url = str(sub.get("subscription_url") or "").strip()
    if not url:
        return None
    from .transfer115 import inspect_share, receive

    cookie = str(cfg.get("d115_cookie") or "").strip()
    inspected = inspect_share(url, cookie)
    if not inspected.get("ok"):
        message = inspected.get("message") or "手动链接读取失败"
        store.update_subscription_status(int(sub["id"]), "error", message, completed=False)
        return {"title": sub.get("title") or "", "ok": False, "message": message}

    source_episodes = set(int(x) for x in inspected.get("episodes") or [])
    season = int(sub.get("season") or 0)
    lib = library.status(sub.get("tmdb_id"), sub.get("media_type") or "movie", season)
    available = set()
    if lib.get("checked") and lib.get("exists") and sub.get("media_type") == "tv":
        season_data = (lib.get("seasons") or {}).get(str(season)) or {}
        available = set(season_data.get("available") or [])

    pending = set()
    for row in store.recent_tv_pending(
        sub.get("tmdb_id"), int(cfg.get("pending_unlock_hours") or 24)
    ):
        if int(row.get("season") or 0) == season and (row.get("cloud_type") or "115") == "115":
            pending.update(parse_episode_numbers(row.get("episode") or ""))

    if sub.get("media_type") == "movie":
        if lib.get("exists"):
            store.update_subscription_status(int(sub["id"]), "completed", "电影已入库", completed=True)
            return {"title": sub.get("title") or "", "ok": False, "message": "电影已入库"}
        new_episodes = set()
    else:
        if not source_episodes:
            message = "手动链接中未识别到剧集集数"
            store.update_subscription_status(int(sub["id"]), "error", message, completed=False)
            return {"title": sub.get("title") or "", "ok": False, "message": message}
        new_episodes = source_episodes - available - pending

    if not new_episodes and sub.get("media_type") == "tv":
        missing_pending = source_episodes - available
        if missing_pending:
            message = f"链接中的第 {format_episode_numbers(missing_pending)} 集已转存，等待 Emby 入库"
        else:
            message = f"链接中的第 {format_episode_numbers(source_episodes)} 集均已入库"
        completed = bool(lib.get("complete") and not missing_pending)
        store.update_subscription_status(
            int(sub["id"]), "completed" if completed else "waiting", message, completed=completed
        )
        return {"title": sub.get("title") or "", "ok": False, "message": message}

    ok, transfer_message = receive(
        inspected.get("resolved_url") or url,
        cookie,
        cfg.get("d115_cid"),
    )
    if not ok:
        store.update_subscription_status(int(sub["id"]), "error", transfer_message, completed=False)
        return {"title": sub.get("title") or "", "ok": False, "message": transfer_message}

    episode_text = (
        f"第{season or 1}季 · 第 {format_episode_numbers(new_episodes)} 集"
        if new_episodes else ""
    )
    share_sig = hashlib.sha1(
        f"{inspected.get('resolved_url') or url}|{','.join(map(str, sorted(new_episodes)))}".encode()
    ).hexdigest()[:16]
    store.add_unlock(
        share_id=f"manual:{share_sig}",
        tmdb_id=sub.get("tmdb_id"),
        media_type=sub.get("media_type"),
        season=season,
        title=sub.get("title"),
        episode=episode_text,
        cloud_type="115",
        tag="手动115订阅链接",
        cost=0,
        link=inspected.get("resolved_url") or url,
        ok=True,
        message=transfer_message,
    )
    message = (
        f"发现新集 {format_episode_numbers(new_episodes)}，已提交 115 转存"
        if new_episodes else "已提交 115 转存"
    )
    store.update_subscription_status(int(sub["id"]), "success", message, completed=False)
    return {"title": sub.get("title") or "", "ok": True, "message": message}


def run_subscription_search() -> dict:
    """遍历订阅，搜索并解锁最优资源"""
    cfg = load_config()
    subs = [s for s in store.list_subscriptions() if s.get("enabled")]
    results = []
    for sub in subs:
        title = sub.get("title") or ""
        media_type = sub.get("media_type") or "movie"
        pattern = cfg.get("tv_filter") if media_type == "tv" else cfg.get("movie_filter")
        if not _match_filter(pattern or "", title):
            store.update_subscription_status(int(sub["id"]), "filtered", "未通过过滤词", completed=False)
            results.append({"title": title, "ok": False, "message": "未通过过滤词"})
            continue
        manual_result = _run_manual_subscription(sub, cfg)
        if manual_result is not None:
            results.append(manual_result)
            continue
        data = search_shares(
            sub.get("tmdb_id"),
            media_type,
            int(sub.get("season") or 0),
            cloud_type=sub.get("cloud_type") or "115",
            for_subscription=True,
        )
        if not data.get("ok"):
            store.update_subscription_status(int(sub["id"]), "error", data.get("message") or "查询失败", completed=False)
            results.append({"title": title, "ok": False, "message": data.get("message")})
            continue
        candidates = _filter_candidates(
            data.get("items") or [],
            cfg,
            for_sub=True,
            cloud_type=sub.get("cloud_type") or "115",
        )
        if not candidates:
            lib = data.get("library") or {}
            cloud_label = {"115": "115", "ed2k": "ED2K", "magnet": "磁力"}.get(
                sub.get("cloud_type") or "115", "指定网盘"
            )
            pending_numbers = set()
            for row in data.get("pending") or []:
                row_cloud = row.get("cloud_type") or "115"
                if int(row.get("season") or 0) != int(sub.get("season") or 0):
                    continue
                if (sub.get("cloud_type") or "115") not in ("all", row_cloud):
                    continue
                pending_numbers.update(parse_episode_numbers(row.get("episode") or ""))
            available_for_season = set()
            if lib.get("media_type") == "tv":
                season_data = (lib.get("seasons") or {}).get(str(int(sub.get("season") or 0))) or {}
                available_for_season = set(season_data.get("available") or [])
            pending_numbers -= available_for_season
            pending_text = format_episode_numbers(pending_numbers)
            if pending_text:
                message = f"第 {pending_text} 集链接已获取 · 等待 Emby 入库"
            elif lib.get("checked") and lib.get("exists"):
                if lib.get("complete"):
                    message = f"已完整入库 · {lib.get('available_text') or '无需补集'}"
                elif lib.get("available_text"):
                    message = f"已入库 {lib.get('available_text')} · 没有可补齐的新分享"
                else:
                    message = "已入库 · 没有可补齐的新分享"
            else:
                message = f"没有符合条件的 {cloud_label} 新分享"
            store.update_subscription_status(
                int(sub["id"]),
                "completed" if lib.get("complete") else "waiting",
                message,
                completed=bool(lib.get("complete")),
            )
            results.append({"title": title, "ok": False, "message": message})
            continue
        best = candidates[0]
        season_no = int(sub.get("season") or best.get("season_number") or 0)
        r = unlock_share(
            best,
            title=title,
            media_type=media_type,
            tmdb_id=sub.get("tmdb_id"),
            season=season_no,
            max_cost=int(cfg.get("max_unlock_points_sub") or 20),
        )
        if r.get("ok"):
            store.set_last_share(int(sub["id"]), str(best.get("share_id")))
            store.update_subscription_status(int(sub["id"]), "success", "已提交转存", completed=False)
        else:
            store.update_subscription_status(
                int(sub["id"]),
                "error",
                r.get("message") or "解锁失败",
                completed=False,
            )
        coverage = (
            f"补齐 {best.get('new_episodes_text')} 集 · "
            if best.get("new_episodes_text") else ""
        )
        result_message = r.get("message") or f"已解锁 {best.get('tag_raw')}"
        if r.get("ok") and coverage:
            result_message = coverage + result_message
        results.append({
            "title": title,
            "ok": r.get("ok"),
            "message": result_message,
        })
    return {"ok": True, "results": results}


def rss_poll() -> dict:
    """RSS 增量订阅：拉取新分享事件并解锁订阅命中的资源"""
    cfg = load_config()
    if not cfg.get("rss_enabled"):
        return {"ok": False, "message": "RSS 订阅未启用"}
    client, mode = get_client()
    cursor = store.kv_get("rss_cursor") or ""
    payload: dict[str, Any] = {"limit": 50, "filter": cfg.get("rss_filter") or {}}
    if cursor:
        payload["cursor"] = cursor
    try:
        res = client.rss(payload) or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"RSS 拉取失败：{exc}"}

    code = str(res.get("code") or "")
    if code and code != "ok":
        if code == "cursor_expired":
            store.kv_set("rss_cursor", "")
        return {"ok": False, "message": f"RSS 返回 {code}"}

    items = res.get("items") or []
    subs = {str(s.get("tmdb_id")): s for s in store.list_subscriptions() if s.get("enabled")}
    handled = []
    for it in items:
        key = str(it.get("tmdb_id"))
        sub = subs.get(key)
        if not sub:
            continue
        r = unlock_share(
            {
                "share_id": it.get("share_id"),
                "resource_id": it.get("resource_id"),
                "media_type": sub.get("media_type") or "",
                "tag_raw": it.get("tag") or it.get("tag_raw"),
                "total_size_human": it.get("total_size_human") or it.get("size"),
                "unlock_cost": it.get("unlock_cost") or it.get("cost"),
                "episode": it.get("episode") or "",
            },
            title=sub.get("title") or "",
            media_type=sub.get("media_type") or "",
            tmdb_id=it.get("tmdb_id"),
            season=int(sub.get("season") or 0),
        )
        handled.append({"title": sub.get("title"), "ok": r.get("ok"), "message": r.get("message")})

    if res.get("next_cursor"):
        store.kv_set("rss_cursor", str(res.get("next_cursor")))
    return {"ok": True, "mode": mode, "count": len(items), "handled": handled}

