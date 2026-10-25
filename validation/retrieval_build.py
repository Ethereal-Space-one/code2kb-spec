"""Derive topic-sized retrieval units from an audited supported release."""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote

try:
    from .retrieval_model import AUDIENCES, SCHEMA, RetrievalError, digest, inventory, json_bytes, read_unit, render_unit, strict_json
except ImportError:
    from retrieval_model import AUDIENCES, SCHEMA, RetrievalError, digest, inventory, json_bytes, read_unit, render_unit, strict_json


SOURCE_ORDER = {
    "business": ("常见问答.md", "规则与限制.md", "模块概览.md", "功能与范围.md", "业务流程.md", "业务意图.md"),
    "engineering": ("技术实现.md", "接口与调用.md", "方法与源码.md"),
}


def project_profile(project: Path) -> str:
    path = project / "Code2KB工程配置.json"
    if not path.exists():
        return "full"
    value = strict_json(path)
    if set(value) != {"schema_version", "content_profile"} or value["schema_version"] != "0.1" or value["content_profile"] not in {"full", "compact"}:
        raise RetrievalError("工程配置 profile 无效")
    return value["content_profile"]


def metadata_candidates(docs) -> dict[str, str]:
    """Conservative source-backed suggestions for compatible manifest fields."""
    result = {}
    for audience in AUDIENCES:
        allowed = SOURCE_ORDER[audience]
        selected = [doc for doc in docs if doc.relative.name in allowed and doc.meta.get("applicability") == "current"]
        topics = []
        questions = []
        unknowns = []
        for doc in sorted(selected, key=lambda item: allowed.index(item.relative.name)):
            for title, content in sections(doc.body, doc.relative.name):
                if title not in topics and title not in {"说明", "目录", "接口索引", "方法索引"}:
                    topics.append(title)
                if doc.relative.name == "常见问答.md":
                    questions.append(question_variants(title))
                for line in content.splitlines():
                    line = line.strip().strip("-* ")
                    if any(term in line for term in ("未知", "不能确定", "未验证", "待确认")) and line and line not in unknowns:
                        unknowns.append(line)
            if not topics:
                heading = re.search(r"(?m)^#\s+(.+)$", doc.body)
                if heading:
                    topics.append(heading[1].strip())
        if audience == "engineering" and not selected:
            continue
        def joined(values):
            return "、".join(re.sub(r"[\r\n|]", " ", value).strip() for value in values[:3] if value).strip()[:180]
        result[f"{audience}_topics"] = joined(topics)
        result[f"{audience}_keywords"] = joined(questions or topics)
        result[f"{audience}_unknowns"] = joined(unknowns)
    return result
HEADING = re.compile(r"(?m)^#{2,4}\s+(.+?)\s*$")
FIRST_HEADING = re.compile(r"(?m)^#\s+(.+?)\s*$")
FACT = re.compile(r"(?<![\w.-])(?:F-[0-9]+[a-z]?|FACT-[0-9]+)(?![\w-])")
LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
GENERIC_TITLES = {"说明", "概述", "适用条件", "已确认的适用条件", "主流程", "分支与失败", "回答边界", "尚不能确定的结果", "平台与角色差异"}
SHARED_CONTEXT_TITLES = {"适用条件", "已确认的适用条件", "回答边界", "尚不能确定的结果"}


def sections(body: str, filename: str):
    all_headings = list(HEADING.finditer(body))
    matches = []
    for match in all_headings:
        level = len(match[0]) - len(match[0].lstrip("#"))
        title = match[1].strip()
        is_question = bool(re.match(r"(?:问|Q\d*)[:：]|.*[？?]$", title, flags=re.I))
        is_technical_detail = filename in {"接口与调用.md", "方法与源码.md"} and bool(re.fullmatch(r"(?:API|METHOD)-[A-Za-z0-9-]+", title))
        if level == 2 or (level == 3 and (is_question or is_technical_detail)):
            matches.append(match)
    if not matches and all_headings:
        matches = [match for match in all_headings if len(match[0]) - len(match[0].lstrip("#")) == 3]
    for index, match in enumerate(matches):
        title = match[1].strip().strip("：:")
        content = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)].strip()
        if not content or title in {"目录", "事实编号对照", "索引", "接口索引", "方法索引"}:
            continue
        # Nested headings carry the enclosing topic; do not turn an empty heading into a unit.
        yield title, content
    if not matches and body.strip():
        content = re.sub(r"\A# .+\n", "", body).strip()
        if content:
            yield filename.removesuffix(".md"), content


