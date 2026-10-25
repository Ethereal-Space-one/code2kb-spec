"""Explicitly registered inventory adapters; no project code is auto-loaded."""

from __future__ import annotations


ADAPTER_NAMES = ("builtin-mixed", "universal-l1")


def get_adapter(name: str):
    from .platform import BuiltinMixedAdapter, UniversalL1Adapter

    registry = {"builtin-mixed": BuiltinMixedAdapter, "universal-l1": UniversalL1Adapter}
    if name not in registry:
        raise ValueError(f"未知内置 Adapter：{name}")
    return registry[name]()
