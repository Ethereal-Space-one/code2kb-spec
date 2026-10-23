"""Compare answerable-topic coverage when moving from full to compact authoring."""

from __future__ import annotations

import re


UNKNOWN = ("未知", "不能确定", "未验证", "待确认", "不清楚")


def topic_key(unit: dict) -> tuple[str, str, str]:
    meta = unit["meta"]
    topic = re.sub(r"\s+", "", meta["topic"].casefold())
    return meta["audience"], meta["module_id"], topic


def unknown_lines(unit: dict) -> set[str]:
    return {
        re.sub(r"\s+", "", line.strip().casefold())
        for line in unit["body"].splitlines()
        if any(word in line for word in UNKNOWN)
    }


def compare(full_units: dict[str, dict], compact_units: dict[str, dict]) -> dict:
    """Conservative mechanical comparison; it cannot certify semantic equivalence."""
    full = {topic_key(unit): unit for unit in full_units.values()}
    compact = {topic_key(unit): unit for unit in compact_units.values()}
    missing_topics = sorted(full.keys() - compact.keys())
    missing_unknowns = []
    for key in sorted(full.keys() & compact.keys()):
        if unknown_lines(full[key]) and not unknown_lines(compact[key]):
            missing_unknowns.append(key)
    return {
        "full_topics": len(full), "compact_topics": len(compact),
        "missing_topics": [list(item) for item in missing_topics],
        "missing_unknown_boundaries": [list(item) for item in missing_unknowns],
        "passed": not missing_topics and not missing_unknowns,
        "warning": "仅比较主题身份与未知边界存在性；仍须人工核对条件、结论和例外的语义一致性",
    }
