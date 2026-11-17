"""浏览器自动化适配器（不依赖官方 SDK 审批）

原理：
  - 资源页地址 /r/<key>，key = base64url( XOR("1|tmdb|<type>|<tmdb_id>|<season>", mask) )
    → 知道 TMDB ID 就能直接打开资源页，不需要搜索接口
  - 用 CDP 接管一个「已登录影癫」的标签页（登录态绑定标签页，不能新开）
  - 列表：解析页面 li.hd-share-card 卡片（规格 / 大小 / 积分 / 是否已解锁）
  - 解锁：点该卡片的「获取」按钮（如有确认框则点确认），然后从页面/弹窗里读取 115 链接
  - 签到：打开 /me/signin 点签到按钮
"""
from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from typing import Any

from .config import load_config
from .cdp import CDPSession, browser_reachable, find_logged_in_target, list_targets

MASK = (0x37, 0xA1, 0x5C, 0xE9)

# 浏览器模式只能操作同一个标签页，必须串行，否则并发会互相干扰
_BROWSER_LOCK = threading.RLock()

LINK_RE = r"https?://(?:115cdn\.com|115\.com|anxia\.com)/s/[A-Za-z0-9]+(?:\?password=[A-Za-z0-9]+)?"

CARD_JS = r"""
(() => {
  const KEYS = ["8K","4K","1080P","1080I","720P","SD","H.265","H.264","AV1",
    "Dolby Vision","HDR10+","HDR10","SDR","TrueHD","DTS-HD MA","DTS","Atmos","DDP","EAC3","AC3","AAC",
    "BluRay REMUX","UHD BluRay","BluRay","WEB-DL","WEBRIP","REMUX","HDTV",
    "24fps","60fps","中字","内封","MKV","MP4","ISO"];
  const cards = Array.from(document.querySelectorAll('li.hd-share-card'));
  return cards.map((el, i) => {
    const txt = el.innerText || '';
    const lines = txt.split('\n').map(s => s.trim()).filter(Boolean);
    const size = (txt.match(/(\d+(?:\.\d+)?\s*(?:GB|TB|MB))/i) || [])[1] || '';
    // 分享于 后两个数字：使用次数、积分
    let cost = 0;
    const di = lines.findIndex(l => /^分享于/.test(l));
    if (di >= 0) {
      const nums = [];
      for (let k = di + 1; k < lines.length && nums.length < 2; k++) {
        if (/^\d+$/.test(lines[k])) nums.push(parseInt(lines[k], 10)); else break;
      }
      cost = nums.length >= 2 ? nums[nums.length - 1] : (nums[0] || 0);
    }
    const chips = Array.from(el.querySelectorAll('.chip')).map(c => (c.innerText || '').trim()).filter(Boolean);
    // 集数：形如「第2季 · 第 4 集」「第2季 · 第 1-9 集」
    const ep = chips.find(c => /第\s*\d+\s*季|第\s*[\d\-]+\s*集/.test(c)) || '';
    // 分享类型
    let kind = '115';
    if (/磁力|magnet/i.test(txt)) kind = 'magnet';
    else if (/ed2k/i.test(txt)) kind = 'ed2k';
    else if (/115/.test(txt)) kind = '115';
    const badges = KEYS.filter(k => txt.indexOf(k) >= 0);
    const btn = el.querySelector('button.share-main-action');
    return {
      i, size, cost, episode: ep, kind,
      button: btn ? (btn.innerText || '').trim() : '',
      badges,
      text: lines.join('|').slice(0, 300),
    };
  });
})()
"""

TABS_JS = r"""
Array.from(document.querySelectorAll('button'))
  .map(function (b, i) { return { i: i, t: (b.innerText || '').replace(/\n/g, ' ').trim() }; })
  .filter(function (x) { return x.t.indexOf('条') >= 0 && /(115|ED2K|磁力|magnet)/i.test(x.t); })
"""


def encode_portal_key(tmdb_id: int | str, media_type: str = "movie", season: int = 0) -> str:
    text = f"1|tmdb|{media_type}|{int(tmdb_id)}|{int(season or 0)}".encode("utf-8")
    raw = bytes(b ^ MASK[i % 4] for i, b in enumerate(text))
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_portal_key(key: str) -> dict:
    raw = bytearray(base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)))
    for i in range(len(raw)):
        raw[i] ^= MASK[i % 4]
    version, source, media_type, tmdb_id, season = raw.decode().split("|")
    return {"version": version, "source": source, "media_type": media_type, "tmdb_id": int(tmdb_id), "season": int(season)}


