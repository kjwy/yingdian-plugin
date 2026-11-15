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
  title TEXT,
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
  enabled INTEGER DEFAULT 1,
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
    fields = ["share_id", "resource_id", "tmdb_id", "media_type", "title", "tag", "size", "cost", "link", "ok", "message"]
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


# ---------- 订阅 ----------
def add_subscription(title: str, tmdb_id: str, media_type: str, season: int = 0) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO subscriptions(title, tmdb_id, media_type, season, enabled, created_at) VALUES(?,?,?,?,?,?)",
            (title, str(tmdb_id), media_type, season, 1, _now()),
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


def set_last_share(sid: int, share_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE subscriptions SET last_share_id = ? WHERE id = ?", (str(share_id), sid))
