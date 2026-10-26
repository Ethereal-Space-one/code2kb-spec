"""Conservative source-repository URL detection for business knowledge."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit


URL = re.compile(r"https?://[^\s<>\[\]()]+", re.IGNORECASE)
CODE_HOSTS = frozenset({
    "github.com", "gitlab.com", "gitee.com", "bitbucket.org", "codeberg.org",
    "codeup.aliyun.com",
})
SOURCE_VIEW = re.compile(
    r"(?:/[^/]+){2}/(?:-/)?(?:blob|commit|tree)/[0-9a-f]{7,40}(?:/|$)",
    re.IGNORECASE,
)


def contains_source_repository_url(text: str) -> bool:
    """Detect clear repository links, leaving ordinary business URLs alone."""
    for match in URL.finditer(text):
        parsed = urlsplit(match.group().rstrip(".,;:!?，。；：！？"))
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = unquote(parsed.path)
        components = [item for item in path.split("/") if item]
        if host in CODE_HOSTS and len(components) >= 2:
            return True
        if SOURCE_VIEW.search(path):
            return True
    return False
