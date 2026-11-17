"""影癫 OpenAPI v2 客户端。

优先使用官方发放的 SDK（审批通过后下载，包名 dian115_openapi）。
未安装 SDK 或开启模拟模式时，使用 MockClient，方便先把界面/流程跑通。

官方 SDK 用法（见影癫 OpenAPI v2 文档）：
    from dian115_openapi import Dian115OpenAPI
    client = Dian115OpenAPI(base_url="https://m.dian115.com", api_key="dys_xxx")
    client.signin("normal")
    client.list_shares({"tmdb_id": 438631, "media_type": "movie"})["items"]
    client.unlock({"share_id": 123, "resource_id": 456})
"""
from __future__ import annotations

import random
from typing import Any

from .config import load_config

SDK_IMPORT_ERROR = ""


def _try_import_sdk():
    try:
        from dian115_openapi import Dian115OpenAPI  # type: ignore

        return Dian115OpenAPI
    except Exception as exc:  # noqa: BLE001
        global SDK_IMPORT_ERROR
        SDK_IMPORT_ERROR = str(exc)
        return None


class MockClient:
    """本地模拟：不调用真实接口，用于界面联调与演示。"""

    def __init__(self) -> None:
        self._signed = False

    def me(self, _payload: dict | None = None) -> dict:
        return {
            "code": "ok",
            "nickname": "模拟用户",
            "vip": False,
            "points": 1234,
            "entitlements": {"level": "L2", "daily_api_remaining": 500, "daily_unlock_remaining": 30},
        }

    def signin(self, mode: str) -> dict:
        if self._signed:
            return {"code": "already_signed", "msg": "今日已签到"}
        self._signed = True
        return {"code": "ok", "points_awarded": random.randint(5, 20), "mode": mode}

    def list_shares(self, payload: dict) -> dict:
        tmdb_id = payload.get("tmdb_id")
        items = []
        for i in range(3):
            res = ["4K", "1080P", "720P"][i]
            items.append(
                {
                    "share_id": f"mock-{tmdb_id}-{i}",
                    "resource_id": f"mock-res-{tmdb_id}",
                    "tmdb_id": tmdb_id,
                    "media_type": payload.get("media_type", "movie"),
                    "tag_raw": f"DT2|{res}|WEB-DL|NF|HEVC|HDR10|DDP5.1|CHS|MKV",
                    "tag_decoded": {"resolution": res, "source": "WEB-DL", "hdr": "HDR10", "audio_codec": "DDP5.1"},
                    "total_size_human": ["8.5 GB", "2.1 GB", "900 MB"][i],
                    "total_size_bytes": [9126805504, 2254857830, 943718400][i],
                    "unlock_cost": [12, 4, 0][i],
                    "is_unlocked": False,
                    "has_chinese_subtitle": True,
                    "use_count": 10 - i,
                    "share_kind": "115",
                    "created_at": "2026-11-15T10:00:00+08:00",
                }
            )
        return {"code": "ok", "items": items}

    def unlock(self, payload: dict) -> dict:
        sid = payload.get("share_id")
        return {
            "code": "ok",
            "share_id": sid,
            "url_115": f"https://115cdn.com/s/mock{sid}?password=abcd#",
            "receive_code": "abcd",
            "points_cost": 4,
        }

    def rss(self, payload: dict) -> dict:
        return {"code": "ok", "items": [], "has_more": False, "next_cursor": payload.get("cursor") or "mock-cursor"}

    def rss_options(self, payload: dict | None = None) -> dict:
        return {"code": "ok", "categories": [], "regions": [], "tags": {}}


class DianClient:
    """真实客户端：包装官方 SDK。"""

    def __init__(self, base_url: str, api_key: str) -> None:
        SDK = _try_import_sdk()
        if SDK is None:
            raise RuntimeError(
                "未安装官方 SDK。请先申请开发者，下载 Python SDK 并安装，"
                f"或开启模拟模式。导入错误：{SDK_IMPORT_ERROR}"
            )
        self._sdk = SDK(base_url=base_url, api_key=api_key)

    def me(self, payload: dict | None = None) -> dict:
        p = payload or {}
        return self._sdk.me(p) if hasattr(self._sdk, "me") else {}

    def signin(self, mode: str) -> dict:
        return self._sdk.signin(mode)

    def list_shares(self, payload: dict) -> dict:
        return self._sdk.list_shares(payload)

    def unlock(self, payload: dict) -> dict:
        return self._sdk.unlock(payload)

    def rss(self, payload: dict) -> dict:
        return self._sdk.rss(payload)

    def rss_options(self, payload: dict | None = None) -> dict:
        return self._sdk.rss_options(payload or {}) if hasattr(self._sdk, "rss_options") else {}


def current_mode(cfg: dict) -> str:
    """mock | sdk | browser（兼容旧的 mock_mode 布尔开关）"""
    mode = (cfg.get("mode") or "").strip().lower()
    if mode in ("mock", "sdk", "browser"):
        return mode
    return "mock" if cfg.get("mock_mode") else "sdk"


def get_client() -> tuple[Any, str]:
    """返回 (client, mode)，mode ∈ {mock, sdk, browser}"""
    cfg = load_config()
    mode = current_mode(cfg)
    if mode == "mock":
        return MockClient(), "mock"
    if mode == "browser":
        from .browser_client import BrowserClient

        return (
            BrowserClient(
                cfg.get("dian_base_url", "https://m.dian115.com"),
                cfg.get("cdp_host", "127.0.0.1"),
                int(cfg.get("cdp_port") or 9222),
            ),
            "browser",
        )
    return DianClient(cfg.get("dian_base_url", ""), cfg.get("dian_api_key", "")), "sdk"


def client_status() -> dict:
    cfg = load_config()
    mode = current_mode(cfg)
    if mode == "mock":
        return {"mode": "mock", "ready": True, "message": "模拟模式", "detail": "假数据，仅用于试用界面"}
    if mode == "browser":
        from .cdp import browser_reachable, find_logged_in_target

        host = cfg.get("cdp_host", "127.0.0.1")
        port = int(cfg.get("cdp_port") or 9222)
        ok, info = browser_reachable(host, port)
        if not ok:
            return {"mode": "browser", "ready": False, "message": "浏览器未连接", "detail": f"CDP {host}:{port} 连不上：{info}"}
        target = find_logged_in_target(host, port, cfg.get("dian_base_url", ""))
        if not target:
            return {"mode": "browser", "ready": False, "message": "需要登录影癫", "detail": "浏览器已连接，但没有已登录的影癫标签页"}
        return {"mode": "browser", "ready": True, "message": "就绪", "detail": f"{info} · 已找到登录标签页"}
    if _try_import_sdk() is None:
        return {"mode": "sdk", "ready": False, "message": "未安装 SDK", "detail": SDK_IMPORT_ERROR}
    if not cfg.get("dian_api_key"):
        return {"mode": "sdk", "ready": False, "message": "未填写 Key", "detail": "请在设置里填写 OpenAPI Key"}
    return {"mode": "sdk", "ready": True, "message": "就绪", "detail": "官方 OpenAPI SDK"}

