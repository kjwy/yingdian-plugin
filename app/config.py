"""配置读写：data/config.json"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("YDP_DATA_DIR", str(BASE_DIR / "data")))
CONFIG_FILE = DATA_DIR / "config.json"
DB_FILE = DATA_DIR / "plugin.db"

DEFAULTS: dict = {
    # 运行模式：mock（模拟）| sdk（官方 OpenAPI）| browser（浏览器自动化）
    "mode": os.getenv("YDP_MODE", "browser"),
    # 浏览器模式用的 CDP 地址（NAS 上指向 browser 容器）
    "cdp_host": os.getenv("YDP_CDP_HOST", "127.0.0.1"),
    "cdp_port": int(os.getenv("YDP_CDP_PORT", "9222")),
    # 影癫 OpenAPI
    "dian_base_url": os.getenv("DIAN_BASE_URL", "https://m.dian115.com"),
    "dian_api_key": "",
    # 影癫账号，用于登录失效时自动重新登录
    "dian_email": "",
    "dian_password": "",
    # 签到
    "checkin_enabled": True,
    "checkin_mode": "normal",          # normal | lucky
    "checkin_window_start": 8,         # 随机签到时间窗口（小时）
    "checkin_window_end": 23,
    "checkin_notify": True,
    # 解锁策略（对标 HDHive配置）
    "max_unlock_points": 20,
    "unlock_rate_per_minute": 3,
    "expire_remind_enabled": True,
    "expire_remind_hours": 6,
    # 订阅设置（对标 HDHive订阅）
    "movie_filter": "",               # 正则，匹配标题/正文
    "tv_filter": "",                  # 正则
    "max_unlock_points_sub": 20,
    "only_free": False,
    "unlock_official": True,
    "api_search_enabled": True,
    "rss_enabled": False,
    "rss_interval_minutes": 5,
    "subs_interval_minutes": 30,
    "rss_filter": {                    # 与 rss/options 对齐
        "media_types": [],
        "categories": [],
        "regions": [],
        "tags": {},
    },
    # Telegram 推送（Symedia 115助手 所在群）
    # 115 直连转存
    "d115_enabled": False,
    "d115_cookie": "",
    "d115_cid": "0",
    # Emby 入库检测：避免重复解锁已入库或正在转存的集数
    "emby_enabled": True,
    "emby_host": "",
    "emby_api_key": "",
    "skip_in_library": True,
    "pending_unlock_hours": 24,
    # 是否同时推送 Telegram（Symedia 只认真人消息，建议关）
    "tg_push_enabled": True,
    "tg_bot_token": "",
    "tg_proxy": "",   # 可选：http://127.0.0.1:7890 这类 HTTP 代理
    "tg_chat_id": "",
    "tg_template": "【影癫插件】{title}\n{link}",
    # TMDB（用于片名 → tmdb_id）
    "tmdb_api_key": "",
    "tmdb_proxy": "",       # 可选：TMDB 代理（留空则沿用 Telegram 代理）
    "tmdb_api_base": "https://api.themoviedb.org/3",
    "tmdb_image_base": "https://image.tmdb.org/t/p",
    "tmdb_language": "zh-CN",
    # 其它
    "mock_mode": os.getenv("YDP_MOCK", "0") == "1",
    "timezone": os.getenv("TZ", "Asia/Shanghai"),
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    # Docker 部署时环境变量优先（方便 compose 里统一控制）
    if os.getenv("YDP_MODE"):
        cfg["mode"] = os.getenv("YDP_MODE")
    if os.getenv("YDP_CDP_HOST"):
        cfg["cdp_host"] = os.getenv("YDP_CDP_HOST")
    if os.getenv("YDP_CDP_PORT"):
        try:
            cfg["cdp_port"] = int(os.getenv("YDP_CDP_PORT"))
        except ValueError:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:8] + "***"

