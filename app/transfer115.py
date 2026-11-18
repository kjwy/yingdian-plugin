"""115 直连转存

拿到影癫解锁后的 115 分享链接后，用你自己的 115 Cookie 直接调用 115 网盘接口转存到指定目录。
这样就不需要经过 Telegram / Symedia 的机器人（Symedia 只认真人消息）。

需要的配置：
  d115_cookie  —— 115 网盘 Cookie（UID/CID/SEID/KID 等，浏览器 F12 复制）
  d115_cid     —— 目标目录 id（0 = 根目录；可填某个子目录的 cid）
"""
from __future__ import annotations

import re

import httpx

from .config import load_config

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
API_RECEIVE = "https://webapi.115.com/share/receive"
API_USERINFO = "https://webapi.115.com/user/info"
API_SHARE_SNAP = "https://webapi.115.com/share/snap"
SHARE_URL_RE = re.compile(r"https?://(?:115cdn\.com|115\.com|anxia\.com)/s/[A-Za-z0-9]+(?:\?[^\"'\s<]+)?", re.I)


def parse_115_link(url: str) -> tuple[str, str]:
    """从分享链接里解析 share_code 与提取码"""
    if not url:
        return "", ""
    code = ""
    m = re.search(r"(?:115(?:cdn)?\.com|anxia\.com)/s/([A-Za-z0-9]+)", url)
    if m:
        code = m.group(1)
    pwd = ""
    m2 = re.search(r"[?&](?:password|pwd)=([A-Za-z0-9]+)", url)
    if m2:
        pwd = m2.group(1)
    return code, pwd


def resolve_share_link(url: str, cookie: str | None = None) -> str:
    """解析 re0.me 等中转链接，返回最终 115 分享链接。"""
    current = (url or "").strip()
    if not current:
        return ""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    if parse_115_link(current)[0]:
        return current
    try:
        with httpx.Client(
            timeout=25,
            headers=_headers(cookie) if cookie else {"User-Agent": UA},
            follow_redirects=True,
        ) as client:
            response = client.get(current)
            final_url = str(response.url)
            if parse_115_link(final_url)[0]:
                return final_url
            match = SHARE_URL_RE.search(response.text or "")
            if match:
                return match.group(0)
    except Exception:
        pass
    return current


def inspect_share(link: str, cookie: str | None = None) -> dict:
    """读取 115 分享内的文件名和集数。"""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    resolved = resolve_share_link(link, cookie)
    share_code, pwd = parse_115_link(resolved)
    if not share_code:
        return {"ok": False, "message": "无法解析 115 分享链接", "episodes": [], "files": [], "items": []}
    filenames: list[str] = []
    file_items: list[dict] = []
    title = ""
    queue = ["0"]
    seen = set()
    try:
        with httpx.Client(timeout=30, headers=_headers(cookie), follow_redirects=True) as client:
            while queue and len(seen) < 80:
                cid = str(queue.pop(0))
                if cid in seen:
                    continue
                seen.add(cid)
                response = client.get(API_SHARE_SNAP, params={
                    "share_code": share_code,
                    "receive_code": pwd,
                    "offset": 0,
                    "limit": 200,
                    "cid": cid,
                })
                data = response.json()
                if not data.get("state"):
                    return {
                        "ok": False,
                        "message": data.get("error") or "115 分享读取失败",
                        "episodes": [], "files": [], "items": [],
                    }
                payload = data.get("data") or {}
                title = title or (payload.get("shareinfo") or {}).get("share_title") or ""
                for item in payload.get("list") or []:
                    name = str(item.get("n") or "")
                    is_folder = int(item.get("fc") or 0) == 0 and item.get("cid")
                    if is_folder:
                        queue.append(str(item["cid"]))
                    elif name:
                        filenames.append(name)
                        file_items.append({
                            "name": name,
                            "id": str(item.get("fid") or item.get("cid") or ""),
                        })
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"读取 115 分享失败：{exc}", "episodes": [], "files": [], "items": []}

    episodes: set[int] = set()
    for name in filenames:
        for episode in re.findall(r"(?i)S\d{1,3}E(\d{1,4})", name):
            episodes.add(int(episode))
        if not re.search(r"(?i)S\d{1,3}E\d{1,4}", name):
            for episode in re.findall(r"(?i)(?:^|[.\s_-])E(\d{1,4})(?:[.\s_-]|$)", name):
                episodes.add(int(episode))
            for episode in re.findall(r"第\s*(\d{1,4})\s*集", name):
                episodes.add(int(episode))
    for item in file_items:
        name = item["name"]
        item_episodes = set()
        for episode in re.findall(r"(?i)S\d{1,3}E(\d{1,4})", name):
            item_episodes.add(int(episode))
        if not re.search(r"(?i)S\d{1,3}E\d{1,4}", name):
            item_episodes.update(
                int(x) for x in re.findall(r"(?i)(?:^|[.\s_-])E(\d{1,4})(?:[.\s_-]|$)", name)
            )
            item_episodes.update(int(x) for x in re.findall(r"第\s*(\d{1,4})\s*集", name))
        item["episodes"] = sorted(item_episodes)
    return {
        "ok": True,
        "resolved_url": resolved,
        "title": title,
        "episodes": sorted(episodes),
        "files": filenames,
        "items": file_items,
        "message": f"读取到 {len(filenames)} 个文件、{len(episodes)} 集",
    }


