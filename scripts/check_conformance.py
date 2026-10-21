#!/usr/bin/env python3
"""Validate requirement coverage and execute portable Code2KB fixtures."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
REQUIREMENT = re.compile(r"\*\*(C2KB-[A-Z]+-[0-9]{3})\*\*")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ConformanceError(ValueError):
    pass


def strict_json(path: Path) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ConformanceError(f"{path}: 重复字段 {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"{path}: 不是有效 UTF-8 JSON") from exc


def requirement_ids() -> list[str]:
    found: list[str] = []
    for path in sorted((ROOT / "spec").glob("*.md")):
        found.extend(REQUIREMENT.findall(path.read_text(encoding="utf-8")))
    if not found or len(found) != len(set(found)):
        raise ConformanceError("规范编号为空或重复")
    return sorted(found)


def validate_reference(reference: str) -> None:
    if not isinstance(reference, str) or not reference:
        raise ConformanceError("覆盖引用必须是非空字符串")
    local, separator, selector = reference.partition("::")
    path = ROOT / local
    if Path(local).is_absolute() or ".." in Path(local).parts or not path.is_file():
        raise ConformanceError(f"覆盖引用文件不存在或越界：{reference}")
    if separator:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", selector):
            raise ConformanceError(f"测试选择器无效：{reference}")
        class_name, method_name = selector.split(".", 1)
        body = path.read_text(encoding="utf-8")
        if not re.search(rf"(?m)^class {re.escape(class_name)}\b", body) or not re.search(
            rf"(?m)^\s+def {re.escape(method_name)}\(", body
        ):
            raise ConformanceError(f"测试选择器未找到：{reference}")


def validate_coverage(ids: list[str]) -> dict:
    value = strict_json(CONFORMANCE / "coverage.json")
    if not isinstance(value, dict) or set(value) != {"schema_version", "spec_version", "requirements"}:
        raise ConformanceError("coverage.json 字段不完整或含未知字段")
    mapping = value["requirements"]
    if value["schema_version"] != "1.0" or value["spec_version"] != "0.8.3" or not isinstance(mapping, dict):
        raise ConformanceError("coverage.json 版本或 requirements 无效")
    if set(mapping) != set(ids):
        missing = sorted(set(ids) - set(mapping))
        unknown = sorted(set(mapping) - set(ids))
        raise ConformanceError(f"规范覆盖不完整：missing={missing}, unknown={unknown}")
    for requirement_id, references in mapping.items():
        if not isinstance(references, list) or not references or len(references) != len(set(references)):
            raise ConformanceError(f"{requirement_id}: 覆盖引用须非空且不重复")
        for reference in references:
            validate_reference(reference)
    return value


def execute_cases() -> tuple[int, int]:
    manifest = strict_json(CONFORMANCE / "cases.json")
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "cases"} or manifest["schema_version"] != "1.0":
        raise ConformanceError("cases.json 结构无效")
    cases = manifest["cases"]
    if not isinstance(cases, list) or not cases:
        raise ConformanceError("cases.json 必须包含夹具")
    seen: set[str] = set()
    passed = 0
    from validation.knowledge import KnowledgeError, read_config

    for case in cases:
        required = {"case_id", "kind", "file", "expected"}
        if not isinstance(case, dict) or (set(case) != required and set(case) != required | {"error_contains"}):
            raise ConformanceError("夹具条目字段无效")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ConformanceError(f"夹具 ID 无效或重复：{case_id}")
        seen.add(case_id)
        if case["kind"] != "project_config" or case["expected"] not in {"valid", "invalid"}:
            raise ConformanceError(f"{case_id}: 不支持的 kind 或 expected")
        fixture = CONFORMANCE / case["file"]
        if not fixture.is_file() or not fixture.resolve().is_relative_to(CONFORMANCE.resolve()):
            raise ConformanceError(f"{case_id}: 夹具路径不存在或越界")
        with tempfile.TemporaryDirectory(prefix="code2kb-conformance-") as temp:
            project = Path(temp).resolve() / "project"
            source = Path(temp).resolve() / "source"
            (project / "知识源").mkdir(parents=True)
            source.mkdir()
            shutil.copyfile(fixture, project / "知识库配置.json")
            error = None
            old = os.environ.get("CODE2KB_FIXTURE_SOURCE")
            os.environ["CODE2KB_FIXTURE_SOURCE"] = str(source)
            try:
                read_config(project)
            except (KnowledgeError, ValueError) as exc:
                error = str(exc)
            finally:
                if old is None:
                    os.environ.pop("CODE2KB_FIXTURE_SOURCE", None)
                else:
                    os.environ["CODE2KB_FIXTURE_SOURCE"] = old
        if case["expected"] == "valid" and error is not None:
            raise ConformanceError(f"{case_id}: 预期有效但被拒绝：{error}")
        if case["expected"] == "invalid":
            if error is None:
                raise ConformanceError(f"{case_id}: 预期无效但被接受")
            expected_error = case.get("error_contains")
            if expected_error and expected_error not in error:
                raise ConformanceError(f"{case_id}: 错误信息不匹配：{error}")
        passed += 1
    return len(cases), passed


def build_report() -> dict:
    ids = requirement_ids()
    validate_coverage(ids)
    cases_total, cases_passed = execute_cases()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    return {
        "schema_version": "1.0",
        "spec_version": "0.8.3",
        "implementation_version": version,
        "requirements_total": len(ids),
        "requirements_covered": len(ids),
        "cases_total": cases_total,
        "cases_passed": cases_passed,
        "status": "passed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-expected", action="store_true", help="compare with conformance/expected/report.json")
    parser.add_argument("--output", type=Path, help="write the deterministic report")
    args = parser.parse_args(argv)
    try:
        report = build_report()
        if args.check_expected:
            expected = strict_json(CONFORMANCE / "expected" / "report.json")
            if report != expected:
                raise ConformanceError(f"一致性报告与预期不同：expected={expected}, actual={report}")
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except ConformanceError as exc:
        print(f"一致性检查失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