def index_sections(body: str, filename: str) -> list[tuple[str, str, list[str]]]:
    """Keep source heading identities while preserving shared answer boundaries."""
    original = list(sections(body, filename))
    if not original:
        return []
    headings = [match[1].strip().strip("：:") for match in HEADING.finditer(body)]
    if any(title in SHARED_CONTEXT_TITLES for title in headings):
        # A rule or exception in a sibling section cannot safely be assigned to
        # one answer by a lexical parser. Keep the whole source instead.
        title_match = FIRST_HEADING.search(body)
        title = title_match[1].strip() if title_match else filename.removesuffix(".md")
        return [(title, body.strip(), list(dict.fromkeys(headings)))]
    selected = []
    for match in HEADING.finditer(body):
        level = len(match[0]) - len(match[0].lstrip("#"))
        title = match[1].strip().strip("：:")
        is_question = bool(re.match(r"(?:问|Q\d*)[:：]|.*[？?]$", title, flags=re.I))
        is_detail = filename in {"接口与调用.md", "方法与源码.md"} and bool(re.fullmatch(r"(?:API|METHOD)-[A-Za-z0-9-]+", title))
        if level == 2 or (level == 3 and (is_question or is_detail)):
            selected.append((match, level, title))
    if not selected:
        return [(title, content, [title]) for title, content in original]
    results = []
    # Text before the first section applies to every extracted answer as well.
    document_intro = FIRST_HEADING.sub("", body[:selected[0][0].start()], count=1).strip()
    parent_title = ""
    parent_intro = ""
    for index, (match, level, title) in enumerate(selected):
        end = selected[index + 1][0].start() if index + 1 < len(selected) else len(body)
        content = body[match.end():end].strip()
        if level == 2:
            parent_title, parent_intro = title, content
            has_children = index + 1 < len(selected) and selected[index + 1][1] == 3
            if content and not has_children and title not in {"目录", "事实编号对照", "索引", "接口索引", "方法索引"}:
                combined = f"{document_intro}\n\n{content}" if document_intro else content
                results.append((title, combined, [title]))
        elif content:
            combined = "\n\n".join(part for part in (document_intro, parent_intro, content) if part)
            names = [parent_title, title] if parent_title else [title]
            display = f"{parent_title} · {title}" if parent_title else title
            results.append((display, combined, names))
    return results


def readable_module_title(body: str, filename: str) -> str:
    match = FIRST_HEADING.search(body)
    if not match:
        return filename.removesuffix(".md")
    title = match[1].strip()
    suffix = filename.removesuffix(".md")
    for separator in ("：", ":", "·", "-"):
        ending = separator + suffix
        if title.endswith(ending):
            return title[: -len(ending)].strip()
    return title


def question_variants(title: str) -> str:
    text = re.sub(r"^(?:问|Q\d*)[:：]\s*", "", title, flags=re.I).strip()
    return text


def clean_title(title: str) -> str:
    return re.sub(r"[\r\n|]", " ", title).strip()[:160]


def rewrite_links(content: str, source: Path, destination: Path) -> str:
    def rewrite(match):
        target = match[2]
        if target.startswith(("http://", "https://", "mailto:")):
            return match[0]
        if target.startswith("#"):
            relative = os.path.relpath(source, destination.parent).replace(os.sep, "/")
            return f"[{match[1]}]({relative}{target})"
        source_target = (source.parent / unquote(target.split("#", 1)[0])).resolve()
        if not source_target.is_file():
            return match[0]
        relative = os.path.relpath(source_target, destination.parent).replace(os.sep, "/")
        fragment = "#" + target.split("#", 1)[1] if "#" in target else ""
        return f"[{match[1]}]({relative}{fragment})"
    return LINK.sub(rewrite, content)