def receive_file_ids(
    link: str,
    file_ids: list[str],
    cookie: str | None = None,
    cid: str | None = None,
) -> tuple[bool, str]:
    """只转存 115 分享中的指定文件。"""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    cid = str(cid if cid is not None else (cfg.get("d115_cid") or "0")).strip() or "0"
    file_ids = [str(x) for x in file_ids if str(x)]
    if not cookie:
        return False, "未配置 115 Cookie"
    if not file_ids:
        return False, "没有需要转存的新文件"
    link = resolve_share_link(link, cookie)
    share_code, pwd = parse_115_link(link)
    if not share_code:
        return False, "无法解析 115 分享码"
    user_id = ""
    match = re.search(r"(?:^|;\s*)UID=(\d+)", cookie)
    if match:
        user_id = match.group(1)
    data = {
        "share_code": share_code,
        "receive_code": pwd,
        "file_id": ",".join(file_ids),
        "cid": cid,
    }
    if user_id:
        data["user_id"] = user_id
    try:
        with httpx.Client(timeout=30, headers=_headers(cookie), follow_redirects=True) as client:
            response = client.post(API_RECEIVE, data=data)
            result = response.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"选择性转存失败：{type(exc).__name__}: {exc}"
    if result.get("state"):
        return True, f"已转存 {len(file_ids)} 个新增文件 · cid={cid}"
    message = result.get("error") or result.get("message") or str(result)[:160]
    if "无需重复接收" in message or "已接收" in message:
        return True, "新增文件已转存过"
    return False, f"115 返回失败：{message}"


def _headers(cookie: str) -> dict:
    return {
        "Cookie": cookie.strip(),
        "User-Agent": UA,
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
    }


def check(cookie: str | None = None) -> tuple[bool, str]:
    """检查 Cookie 是否有效"""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    if not cookie:
        return False, "未填写 115 Cookie"
    try:
        with httpx.Client(timeout=20, headers=_headers(cookie), follow_redirects=True) as c:
            r = c.get(API_USERINFO)
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"请求 115 失败：{type(exc).__name__}: {exc}"
    if data.get("state"):
        info = data.get("data")
        name = info if isinstance(info, str) else (info or {}).get("user_name", "已登录")
        return True, f"115 Cookie 有效 · {name}"
    msg = data.get("error") or data.get("message") or str(data)[:120]
    return False, f"115 Cookie 无效或已过期：{msg}"


def receive(link: str, cookie: str | None = None, cid: str | None = None) -> tuple[bool, str]:
    """把一个 115 分享转存到自己的网盘"""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    cid = str(cid if cid is not None else (cfg.get("d115_cid") or "0")).strip() or "0"
    if not cookie:
        return False, "未配置 115 Cookie"

    link = resolve_share_link(link, cookie)
    share_code, pwd = parse_115_link(link)
    if not share_code:
        return False, f"无法从链接解析出 115 分享码：{link[:60]}"

    data = {"cid": cid, "share_code": share_code, "receive_code": pwd}
    try:
        with httpx.Client(timeout=30, headers=_headers(cookie), follow_redirects=True) as c:
            r = c.post(API_RECEIVE, data=data)
            res = r.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"转存请求失败：{type(exc).__name__}: {exc}"

    if res.get("state"):
        return True, f"已转存到 115 · share_code={share_code} · cid={cid}"
    err = res.get("error") or res.get("message") or str(res)[:160]
    return False, f"115 返回失败：{err}"



API_FILES = "https://webapi.115.com/files"


def list_folders(cid: str = "0", cookie: str | None = None) -> tuple[bool, list[dict], str]:
    """列出某个目录下的子文件夹（用于选择转存目标目录）"""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    if not cookie:
        return False, [], "未配置 115 Cookie"
    params = {"aid": 1, "cid": str(cid or "0"), "o": "user_ptime", "asc": 0,
              "offset": 0, "show_icon": 1, "limit": 200}
    try:
        with httpx.Client(timeout=25, headers=_headers(cookie), follow_redirects=True) as c:
            r = c.get(API_FILES, params=params)
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        return False, [], f"请求 115 失败：{type(exc).__name__}: {exc}"
    if not data.get("state") and not data.get("data"):
        return False, [], f"115 返回：{data.get('error') or data}"
    folders = [
        {"cid": str(x.get("cid")), "name": x.get("n") or ""}
        for x in (data.get("data") or [])
        if x.get("cid")
    ]
    return True, folders, ""


API_OFFLINE = "https://webapi.115.com/offline/add_task_urls"


def is_offline_link(link: str) -> bool:
    """ED2K / 磁力 走 115 离线下载"""
    low = (link or "").lower()
    return low.startswith("ed2k://") or low.startswith("magnet:")


def add_offline(link: str, cookie: str | None = None, wp_path_id: str | None = None) -> tuple[bool, str]:
    """把 ED2K / 磁力 链接加入 115 离线下载"""
    cfg = load_config()
    cookie = (cookie if cookie is not None else cfg.get("d115_cookie", "")).strip()
    wp_path_id = str(wp_path_id if wp_path_id is not None else (cfg.get("d115_cid") or "0")).strip() or "0"
    if not cookie:
        return False, "未配置 115 Cookie"
    if not is_offline_link(link):
        return False, "不是 ED2K/磁力 链接"
    try:
        with httpx.Client(timeout=30, headers=_headers(cookie), follow_redirects=True) as c:
            r = c.post(API_OFFLINE, data={"urls[]": link, "wp_path_id": wp_path_id})
            res = r.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"离线请求失败：{type(exc).__name__}: {exc}"
    if res.get("state"):
        return True, f"已添加 115 离线下载 · 目录 {wp_path_id}"
    err = res.get("error") or res.get("message") or str(res)[:160]
    return False, f"115 离线返回失败：{err}"
