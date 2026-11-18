"""SQLite 存储：签到记录、解锁记录、RSS 游标、订阅列表"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .config import DB_FILE, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  mode TEXT,
  ok INTEGER,
  message TEXT,
  points_before INTEGER,
  points_after INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unlocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  share_id TEXT,
  resource_id TEXT,
  tmdb_id TEXT,
  media_type TEXT,
  season INTEGER DEFAULT 0,
  title TEXT,
  episode TEXT,
  cloud_type TEXT,
  tag TEXT,
  size TEXT,
  cost INTEGER,
  link TEXT,
  ok INTEGER,
  message TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  tmdb_id TEXT,
  media_type TEXT,
  season INTEGER DEFAULT 0,
  start_episode INTEGER DEFAULT 1,
  total_episodes INTEGER DEFAULT 0,
  cloud_type TEXT DEFAULT '115',
  subscription_url TEXT,
  enabled INTEGER DEFAULT 1,
  completed INTEGER DEFAULT 0,
  last_status TEXT DEFAULT 'pending',
  last_message TEXT,
  last_checked_at TEXT,
  last_share_id TEXT,
  created_at TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(unlocks)").fetchall()}
        if "season" not in columns:
            conn.execute("ALTER TABLE unlocks ADD COLUMN season INTEGER DEFAULT 0")
        if "episode" not in columns:
            conn.execute("ALTER TABLE unlocks ADD COLUMN episode TEXT")
        if "cloud_type" not in columns:
            conn.execute("ALTER TABLE unlocks ADD COLUMN cloud_type TEXT")
        conn.execute(
            "UPDATE unlocks SET cloud_type = CASE "
            "WHEN UPPER(COALESCE(tag,'')) LIKE '%ED2K%' THEN 'ed2k' "
            "WHEN UPPER(COALESCE(tag,'')) LIKE '%磁力%' OR LOWER(COALESCE(tag,'')) LIKE '%magnet%' THEN 'magnet' "
            "ELSE '115' END "
            "WHERE cloud_type IS NULL OR cloud_type = ''"
        )
        sub_columns = {row["name"] for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
        migrations = {
            "start_episode": "INTEGER DEFAULT 1",
            "total_episodes": "INTEGER DEFAULT 0",
            "cloud_type": "TEXT DEFAULT '115'",
            "subscription_url": "TEXT",
            "completed": "INTEGER DEFAULT 0",
            "last_status": "TEXT DEFAULT 'pending'",
            "last_message": "TEXT",
            "last_checked_at": "TEXT",
        }
        for name, declaration in migrations.items():
            if name not in sub_columns:
                conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {name} {declaration}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- KV ----------
def kv_get(key: str, default: str | None = None) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------- 签到 ----------
def has_checked_in(day: str | None = None) -> bool:
    day = day or date.today().isoformat()
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM checkins WHERE day = ? AND ok = 1 LIMIT 1", (day,)).fetchone()
        return row is not None


def add_checkin(day: str, mode: str, ok: bool, message: str, before: int | None = None, after: int | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO checkins(day, mode, ok, message, points_before, points_after, created_at) VALUES(?,?,?,?,?,?,?)",
            (day, mode, 1 if ok else 0, message, before, after, _now()),
        )


def list_checkins(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM checkins ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---------- 解锁 ----------
def add_unlock(**kw: Any) -> None:
    fields = [
        "share_id", "resource_id", "tmdb_id", "media_type", "season", "title", "episode",
        "cloud_type", "tag", "size", "cost", "link", "ok", "message",
    ]
    values = [kw.get(f) for f in fields]
    with _conn() as conn:
        conn.execute(
            f"INSERT INTO unlocks({','.join(fields)}, created_at) VALUES({','.join(['?'] * len(fields))}, ?)",
            (*values, _now()),
        )


def list_unlocks(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM unlocks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def unlocks_in_last_minute() -> int:
    since = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) c FROM unlocks WHERE ok = 1 AND created_at >= ?", (since,)).fetchone()
        return int(row["c"])


def already_unlocked(share_id: str | int) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM unlocks WHERE ok = 1 AND share_id = ? LIMIT 1", (str(share_id),)).fetchone()
        return row is not None


def recent_tv_pending(tmdb_id: str | int, hours: int = 24) -> list[dict]:
    """最近已解锁/转存中的剧集，防止 Emby 尚未刷新时重复解锁。"""
    since = (datetime.now() - timedelta(hours=max(1, int(hours)))).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        rows = conn.execute(
            "SELECT season, episode, cloud_type, created_at FROM unlocks "
            "WHERE ok = 1 AND media_type = 'tv' AND tmdb_id = ? AND created_at >= ? "
            "AND episode IS NOT NULL AND episode != '' ORDER BY id DESC",
            (str(tmdb_id), since),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- 订阅 ----------
def add_subscription(
    title: str,
    tmdb_id: str,
    media_type: str,
    season: int = 0,
    start_episode: int = 1,
    total_episodes: int = 0,
    cloud_type: str = "115",
    subscription_url: str = "",
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO subscriptions("
            "title, tmdb_id, media_type, season, start_episode, total_episodes, "
            "cloud_type, subscription_url, enabled, completed, last_status, created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                title, str(tmdb_id), media_type, season, max(1, int(start_episode or 1)),
                max(0, int(total_episodes or 0)), cloud_type or "115",
                subscription_url or "", 1, 0, "pending", _now(),
            ),
        )


def list_subscriptions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def delete_subscription(sid: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM subscriptions WHERE id = ?", (sid,))


def toggle_subscription(sid: int, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute("UPDATE subscriptions SET enabled = ? WHERE id = ?", (1 if enabled else 0, sid))


def set_subscription_cloud(sid: int, cloud_type: str) -> None:
    cloud_type = cloud_type if cloud_type in ("all", "115", "ed2k", "magnet") else "115"
    with _conn() as conn:
        conn.execute("UPDATE subscriptions SET cloud_type = ? WHERE id = ?", (cloud_type, sid))


def update_subscription(
    sid: int,
    title: str,
    tmdb_id: str,
    media_type: str,
    season: int,
    start_episode: int,
    total_episodes: int,
    cloud_type: str,
    subscription_url: str,
) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE subscriptions SET title = ?, tmdb_id = ?, media_type = ?, season = ?, "
            "start_episode = ?, total_episodes = ?, cloud_type = ?, subscription_url = ? "
            "WHERE id = ?",
            (
                title, str(tmdb_id), media_type, int(season or 0),
                max(1, int(start_episode or 1)), max(0, int(total_episodes or 0)),
                cloud_type, subscription_url, sid,
            ),
        )


def set_last_share(sid: int, share_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE subscriptions SET last_share_id = ? WHERE id = ?", (str(share_id), sid))

def update_subscription_status(
    sid: int,
    status: str,
    message: str = "",
    completed: bool | None = None,
) -> None:
    with _conn() as conn:
        if completed is None:
            conn.execute(
                "UPDATE subscriptions SET last_status = ?, last_message = ?, last_checked_at = ? WHERE id = ?",
                (status, message, _now(), sid),
            )
        else:
            conn.execute(
                "UPDATE subscriptions SET last_status = ?, last_message = ?, last_checked_at = ?, completed = ? WHERE id = ?",
                (status, message, _now(), 1 if completed else 0, sid),
            )

