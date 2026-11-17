"""资源评分与入库集数覆盖判断。"""
from __future__ import annotations

import re

RES_SCORE = {"8K": 100, "4K": 90, "2160P": 90, "1080P": 60, "1080I": 55, "720P": 35, "SD": 10}
SOURCE_SCORE = {
    "REMUX": 40, "BLURAY REMUX": 40, "UHD BLURAY": 36, "BLURAY": 28,
    "WEB-DL": 24, "WEBRIP": 18, "HDTV": 10,
}
HDR_SCORE = {"DOLBY VISION": 16, "DV": 16, "HDR10+": 12, "HDR10": 10, "HDR": 8, "SDR": 0}
AUDIO_SCORE = {"TRUEHD": 10, "ATMOS": 8, "DTS-HD MA": 8, "DDP": 5, "DTS": 4, "EAC3": 4, "AC3": 3, "AAC": 2}


def parse_episode_numbers(text: str) -> set[int]:
    """从资源标签中解析集数，支持第 1-9 集、第 3 集、E01-E09 等写法。"""
    if not text:
        return set()
    out: set[int] = set()
    for start, end in re.findall(r"第\s*(\d+)\s*(?:[-~至]\s*(\d+))?\s*集", text):
        first = int(start)
        last = int(end) if end else first
        if 0 < first <= last <= 2000:
            out.update(range(first, last + 1))
    for start, end in re.findall(r"(?<![A-Z0-9])E(\d{1,4})(?:\s*[-~]\s*E?(\d{1,4}))?", text, re.I):
        first = int(start)
        last = int(end) if end else first
        if 0 < first <= last <= 2000:
            out.update(range(first, last + 1))
    return out


def parse_season_number(text: str) -> int | None:
    """从标签中解析季号；没有季号时返回 None。"""
    if not text:
        return None
    m = re.search(r"第\s*(\d+)\s*季", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<![A-Z0-9])S(\d{1,3})(?=E|\b)", text, re.I)
    return int(m.group(1)) if m else None


def parse_episode_range(ep: str) -> tuple[int, int]:
    """兼容旧接口：返回解析结果中的最小集和最大集。"""
    nums = parse_episode_numbers(ep)
    return (min(nums), max(nums)) if nums else (0, 0)


def episode_count(ep: str) -> int:
    return len(parse_episode_numbers(ep))


