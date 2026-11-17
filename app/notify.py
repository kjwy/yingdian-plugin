"""Telegram 推送（把 115 链接发给 Symedia 115助手 所在群）

支持 HTTP 代理：NAS 在国内通常直连不了 api.telegram.org，需要在设置里填代理。
"""
from __future__ import annotations

import httpx

from .config import load_config

API = "https://api.telegram.org"


def _client(timeout: float = 25.0) -> httpx.Client:
    cfg = load_config()
    proxy = (cfg.get("tg_proxy") or "").strip()
    if proxy:
        try:
            return httpx.Client(timeout=timeout, proxy=proxy)
        except TypeError:  # 兼容旧版 httpx
            return httpx.Client(timeout=timeout, proxies=proxy)
    return httpx.Client(timeout=timeout)


def check() -> tuple[bool, str]:
    """诊断：调用 getMe，验证 token 与网络连通性。"""
    cfg = load_config()
    token = (cfg.get("tg_bot_token") or "").strip()
    if not token:
        return False, "未填写 Bot Token"
    proxy = (cfg.get("tg_proxy") or "").strip()
    try:
        with _client(20) as c:
            r = c.get(f"{API}/bot{token}/getMe")
            data = r.json()
        if data.get("ok"):
            bot = data.get("result") or {}
            extra = f"· 代理 {proxy}" if proxy else "· 直连"
            return True, f"连接正常：@{bot.get('username')} {extra}"
        return False, f"Token 无效：{data.get('description', '')}"
    except Exception as exc:  # noqa: BLE001
        hint = "NAS 可能无法直连 Telegram，请在下方填写 HTTP 代理" if not proxy else "代理不可用，请检查地址/端口"
        return False, f"网络不通：{type(exc).__name__}: {exc}。{hint}"


def send(text: str) -> tuple[bool, str]:
    cfg = load_config()
    chat = (cfg.get("tg_chat_id") or "").strip()

    # 优先用「你的 Telegram 账号」发送（Symedia 只处理真人账号的消息）
    if cfg.get("tg_userbot_session") and chat:
        from .userbot import send_as_user

        return send_as_user(chat, text)

    token = (cfg.get("tg_bot_token") or "").strip()
    if not token or not chat:
        return False, "未配置 Telegram bot token / chat id"
    try:
        with _client(25) as c:
            r = c.post(
                f"{API}/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
            )
            data = r.json()
        if data.get("ok"):
            return True, "已发送到 Telegram"
        return False, f"Telegram 返回错误: {data.get('description', '')}"
    except Exception as exc:  # noqa: BLE001
        return False, f"发送失败：{type(exc).__name__}: {exc}"


def send_transfer(title: str, link: str, password: str = "") -> tuple[bool, str]:
    cfg = load_config()
    tpl = cfg.get("tg_template") or "【影癫插件】{title}\n{link}"
    text = tpl.replace("{title}", title or "影癫资源").replace("{link}", link)
    if password and password not in text:
        text += f"\n提取码：{password}"
    return send(text)

