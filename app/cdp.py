"""极简 Chrome DevTools Protocol 客户端（同步）

用途：接管一个已登录影癫的浏览器标签页，执行导航 / 抓接口 / 点按钮。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.parse
import urllib.request
from typing import Any

import websocket  # websocket-client


class CDPError(RuntimeError):
    pass


def _host_ip(host: str) -> str:
    """Chromium 的 DevTools 只接受 IP / localhost 作为 Host 头，
    所以容器名（如 browser）必须先解析成 IP。"""
    if host in ("127.0.0.1", "localhost", "::1"):
        return host
    try:
        return socket.gethostbyname(host)
    except Exception:
        return host


def _rewrite_ws(ws_url: str, host_ip: str, port: int) -> str:
    """把 Chromium 返回的 ws://127.0.0.1:9222/... 改写成 ws://<ip>:<port>/..."""
    try:
        parts = urllib.parse.urlsplit(ws_url)
        return urllib.parse.urlunsplit(("ws", f"{host_ip}:{port}", parts.path, parts.query, parts.fragment))
    except Exception:
        return ws_url


def list_targets(host: str, port: int, timeout: float = 5.0) -> list[dict]:
    ip = _host_ip(host)
    url = f"http://{ip}:{port}/json/list"
    req = urllib.request.Request(url, headers={"User-Agent": "ydp"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        targets = json.loads(r.read().decode("utf-8"))
    for t in targets:
        if t.get("webSocketDebuggerUrl"):
            t["webSocketDebuggerUrl"] = _rewrite_ws(t["webSocketDebuggerUrl"], ip, port)
    return targets


class CDPSession:
    """连接单个标签页（target）"""

    def __init__(self, ws_url: str, timeout: float = 60.0):
        self.ws = websocket.create_connection(ws_url, timeout=timeout, max_size=None)
        self._id = 0
        self._events: list[dict] = []

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def _recv(self) -> dict:
        raw = self.ws.recv()
        if not raw:
            return {}
        return json.loads(raw)

    def send(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self._recv()
            except Exception:
                # websocket 读超时：放宽一次，不立即失败
                time.sleep(0.3)
                continue
            if not msg:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise CDPError(f"{method} 失败: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self._events.append(msg)
        raise CDPError(f"{method} 超时")

    def enable_network(self) -> None:
        self.send("Network.enable", {})
        self.send("Page.enable", {})

    def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        res = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        )
        return (res.get("result") or {}).get("value")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})

    def wait_json_response(self, url_contains: str, timeout: float = 25.0) -> dict | None:
        """等待包含指定 URL 的 JSON 响应并返回解析后的 body"""
        deadline = time.time() + timeout
        # 先看已缓存事件
        events, self._events = self._events, []
        for ev in events:
            body = self._try_body(ev, url_contains)
            if body is not None:
                return body
        while time.time() < deadline:
            try:
                msg = self._recv()
            except Exception:
                continue
            if not msg or "method" not in msg:
                continue
            body = self._try_body(msg, url_contains)
            if body is not None:
                return body
        return None

    def _try_body(self, ev: dict, url_contains: str) -> dict | None:
        if ev.get("method") != "Network.responseReceived":
            return None
        p = ev.get("params") or {}
        resp = p.get("response") or {}
        url = resp.get("url") or ""
        if url_contains not in url:
            return None
        ctype = (resp.get("mimeType") or "") + str(resp.get("headers") or "")
        if "json" not in ctype.lower():
            return None
        try:
            body_res = self.send("Network.getResponseBody", {"requestId": p.get("requestId")})
            raw = body_res.get("body") or ""
            if body_res.get("base64Encoded"):
                import base64

                raw = base64.b64decode(raw).decode("utf-8", "ignore")
            return json.loads(raw)
        except Exception:
            return None


def find_logged_in_target(host: str, port: int, base_url: str) -> dict | None:
    """在浏览器里找"已登录影癫"的标签页（登录态绑定标签页，必须复用）"""
    try:
        targets = list_targets(host, port)
    except Exception:
        return None
    pages = [t for t in targets if t.get("type") == "page" and "dian115.com" in (t.get("url") or "")]
    for t in pages:
        try:
            s = CDPSession(t["webSocketDebuggerUrl"], timeout=10)
            try:
                logged = s.evaluate(
                    "(() => { const t = document.body ? document.body.innerText : '';"
                    " return /账号/.test(t) && /\\d{2,}/.test((t.split('账号')[1]||'')); })()"
                )
            finally:
                s.close()
            if logged:
                return t
        except Exception:
            continue
    return None


def browser_reachable(host: str, port: int) -> tuple[bool, str]:
    try:
        ip = _host_ip(host)
        v = json.loads(
            urllib.request.urlopen(f"http://{ip}:{port}/json/version", timeout=5).read().decode("utf-8")
        )
        return True, v.get("Browser", "unknown")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