def format_episode_numbers(numbers: set[int] | list[int] | tuple[int, ...]) -> str:
    """把集数格式化成 1-2,5,7-9。"""
    values = sorted({int(x) for x in numbers if int(x) > 0})
    if not values:
        return ""
    parts: list[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def score_share(item: dict, for_tv: bool = False) -> int:
    td = item.get("tag_decoded") or {}
    raw = (item.get("tag_raw") or "").upper()
    score = 0

    res = str(td.get("resolution") or "").upper()
    score += RES_SCORE.get(res, 0)
    src = str(td.get("source") or "").upper()
    score += SOURCE_SCORE.get(src, 0)
    if not src:
        for key, value in SOURCE_SCORE.items():
            if key in raw:
                score += value
                break
    hdr = str(td.get("hdr") or "").upper()
    score += HDR_SCORE.get(hdr, 8 if "HDR" in raw else 0)
    audio = str(td.get("audio_codec") or "").upper()
    score += AUDIO_SCORE.get(audio, 0)
    if item.get("has_chinese_subtitle") or "中字" in raw or "内封" in raw:
        score += 12

    if for_tv:
        count = int(item.get("episode_count") or episode_count(item.get("episode") or ""))
        if count >= 2:
            score += min(count, 30) * 5
        elif count == 1:
            score -= 25
        if "全集" in raw or "COMPLETE" in raw:
            score += 20

    try:
        score += min(int(item.get("use_count") or 0), 20)
    except Exception:
        pass
    try:
        size = int(item.get("total_size_bytes") or 0)
        if size and not for_tv:
            score += min(size // (1024 ** 3), 10)
    except Exception:
        pass
    if (item.get("share_kind") or "115") != "115":
        score -= 15
    return score


def annotate_library(
    items: list[dict],
    status: dict | None,
    requested_season: int = 0,
    pending: list[dict] | None = None,
    combine_pending: bool = False,
    respect_pending: bool = False,
) -> list[dict]:
    """给候选资源标注已入库集数、可补齐集数和是否值得解锁。"""
    seasons = (status or {}).get("seasons") or {}
    pending_rows = pending or []
    pending_by_season_cloud: dict[tuple[int, str], set[int]] = {}
    for row in pending_rows:
        season_no = int(row.get("season") or 0)
        cloud = str(row.get("cloud_type") or "115").lower()
        pending_by_season_cloud.setdefault((season_no, cloud), set()).update(
            parse_episode_numbers(row.get("episode") or "")
        )

    for item in items:
        episode_text = item.get("episode") or ""
        episodes = parse_episode_numbers(episode_text)
        season_no = parse_season_number(episode_text)
        if season_no is None and requested_season:
            season_no = int(requested_season)

        item["episode_numbers"] = sorted(episodes)
        item["episode_count"] = len(episodes)
        item["season_number"] = season_no or 0
        item["library_checked"] = bool((status or {}).get("checked"))
        item["library_exists"] = bool((status or {}).get("exists"))
        item["in_library"] = False
        item["already_complete"] = False
        item["coverage_status"] = "unknown"
        item["new_episode_count"] = 0
        item["new_episodes"] = []
        item["new_episodes_text"] = ""
        item["previously_obtained"] = False

        if not status or not status.get("checked") or not status.get("exists"):
            continue

        if status.get("media_type") == "movie":
            item["in_library"] = True
            item["already_complete"] = True
            item["coverage_status"] = "complete"
            continue

        if season_no and str(season_no) in seasons:
            available = set(seasons[str(season_no)].get("available") or [])
        elif requested_season and str(requested_season) in seasons:
            season_no = int(requested_season)
            item["season_number"] = season_no
            available = set(seasons[str(season_no)].get("available") or [])
        else:
            available = set(status.get("available") or [])

        cloud_type = str(item.get("share_kind") or "115").lower()
        if combine_pending:
            pending_eps = set()
            for (pending_season, _pending_cloud), values in pending_by_season_cloud.items():
                if pending_season == int(season_no or 0):
                    pending_eps.update(values)
        else:
            pending_eps = pending_by_season_cloud.get((int(season_no or 0), cloud_type), set())
        item["library_available"] = sorted(available)
        item["library_available_text"] = format_episode_numbers(available)
        item["pending_episode_numbers"] = sorted(pending_eps)
        item["pending_episodes_text"] = format_episode_numbers(pending_eps)
        effective_pending = pending_eps if (respect_pending or cloud_type == "115") else set()
        item["pending_overlap_count"] = len(episodes & effective_pending)
        item["previously_obtained"] = bool(episodes & pending_eps)
        item["in_library"] = bool(episodes and episodes.issubset(available))

        if not episodes:
            continue

        new_episodes = episodes - available - effective_pending
        item["new_episodes"] = sorted(new_episodes)
        item["new_episode_count"] = len(new_episodes)
        item["new_episodes_text"] = format_episode_numbers(new_episodes)
        item["already_complete"] = not new_episodes
        item["coverage_status"] = "partial" if new_episodes else "complete"

    return items


def rank_shares(items: list[dict], for_tv: bool = False, skip_complete: bool = True) -> list[dict]:
    """剧集优先补齐缺失集数，其次比较完整度和画质。"""
    def key(item: dict):
        score = score_share(item, for_tv)
        if for_tv:
            has_known_new = bool(item.get("library_checked"))
            new_count = int(item.get("new_episode_count") or 0)
            pending_overlap = int(item.get("pending_overlap_count") or 0)
            count = int(item.get("episode_count") or 0)
            has_episodes = 1 if count else 0
            has_new = 1 if (not has_known_new or new_count > 0) else 0
            try:
                cost = int(item.get("unlock_cost") or 0)
            except Exception:
                cost = 0
            return (has_new, -pending_overlap, new_count, has_episodes, count, -cost, score)
        return (score,)

    return sorted(items, key=key, reverse=True)
