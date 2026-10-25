"""In-memory example of replacing an audited retrieval snapshot for one audience."""

from __future__ import annotations


class SnapshotError(ValueError):
    pass


def _keys(manifest: dict, audience: str) -> set[tuple[str, str, str]]:
    release_id = manifest.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise SnapshotError("检索清单缺少发布身份")
    units = manifest.get("units")
    if not isinstance(units, list):
        raise SnapshotError("检索清单缺少单元目录")
    keys = set()
    for item in units:
        if not isinstance(item, dict) or item.get("audience") not in {"business", "engineering"} or not isinstance(item.get("unit_id"), str):
            raise SnapshotError("检索单元目录无效")
        if item["audience"] == audience:
            key = (release_id, audience, item["unit_id"])
            if key in keys:
                raise SnapshotError("检索单元身份重复")
            keys.add(key)
    return keys


def plan(old: dict, new: dict, audience: str) -> dict:
    """Return a versioned replacement plan; callers audit both manifests first."""
    if audience not in {"business", "engineering"}:
        raise SnapshotError("检索受众无效")
    if old.get("release_id") == new.get("release_id"):
        raise SnapshotError("新旧检索快照须使用不同发布身份")
    old_keys, new_keys = _keys(old, audience), _keys(new, audience)
    # An audited release may intentionally remove every unit for an audience.
    # Switching to an empty set retires that audience's stale searchable content.
    return {
        "audience": audience, "old_release_id": old["release_id"],
        "new_release_id": new["release_id"],
        "stage_keys": sorted(new_keys), "retire_keys": sorted(old_keys),
    }


def simulate_switch(old: dict, new: dict, audience: str, *, fail_before_switch: bool = False) -> dict:
    """Stage a complete new set before changing the active pointer."""
    change = plan(old, new, audience)
    snapshots = {change["old_release_id"]: set(change["retire_keys"])}
    active = change["old_release_id"]
    staged = set(change["stage_keys"])
    if not fail_before_switch:
        snapshots[change["new_release_id"]] = staged
        active = change["new_release_id"]
    return {"active_release_id": active, "active_keys": sorted(snapshots[active]),
            "old_snapshot_preserved": change["old_release_id"] in snapshots}