def _decode_chips(chips: list[str]) -> dict:
    """把页面上的规格标签映射成 tag_decoded（供评分使用）"""
    joined = " ".join(chips).upper()
    res = next((r for r in ("8K", "4K", "1080P", "1080I", "720P", "SD") if r in joined), "")
    source = ""
    for s in ("BLURAY REMUX", "UHD BLURAY", "REMUX", "BLURAY", "WEB-DL", "WEBRIP", "HDTV"):
        if s in joined:
            source = s
            break
    hdr = ""
    for h in ("DOLBY VISION", "HDR10+", "HDR10", "SDR"):
        if h in joined:
            hdr = h
            break
    audio = next((a for a in ("TRUEHD", "DTS-HD MA", "DTS", "ATMOS", "DDP", "EAC3", "AC3", "AAC") if a in joined), "")
    return {
        "resolution": res,
        "source": source,
        "hdr": hdr,
        "audio_codec": audio,
        "has_chinese_subtitle": ("中字" in joined) or ("内封" in joined) or ("CHS" in joined),
    }


class BrowserClient:
    def __init__(self, base_url: str, cdp_host: str, cdp_port: int):
        self.base = (base_url or "https://m.dian115.com").rstrip("/")
        self.host = cdp_host
        self.port = int(cdp_port)

    # ---------- 基础设施 ----------
    def _session(self) -> CDPSession:
        ok, info = browser_reachable(self.host, self.port)
        if not ok:
            raise RuntimeError(f"连不上浏览器 CDP {self.host}:{self.port} · {info}")
        target = find_logged_in_target(self.host, self.port, self.base)
        if not target:
            # 兜底：用配置里的账号密码自动登录
            print("[browser] 没找到已登录标签页，尝试自动登录…", flush=True)
            for t in [x for x in list_targets(self.host, self.port) if x.get("type") == "page" and "dian115.com" in (x.get("url") or "")]:
                try:
                    ss = CDPSession(t["webSocketDebuggerUrl"])
                    ok = self._auto_login(ss)
                    ss.close()
                    if ok:
                        target = find_logged_in_target(self.host, self.port, self.base)
                        if target:
                            break
                except Exception:
                    continue
        if not target:
            raise RuntimeError("影癫未登录：请在 noVNC 里登录，或在设置里填写影癫账号密码")
        s = CDPSession(target["webSocketDebuggerUrl"])
        s.enable_network()
        return s

    def _goto(self, s: CDPSession, path: str, wait: float = 3.0) -> None:
        """导航（带时间戳，避免 SPA 缓存导致不刷新）"""
        url = path if path.startswith("http") else f"{self.base}{path}"
        sep = "&" if "?" in url else "?"
        s.navigate(f"{url}{sep}t={int(time.time() * 1000)}")
        time.sleep(wait)
        cur = s.evaluate("location.href") or ""
        if "/login" in cur:
            raise RuntimeError("影癫登录已失效：请在 noVNC 里重新登录影癫")

    def _wait_cards(self, s: CDPSession, timeout: float = 20.0) -> list[dict]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            cards = s.evaluate(CARD_JS) or []
            if cards:
                return cards
            time.sleep(1.5)
        return []

    def _is_logged_in(self, s: CDPSession) -> bool:
        try:
            return bool(s.evaluate("(() => { const t = document.body ? document.body.innerText : '';"
                                   " return /账号/.test(t) && /\\d{2,}/.test((t.split('账号')[1]||'')); })()"))
        except Exception:
            return False

    def _auto_login(self, s: CDPSession) -> bool:
        """用配置里的影癫账号密码自动登录"""
        import json as _json

        cfg = load_config()
        email = (cfg.get("dian_email") or "").strip()
        pwd = (cfg.get("dian_password") or "").strip()
        if not email or not pwd:
            return False
        try:
            self._goto(s, "/login", 3.0)
            js = (
                "(function(email, pwd) {"
                " const inputs = Array.from(document.querySelectorAll('input'));"
                " const emailEl = inputs.find(function(i){ return i.type === 'email' || /邮箱|email|账号/i.test((i.placeholder||'') + (i.name||'')); }) || inputs[0];"
                " const pwdEl = inputs.find(function(i){ return i.type === 'password'; }) || inputs[1];"
                " if (!emailEl || !pwdEl) return false;"
                " const setV = function(el, v) {"
                "   const st = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value').set;"
                "   st.call(el, v);"
                "   el.dispatchEvent(new Event('input', {bubbles:true}));"
                "   el.dispatchEvent(new Event('change', {bubbles:true}));"
                " };"
                " setV(emailEl, email); setV(pwdEl, pwd);"
                " const btn = Array.from(document.querySelectorAll('button')).find(function(b){ return /登录/.test(b.innerText||'') && !b.disabled; });"
                " if (btn) { btn.click(); return true; } return false;"
                "})(" + _json.dumps(email) + ", " + _json.dumps(pwd) + ")"
            )
            ok = s.evaluate(js)
            if not ok:
                print("[auto-login] 没找到登录表单或登录按钮", flush=True)
                return False
            time.sleep(6)
            logged = self._is_logged_in(s)
            print(f"[auto-login] 结果: {logged}", flush=True)
            return logged
        except Exception as exc:  # noqa: BLE001
            print(f"[auto-login] 异常: {exc}", flush=True)
            return False

    # ---------- 接口 ----------
    def _me(self, payload: dict | None = None) -> dict:
        s = self._session()
        try:
            self._goto(s, "/me", 2.0)
            data = s.wait_json_response("/api/portal/me", timeout=15) or {}
            user = data.get("user") or {}
            if not user:
                # 兜底：从页面文字里读积分
                txt = s.evaluate("document.body ? document.body.innerText : ''") or ""
                m = re.search(r"([\d,]{3,})\s*\n?\s*积分", txt)
                return {"code": "ok", "points": int(m.group(1).replace(",", "")) if m else None}
            return {
                "code": "ok",
                "nickname": user.get("nickname"),
                "points": user.get("points"),
                "vip": user.get("vip"),
                "consecutive_signin": user.get("consecutive_signin"),
                "last_signin_date": user.get("last_signin_date"),
                "raw": data,
            }
        finally:
            s.close()

    def _signin(self, mode: str = "normal") -> dict:
        s = self._session()
        try:
            self._goto(s, "/me/signin", 3.0)
            before = s.evaluate(
                "(() => { const m = (document.body.innerText||'').match(/([\\d,]{3,})\\s*\\n?\\s*积分/);"
                " return m ? parseInt(m[1].replace(/,/g,''),10) : null; })()"
            )
            clicked = s.evaluate(
                "(() => { const bs = Array.from(document.querySelectorAll('button'));"
                " const b = bs.find(x => /签到|立即签到|签 到/.test(x.innerText||'') && !x.disabled);"
                " if (b) { b.click(); return b.innerText.trim(); } return ''; })()"
            )
            if not clicked:
                return {"code": "no_button", "msg": "没找到签到按钮 · 可能今日已签到"}
            data = s.wait_json_response("/api/portal/signin", timeout=20) or {}
            code = str(data.get("code") or "ok")
            out = {"code": code, "raw": data}
            time.sleep(2)
            after = s.evaluate(
                "(() => { const m = (document.body.innerText||'').match(/([\\d,]{3,})\\s*\\n?\\s*积分/);"
                " return m ? parseInt(m[1].replace(/,/g,''),10) : null; })()"
            )
            if before is not None and after is not None and after != before:
                out["points_awarded"] = after - before
                out["points_after"] = after
            if code == "ok":
                out["msg"] = "签到成功" + (f" +{out['points_awarded']} 积分" if out.get("points_awarded") else "")
            elif code == "already_signed":
                out["msg"] = "今日已签到"
            return out
        finally:
            s.close()

    def _list_shares(self, payload: dict) -> dict:
        tmdb_id = payload.get("tmdb_id")
        media_type = payload.get("media_type") or "movie"
        season = int(payload.get("season") or 0)
        if not tmdb_id:
            raise RuntimeError("缺少 tmdb_id")
        key = encode_portal_key(tmdb_id, media_type, season)
        s = self._session()
        try:
            self._goto(s, f"/r/{key}", 4.0)
            self._wait_cards(s)
            # 遍历「115 / ED2K / 磁力」等所有分类标签，收集全部资源
            tabs = s.evaluate(TABS_JS) or []
            if not tabs:
                tabs = [{"t": "115 网盘分享"}, {"t": "ED2K 离线链接"}, {"t": "磁力 magnet"}]
            all_cards = []
            seen = set()
            for tab in tabs:
                label = (tab.get("t") or "")
                # 用文字点击，避免页面重渲染后按钮索引失效
                key = "磁力" if ("磁力" in label or "magnet" in label.lower()) else ("ED2K" if "ed2k" in label.lower() else "115")
                ok = s.evaluate(
                    "((kw) => { const bs = Array.from(document.querySelectorAll('button'));"
                    " const b = bs.find(x => { const t = (x.innerText||'').replace(/\\n/g,' ');"
                    " return t.indexOf(kw) >= 0 && t.indexOf('条') >= 0; });"
                    " if (b) { b.click(); return true; } return false; })(" + repr(key) + ")"
                )
                if not ok:
                    continue
                time.sleep(2.5)
                got = s.evaluate(CARD_JS) or []
                for c in got:
                    sig = f"{key}|{c.get('size')}|{c.get('episode')}|{'|'.join(c.get('badges') or [])}"
                    if sig in seen:
                        continue
                    seen.add(sig)
                    c["kind"] = {"磁力": "magnet", "ED2K": "ed2k"}.get(key, "115")
                    c["_tab"] = label
                    all_cards.append(c)
            cards = all_cards or (s.evaluate(CARD_JS) or [])
            if not cards:
                raise RuntimeError("没有资源卡片 · 资源不存在或未登录")
            title = s.evaluate(
                "(() => { const h = document.querySelector('h1'); return h ? h.innerText.trim() : ''; })()"
            ) or ""
            items = []
            for c in cards:
                chips = c.get("badges") or []
                dec = _decode_chips(chips)
                size = c.get("size") or ""
                sig = f"{size}|{'|'.join(chips)}"
                sid = "dom:" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
                button = (c.get("button") or "").lower()
                items.append(
                    {
                        "share_id": sid,
                        "resource_id": None,
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "tag_raw": ("DT2|" + "|".join(chips)) if chips else "",
                        "tag_decoded": dec,
                        "total_size_human": size,
                        "total_size_bytes": 0,
                        "unlock_cost": int(c.get("cost") or 0),
                        "is_unlocked": ("查看" in button) or ("已解锁" in button),
                        "url_115": "",
                        "has_chinese_subtitle": dec.get("has_chinese_subtitle", False),
                        "use_count": 0,
                        "share_kind": c.get("kind") or "115",
                        "episode": c.get("episode") or "",
                        "created_at": "",
                        "_index": c.get("i"),
                        "index": c.get("i"),
                        "_text": c.get("text", ""),
                    }
                )
            return {"code": "ok", "items": items, "resource": {"title": title, "tmdb_id": tmdb_id, "media_type": media_type}}
        finally:
            s.close()

    def _unlock(self, payload: dict) -> dict:
        """解锁流程：
        1) 资源页 /r/<key> → 点目标卡片的「获取」→ 跳转到分享详情页 /s/<shareKey>
        2) 详情页点「解锁并查看 · N 积分」
        3) 读取页面上的 115 链接
        """
        share_id = str(payload.get("share_id") or "")
        key = payload.get("key") or ""
        index = payload.get("index")
        max_cost = payload.get("max_cost")
        if not key:
            raise RuntimeError("浏览器模式需要资源页 key")

        import time as _t
        t0 = _t.time()

        def _lap(msg):
            print(f"[unlock +{_t.time()-t0:.1f}s] {msg}", flush=True)

        s = self._session()
        try:
            _lap("会话已连接")
            self._goto(s, key if key.startswith("/") else f"/{key}", 3.0)
            cards = self._wait_cards(s)
            _lap(f"资源页已加载，卡片 {len(cards)} 个")
            if not cards:
                raise RuntimeError("页面上没找到资源卡片")

            # 定位目标卡片
            target_idx = None
            for c in cards:
                badges = c.get("badges") or []
                sig = f"{c.get('size') or ''}|{'|'.join(badges)}"
                if "dom:" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12] == share_id:
                    target_idx = c.get("i")
                    break
            if target_idx is None:
                target_idx = int(index) if index is not None else 0

            # 1) 点「获取」→ 跳详情页
            s.evaluate(
                "((i) => { const cards = Array.from(document.querySelectorAll('li.hd-share-card'));"
                " const c = cards[i]; if (!c) return false;"
                " const b = c.querySelector('button.share-main-action'); if (!b) return false;"
                " b.scrollIntoView({block:'center'}); b.click(); return true; })(" + str(target_idx) + ")"
            )

            detail_url = ""
            for _ in range(10):
                time.sleep(0.8)
                cur = s.evaluate("location.href") or ""
                if "/s/" in cur:
                    detail_url = cur
                    break
            if not detail_url:
                body = s.evaluate("document.body ? document.body.innerText : ''") or ""
                if "不存在" in body or "失效" in body:
                    return {"code": "invalid", "msg": "这条分享已失效"}
                return {"code": "pending", "msg": "点了「获取」但没跳到详情页，可能页面结构变化"}

            _lap("已进入分享详情页")
            time.sleep(1.2)

            # 2) 详情页点「解锁并查看 · N 积分」
            btn_info = s.evaluate(
                "(() => { const b = Array.from(document.querySelectorAll('button'))"
                ".find(x => /解锁并查看|解锁/.test(x.innerText || ''));"
                " return b ? {text:(b.innerText||'').trim(), disabled: !!b.disabled} : null; })()"
            )
            if not btn_info:
                return {"code": "no_button", "msg": "没找到解锁按钮 · 可能已解锁或需人工处理"}

            # 已有「查看」说明已解锁过：直接读链接
            text_now = s.evaluate("document.body ? document.body.innerText : ''") or ""
            if "已解锁" in text_now and "解锁并查看" not in (btn_info.get("text") or ""):
                link = s.evaluate(
                    "(() => { const m = (document.body.innerText||'').match(" + repr(LINK_RE).replace("'", '"') + ");"
                    " return m ? m[0] : ''; })()"
                )
                if link:
                    m = re.search(r"password=([A-Za-z0-9]+)", link)
                    return {"code": "ok", "url_115": link, "receive_code": m.group(1) if m else ""}

            # 成本校验
            m_cost = re.search(r"(\d+)\s*积分", btn_info.get("text") or "")
            this_cost = int(m_cost.group(1)) if m_cost else None
            if max_cost is not None and this_cost is not None and this_cost > int(max_cost):
                return {"code": "too_expensive", "msg": f"该资源需 {this_cost} 积分，超过上限 {max_cost}"}

            s.evaluate(
                "(() => { const b = Array.from(document.querySelectorAll('button'))"
                ".find(x => /解锁并查看|解锁/.test(x.innerText || ''));"
                " if (b) { b.click(); return true; } return false; })()"
            )

            # 3) 等链接出现（可能有确认弹窗）
            _lap(f"已点击解锁按钮 {btn_info.get('text')}")
            for _ in range(12):
                time.sleep(1.5)
                # 有确认框就点确认
                s.evaluate(
                    "(() => { const d = document.querySelector('dialog[open], dialog.portal-confirm-dialog');"
                    " const scope = (d && d.open) ? d : document;"
                    " const b = Array.from(scope.querySelectorAll('button'))"
                    ".find(x => /^确认$|^确定$|^解锁$/.test((x.innerText||'').trim()) && !x.disabled);"
                    " if (b) { b.click(); return true; } return false; })()"
                )
                link = s.evaluate(
                    "(() => { const m = (document.body.innerText||'').match(" + repr(LINK_RE).replace("'", '"') + ");"
                    " return m ? m[0] : ''; })()"
                )
                if link:
                    _lap("已读取到 115 链接")
                    m = re.search(r"password=([A-Za-z0-9]+)", link)
                    return {"code": "ok", "url_115": link, "receive_code": m.group(1) if m else ""}

            _lap("轮询结束未读到链接，进入兜底流程")
            body = s.evaluate("document.body ? document.body.innerText : ''") or ""
            if "积分不足" in body:
                return {"code": "no_points", "msg": "积分不足"}
            return {
                "code": "pending",
                "msg": "已点「解锁并查看」但没读到链接——可能弹出人机验证，请在 noVNC 里完成后再试",
            }
        finally:
            s.close()

    # ---------- 带锁的公开接口（浏览器只有一个标签页，必须串行） ----------
    def me(self, payload=None):
        with _BROWSER_LOCK:
            return self._me(payload)

    def signin(self, mode="normal"):
        with _BROWSER_LOCK:
            return self._signin(mode)

    def list_shares(self, payload):
        with _BROWSER_LOCK:
            return self._list_shares(payload)

    def unlock(self, payload):
        with _BROWSER_LOCK:
            return self._unlock(payload)

    def rss(self, payload: dict) -> dict:
        return {"code": "unsupported", "items": [], "has_more": False, "msg": "浏览器模式不支持 RSS，请用「按 TMDB 搜索」"}

    def rss_options(self, payload: dict | None = None) -> dict:
        return {"code": "unsupported", "categories": [], "regions": [], "tags": {}}

