"""Read registered UniApp routes from one configured Git snapshot."""

from __future__ import annotations

import json
import subprocess


def read_uniapp_pages(repository: dict[str, str], manifest_path: str) -> set[str]:
    result = subprocess.run(
        ["git", "-C", repository["path"], "show", f"{repository['commit']}:{manifest_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise ValueError(f"固定提交中找不到 UniApp 页面清单：{manifest_path}")
    try:
        manifest = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{manifest_path} 不是标准 JSON，需配置适配后的清单") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("pages"), list):
        raise ValueError(f"{manifest_path} 缺少 pages 列表")
    routes: set[str] = set()
    packages = [{"root": "", "pages": manifest["pages"]}]
    packages.extend(manifest.get("subPackages", []))
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("pages"), list):
            raise ValueError(f"{manifest_path} 的分包结构无效")
        root = str(package.get("root", "")).strip("/")
        for page in package["pages"]:
            if not isinstance(page, dict) or not isinstance(page.get("path"), str) or not page["path"]:
                raise ValueError(f"{manifest_path} 存在缺少 path 的页面")
            routes.add(f"{root}/{page['path']}".strip("/"))
    return routes
