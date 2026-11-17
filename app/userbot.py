"""Telegram 用户账号模式（userbot）

为什么要这个：Symedia 的 115助手只会处理「真人账号」发的消息，机器人发的会被忽略。
所以插件用你自己的 TG 账号登录后，以你的身份把 115 链接发到群里。

登录需要：
  1. https://my.telegram.org 创建应用，拿 api_id / api_hash
  2. 手机号（+86...），Telegram 里收验证码
  3. 如果开了两步验证，还要密码
"""
from __future__ import annotations

import asyncio
import json

from .config import load_config, save_config

# 待验证的登录会话（api_id -> client）
_pending: dict[str, object] = {}


def _client(api_id: int, api_hash: str, session: str | None = None):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(session or ""), api_id, api_hash)


def start_login(phone: str) -> dict:
    """发送登录验证码"""
    cfg = load_config()
    api_id = int(cfg.get("tg_api_id") or 0)
    api_hash = (cfg.get("tg_api_hash") or "").strip()
    phone = phone.strip()
    if not api_id or not api_hash:
        return {"ok": False, "message": "请先填写 api_id 和 api_hash（my.telegram.org 获取）"}
    if not phone:
        return {"ok": False, "message": "请填写手机号（带国家码，如 +8613800000000）"}

    async def _run():
        c = _client(api_id, api_hash)
        await c.connect()
        sent = await c.send_code_request(phone)
        return c, sent

    try:
        c, sent = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"发送验证码失败：{exc}"}

    _pending[phone] = c
    cfg["tg_phone"] = phone
    save_config(cfg)
    return {"ok": True, "message": "验证码已发送到你的 Telegram，请填入下方验证码"}


def verify_login(phone: str, code: str, password: str = "") -> dict:
    """验证码登录，成功后保存 session

    注意：每次都用**新建的 client**（Telethon client 绑定事件循环，
    不能跨 asyncio.run 复用，否则会报 "attached to a different loop"）。
    """
    cfg = load_config()
    phone = (phone or cfg.get("tg_phone") or "").strip()
    api_id = int(cfg.get("tg_api_id") or 0)
    api_hash = (cfg.get("tg_api_hash") or "").strip()
    if not api_id or not api_hash:
        return {"ok": False, "message": "请先填写 api_id / api_hash 并保存"}
    if not phone:
        return {"ok": False, "message": "请先填写手机号"}
    if not code.strip():
        return {"ok": False, "message": "请填写验证码"}

    async def _run():
        from telethon.errors import SessionPasswordNeededError

        c = _client(api_id, api_hash)
        await c.connect()
        try:
            await c.sign_in(phone=phone, code=code.strip())
        except SessionPasswordNeededError:
            if not password:
                await c.disconnect()
                return {"need_password": True}
            await c.sign_in(password=password)
        session = c.session.save()
        await c.disconnect()
        return {"session": session}

    try:
        result = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "password" in msg.lower():
            return {"ok": False, "need_password": True, "message": f"该账号开启了二次验证，请填写密码（{msg[:60]}）"}
        return {"ok": False, "message": f"登录失败：{msg}"}

    if result.get("need_password"):
        return {"ok": False, "need_password": True, "message": "该账号开启了二次验证，请填写两步验证密码"}

    cfg = load_config()
    cfg["tg_userbot_session"] = result["session"]
    cfg["tg_phone"] = phone
    save_config(cfg)
    return {"ok": True, "message": "登录成功！之后推送将以你的账号发出，Symedia 会正常处理"}


def status() -> dict:
    cfg = load_config()
    has_session = bool(cfg.get("tg_userbot_session"))
    return {
        "configured": bool(cfg.get("tg_api_id")) and bool(cfg.get("tg_api_hash")),
        "logged_in": has_session,
        "phone": cfg.get("tg_phone", ""),
        "api_id": cfg.get("tg_api_id", ""),
    }


def send_as_user(chat_id: str, text: str) -> tuple[bool, str]:
    """用你的账号发消息（Symedia 就会处理）"""
    cfg = load_config()
    session = cfg.get("tg_userbot_session")
    api_id = int(cfg.get("tg_api_id") or 0)
    api_hash = (cfg.get("tg_api_hash") or "").strip()
    if not session or not api_id or not api_hash:
        return False, "未登录 Telegram 账号（userbot）"

    async def _run():
        c = _client(api_id, api_hash, session)
        await c.connect()
        try:
            target = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            await c.send_message(target, text)
        finally:
            await c.disconnect()

    try:
        asyncio.run(_run())
        return True, "已用你的 Telegram 账号发送"
    except Exception as exc:  # noqa: BLE001
        return False, f"发送失败：{exc}"

