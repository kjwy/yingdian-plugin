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
    # 影癫 OpenAPI
    "dian_base_url": os.getenv("DIAN_BASE_URL", "https://m.dian115.com"),
    "dian_api_key": "",
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
    "rss_filter": {                    # 与 rss/options 对齐
        "media_types": [],
        "categories": [],
        "regions": [],
        "tags": {},
    },
    # Telegram 推送（Symedia 115助手 所在群）
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

