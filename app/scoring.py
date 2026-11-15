"""分享评分：清晰度 / 片源 / HDR / 字幕 / 热度 / 体积"""
from __future__ import annotations

RES_SCORE = {"8K": 90, "4K": 80, "1080P": 60, "1080I": 55, "720P": 40, "SD": 20}
SOURCE_SCORE = {"REMUX": 40, "BLURAY-REMUX": 38, "WEB-DL": 30, "BLURAY": 26, "WEBRIP": 22, "HDTV": 12}
HDR_SCORE = {"Dolby Vision": 16, "DV": 16, "HDR10+": 12, "HDR10": 8, "SDR": 0}


def score_share(item: dict) -> int:
    tag = item.get("tag_decoded") or {}
    score = 0
    score += RES_SCORE.get(str(tag.get("resolution", "")).upper(), 0)
    score += SOURCE_SCORE.get(str(tag.get("source", "")).upper(), 0)
    hdr = str(tag.get("hdr", ""))
    score += HDR_SCORE.get(hdr, 8 if "HDR" in hdr.upper() else 0)
    if item.get("has_chinese_subtitle"):
        score += 10
    try:
        score += min(int(item.get("use_count") or 0), 20)
    except Exception:
        pass
    if item.get("share_kind") == "offline":
        score -= 8
    return score


def rank_shares(items: list[dict]) -> list[dict]:
    return sorted(items, key=score_share, reverse=True)