def source_meta(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    pieces = text.split("---\n", 2)
    if len(pieces) != 3 or pieces[0] != "":
        raise RetrievalError(f"发布正文 front matter 无效：{path}")
    meta = {}
    for line in pieces[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, pieces[2]


def build_in_release(release_root: Path, release_id: str, profile: str, generated_by: dict, business_scanner=None) -> dict:
    """Write a retrieval extension into a *staging* release root.

    The caller is responsible for first auditing the base release and for atomically
    installing this root. No existing retrieval extension is overwritten in place.
    """
    if profile not in {"full", "compact"}:
        raise RetrievalError("profile 只能是 full 或 compact")
    pointer = strict_json(release_root / "当前版本.json")
    if pointer.get("release_id") != release_id:
        raise RetrievalError("只能为当前基础发布构建检索扩展")
    registry_local = pointer.get("registry_path")
    if registry_local != f"发布/版本清单/{release_id}.json":
        raise RetrievalError("基础发布清单路径无效")
    registry_path = release_root / "版本清单" / f"{release_id}.json"
    registry_bytes = registry_path.read_bytes()
    if digest(registry_bytes) != pointer.get("registry_sha256"):
        raise RetrievalError("基础版本清单摘要与指针不一致")
    registry = strict_json(registry_path)
    if registry.get("release_id") != release_id or set(registry.get("views", {})) != set(AUDIENCES):
        raise RetrievalError("基础版本清单身份或视图无效")
    for audience in AUDIENCES:
        if registry["views"][audience].get("path") != f"发布/{'业务版' if audience == 'business' else '研发版'}":
            raise RetrievalError("基础发布视图路径无效")
    retrieval_root = release_root / "检索版"
    if any((release_root / name).exists() for name in ("检索版", "检索索引", "检索清单", "检索评测", "当前检索版本.json")):
        raise RetrievalError("当前发布已有检索扩展或残留；请先审计并处理，再建立新的基础 release")
    units = []
    duplicates = []
    for audience in AUDIENCES:
        source_root = release_root / ("业务版" if audience == "business" else "研发版")
        target_root = retrieval_root / ("业务" if audience == "business" else "研发")
        target_root.mkdir(parents=True)
        grouped = defaultdict(dict)
        files = registry["views"][audience]["files"]
        for local in sorted(files):
            source = source_root / local
            if source.name in SOURCE_ORDER[audience]:
                grouped[source.parent.relative_to(source_root).as_posix()][source.name] = source
        for module_dir, by_name in sorted(grouped.items()):
            seen = {}
            generic_units = {}
            identities = defaultdict(int)
            for filename in SOURCE_ORDER[audience]:
                source = by_name.get(filename)
                if source is None:
                    continue
                meta, body = source_meta(source)
                module_id = meta.get("module_id", "")
                if not module_id:
                    raise RetrievalError(f"发布正文缺少 module_id：{source}")
                module_title = clean_title(readable_module_title(body, filename))
                for raw_title, content, source_headings in index_sections(body, filename):
                    title = clean_title(raw_title)
                    if title in GENERIC_TITLES:
                        title = clean_title(f"{module_title} · {title}")
                    if not title:
                        continue
                    source_local = source.relative_to(source_root).as_posix()
                    normalized = re.sub(r"\s+", "", content)
                    if normalized in seen:
                        original = seen[normalized]
                        old_meta, old_body = read_unit(original["path"])
                        old_headings = old_meta["source_headings"].split(" | ")
                        new_source = source_local not in original["entry"]["source_documents"]
                        new_heading = any(heading not in old_headings for heading in source_headings)
                        if source_local not in original["entry"]["source_documents"]:
                            original["entry"]["source_documents"].append(source_local)
                        if new_source or new_heading:
                            old_meta["source_documents"] = " | ".join(original["entry"]["source_documents"])
                            old_meta["source_headings"] = " | ".join(dict.fromkeys(old_headings + source_headings))
                            old_body = old_body.rstrip() + f"\n- {source_local} · {' | '.join(source_headings)}\n"
                            original["path"].write_bytes(render_unit(old_meta, old_body))
                        duplicates.append({"audience": audience, "module_id": module_id, "source": source_local, "same_as": original["source"]})
                        continue
                    if raw_title in GENERIC_TITLES and title in generic_units:
                        original = generic_units[title]
                        destination = original["path"]
                        rewritten = rewrite_links(content, source, destination)
                        old_meta, old_body = read_unit(destination)
                        if "\n## 出处\n\n" not in old_body:
                            raise RetrievalError("检索单元缺少出处段")
                        addition = f"\n### {filename} · {raw_title}\n\n{rewritten}\n"
                        old_body = old_body.replace("\n## 出处\n\n", addition + "\n## 出处\n\n", 1)
                        old_body = old_body.rstrip() + f"\n- {source_local} · {' | '.join(source_headings)}\n"
                        original["entry"]["source_documents"].append(source_local)
                        old_meta["source_documents"] = " | ".join(original["entry"]["source_documents"])
                        old_meta["source_headings"] += " | " + " | ".join(source_headings)
                        if audience == "engineering":
                            facts = sorted((set(old_meta["fact_ids"].split(",")) | set(FACT.findall(content))) - {""})
                            old_meta["fact_ids"] = ",".join(facts)
                            old_meta["traceability_level"] = "fact" if facts else "document"
                        if audience == "business" and business_scanner is not None:
                            business_scanner(old_body, str(destination))
                        destination.write_bytes(render_unit(old_meta, old_body))
                        read_unit(destination)
                        seen[normalized] = original
                        continue
                    identity = (filename, title)
                    identities[identity] += 1
                    unit_id = "ru." + audience + "." + module_id + "." + digest((filename + "\0" + title + "\0" + str(identities[identity])).encode("utf-8"))[:12]
                    local_unit = f"{module_dir}/{unit_id}.md"
                    destination = target_root / local_unit
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    rewritten = rewrite_links(content, source, destination)
                    body_text = f"# {title}\n\n模块：{module_title}\n\n## 结论与边界\n\n{rewritten}\n\n## 出处\n\n- {source_local} · {' | '.join(source_headings)}\n"
                    if audience == "business" and business_scanner is not None:
                        business_scanner(body_text, str(destination))
                    facts = sorted(set(FACT.findall(content))) if audience == "engineering" else []
                    unit_meta = {
                        "document_type": "retrieval_unit", "retrieval_schema_version": SCHEMA,
                        "unit_id": unit_id, "module_id": module_id, "audience": audience,
                        "topic": title, "question_variants": question_variants(title),
                        "source_documents": source_local, "source_headings": " | ".join(source_headings),
                        "fact_ids": ",".join(facts), "traceability_level": "fact" if facts else "document",
                        "release_id": release_id,
                    }
                    destination.write_bytes(render_unit(unit_meta, body_text))
                    read_unit(destination)
                    item = {"unit_id": unit_id, "module_id": module_id, "audience": audience, "path": f"发布/检索版/{'业务' if audience == 'business' else '研发'}/{local_unit}", "topic": title, "source_documents": [source_local]}
                    units.append(item)
                    seen[normalized] = {"source": source_local, "entry": item, "path": destination}
                    if raw_title in GENERIC_TITLES:
                        generic_units[title] = seen[normalized]
    if not any(item["audience"] == "business" for item in units):
        raise RetrievalError("基础发布没有可生成的业务检索单元")
    candidates = []
    by_module = defaultdict(list)
    for item in units:
        by_module[(item["audience"], item["module_id"])].append(item)
    for group in by_module.values():
        for position, left in enumerate(group):
            for right in group[position + 1:]:
                ratio = SequenceMatcher(None, left["topic"], right["topic"]).ratio()
                if ratio >= 0.84:
                    candidates.append({"unit_ids": sorted((left["unit_id"], right["unit_id"])), "title_similarity": round(ratio, 3)})
    route = {"schema_version": SCHEMA, "release_id": release_id, "audiences": {}}
    for audience in AUDIENCES:
        route["audiences"][audience] = [
            {"unit_id": item["unit_id"], "module_id": item["module_id"], "topic": item["topic"], "path": item["path"]}
            for item in sorted(units, key=lambda value: value["unit_id"]) if item["audience"] == audience
        ]
    route_path = release_root / "检索索引" / f"{release_id}.json"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_bytes(json_bytes(route))
    manifest = {
        "retrieval_manifest_schema_version": SCHEMA,
        "retrieval_schema_version": SCHEMA,
        "release_id": release_id,
        "base_registry_path": registry_local,
        "base_registry_sha256": digest(registry_bytes),
        "generated_by": generated_by,
        "generated_at": registry["created_at"],
        "profile": profile,
        "views": {
            "business": {"path": "发布/检索版/业务", "files": inventory(retrieval_root / "业务")},
            "engineering": {"path": "发布/检索版/研发", "files": inventory(retrieval_root / "研发")},
        },
        "units": sorted(units, key=lambda item: item["unit_id"]),
        "duplicates": duplicates,
        "duplicate_candidates": candidates,
        "route_index": {"path": f"发布/检索索引/{release_id}.json", "sha256": digest(route_path.read_bytes())},
        "evaluation": None,
        "gate_status": "unevaluated",
    }
    manifest_path = release_root / "检索清单" / f"{release_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(json_bytes(manifest))
    return manifest


def coverage_report(registry: dict, retrieval: dict, release_root: Path | None = None) -> dict:
    """Explain published files omitted by the optional retrieval extension."""
    if registry.get("release_id") != retrieval.get("release_id"):
        raise RetrievalError("检索覆盖报告的基础发布与检索发布不一致")
    omissions = []
    conservative_groups = []
    navigation = {"目录.md", "功能大纲.md", "检索索引.md", "发布信息.md"}
    for audience in AUDIENCES:
        indexed = {
            path for item in retrieval["units"] if item["audience"] == audience
            for path in item["source_documents"]
        }
        for path in sorted(registry["views"][audience]["files"]):
            if path in indexed:
                continue
            filename = Path(path).name
            if filename == "术语表.md":
                reason = "glossary_not_in_retrieval_extension"
            elif filename in navigation:
                reason = "navigation_only"
            elif filename in SOURCE_ORDER[audience]:
                reason = "no_indexable_section"
            else:
                reason = "not_in_retrieval_source_order"
            omissions.append({"audience": audience, "source_path": f"发布/{'业务版' if audience == 'business' else '研发版'}/{path}", "reason": reason})
        if release_root is not None:
            for path in sorted(indexed):
                source = release_root / ("业务版" if audience == "business" else "研发版") / path
                _, body = source_meta(source)
                shared = sorted({match[1].strip().strip("：:") for match in HEADING.finditer(body)} & SHARED_CONTEXT_TITLES)
                if shared:
                    conservative_groups.append({
                        "audience": audience,
                        "source_path": f"发布/{'业务版' if audience == 'business' else '研发版'}/{path}",
                        "shared_headings": shared,
                        "reason": "whole_source_kept_to_preserve_answer_boundaries",
                        "review_required": True,
                    })
    return {
        "schema_version": "0.1", "release_id": retrieval["release_id"],
        "indexed_units": len(retrieval["units"]), "omissions": omissions,
        "conservative_groups": conservative_groups,
        "coverage_is_complete": not any(item["reason"] != "navigation_only" for item in omissions),
    }


def build(project: Path, release_id: str, profile: str, core) -> dict:
    """Build an optional extension for the audited current base release."""
    try:
        from .governance import Governance, scan_business_terms
    except ImportError:
        from governance import Governance, scan_business_terms
    governance = Governance(project, project / "知识源", {}, [], None, core)
    governance.audit_release(None)
    configured_profile = project_profile(project)
    if profile is not None and profile != configured_profile:
        raise RetrievalError("检索 profile 与项目工程配置不一致")
    profile = configured_profile
    release = project / "发布"
    staging = Path(tempfile.mkdtemp(prefix=".检索待替换-", dir=project))
    try:
        shutil.copytree(release, staging / "发布", symlinks=True)
        manifest = build_in_release(staging / "发布", release_id, profile, governance.generator_identity(), lambda text, where: scan_business_terms(core, text, where))
        try:
            from .retrieval_audit import audit_in_release
        except ImportError:
            from retrieval_audit import audit_in_release
        audit_in_release(staging / "发布", release_id, require_ready=False)
        installed = []
        try:
            for name in ("检索版", "检索索引", "检索清单"):
                os.replace(staging / "发布" / name, release / name)
                installed.append(release / name)
        except OSError:
            for path in reversed(installed):
                if path.is_dir():
                    shutil.rmtree(path)
            raise
        return {"release_id": release_id, "units": len(manifest["units"]), "gate_status": manifest["gate_status"], "duplicates": len(manifest["duplicates"])}
    finally:
        shutil.rmtree(staging)
