"""Telegram 推送（把 115 链接发给 Symedia 115助手 所在群）"""
from __future__ import annotations

import httpx

from .config import load_config

API = "https://api.telegram.org"


def send(text: str) -> tuple[bool, str]:
    cfg = load_config()
    token = cfg.get("tg_bot_token", "")
    chat = cfg.get("tg_chat_id", "")
    if not token or not chat:
        return False, "未配置 Telegram bot token / chat id"
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(
                f"{API}/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
            )
            data = r.json()
        if data.get("ok"):
            return True, "已发送"
        return False, f"Telegram 错误: {data.get('description', '')}"
    except Exception as exc:  # noqa: BLE001
        return False, f"发送失败: {exc}"


def send_transfer(title: str, link: str, password: str = "") -> tuple[bool, str]:
    cfg = load_config()
    tpl = cfg.get("tg_template") or "【影癫插件】{title}\n{link}"
    text = tpl.replace("{title}", title or "影癫资源").replace("{link}", link)
    if password and password not in text:
        text += f"\n提取码：{password}"
    return send(text)
