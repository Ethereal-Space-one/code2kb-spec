"""Conservative source-repository URL detection for business knowledge."""

from __future__ import annotations

from html import unescape
import re
from urllib.parse import unquote, urlsplit


URL = re.compile(r"https?://[^\s<>\[\]()]+", re.IGNORECASE)
CODE_HOSTS = frozenset({
    "github.com", "gitlab.com", "gitee.com", "bitbucket.org", "codeberg.org",
    "codeup.aliyun.com",
})
CODE_HOST_PREFIXES = ("git.", "gitlab.", "github.", "gitea.", "code.", "scm.", "bitbucket.")
SOURCE_VIEW = re.compile(
    r"(?:/[^/]+){2}/(?:-/)?(?:blob|commit|tree)/[0-9a-f]{7,64}(?:/|$)",
    re.IGNORECASE,
)


def contains_source_repository_url(text: str) -> bool:
    """Detect clear repository links, leaving ordinary business URLs alone."""
    # Markdown resolves character references in link destinations before navigation.
    for match in URL.finditer(unescape(text)):
        parsed = urlsplit(match.group().rstrip(".,;:!?，。；：！？"))
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = unquote(parsed.path)
        components = [item for item in path.split("/") if item]
        if (host in CODE_HOSTS or host.startswith(CODE_HOST_PREFIXES)) and len(components) >= 2:
            return True
        if SOURCE_VIEW.search(path):
            return True
    return False
