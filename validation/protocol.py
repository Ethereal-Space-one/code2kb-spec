"""Public knowledge-file compatibility identifiers and their capabilities.

The new identifier is a rename of the existing file contract, not a change to
its required fields or review semantics. Keep both identifiers readable.
"""

from __future__ import annotations


DEFAULT_VERSION = "c2kb-file/1"
LEGACY_VERSION = "0.8.3"
SUPPORTED_VERSIONS = frozenset({DEFAULT_VERSION, LEGACY_VERSION})


def supports(version: object, capability: str) -> bool:
    """Require a known format before checking a format-level capability."""
    if not isinstance(version, str) or version not in SUPPORTED_VERSIONS:
        return False
    return capability in {"business_intent", "business_evidence", "intent_included", "registry_2"}
