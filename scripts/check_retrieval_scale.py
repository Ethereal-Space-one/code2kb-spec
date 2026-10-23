"""Repeatable synthetic size and determinism check; not a real-query quality claim."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from retrieval_evaluate import evaluate_data, load_suite  # noqa: E402
from retrieval_model import digest, json_bytes, read_unit  # noqa: E402


def main() -> int:
    fixture = ROOT / "conformance" / "retrieval"
    originals = [read_unit(path) for path in sorted((fixture / "units").glob("*.md"))]
    suite = load_suite(fixture / "suites" / "minimal-business.json")
    units = {}
    cases = []
    views = {audience: {"files": {}} for audience in ("business", "engineering")}
    for index in range(24):
        marker = f"demo{index:02d}"
        for original_meta, original_body in originals:
            meta = dict(original_meta)
            meta["unit_id"] += "." + marker
            meta["module_id"] += "." + marker
            meta["topic"] = marker + " " + meta["topic"]
            meta["question_variants"] = marker + " " + meta["question_variants"]
            body = original_body.replace("## 出处", marker + "\n\n## 出处", 1)
            units[meta["unit_id"]] = {"meta": meta, "body": body}
            views[meta["audience"]]["files"][meta["unit_id"]] = digest(body.encode("utf-8"))
        for original in suite["cases"]:
            case = dict(original)
            case["case_id"] += "-" + marker
            case["query"] = marker + " " + case["query"]
            case["expected_module_ids"] = [value + "." + marker for value in case["expected_module_ids"]]
            case["expected_unit_ids"] = [value + "." + marker for value in case["expected_unit_ids"]]
            cases.append(case)
    expanded = dict(suite, suite_id="synthetic-scale-v1", cases=cases)
    corpus = digest(json_bytes(views))
    first = evaluate_data(expanded, units, None, corpus)
    second = evaluate_data(expanded, units, None, corpus)
    if json_bytes(first) != json_bytes(second) or first["gate_status"] != "passed":
        print(json.dumps({"summary": first["summary"], "failed": [row for row in first["cases"] if not row["passed"]][:3]}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("合成规模检索基线不稳定或门禁失败")
    print(json.dumps({"schema_version": "0.1", "fixture": expanded["suite_id"],
                      "units": len(units), "cases": len(cases), "business_units": len(views["business"]["files"]),
                      "engineering_units": len(views["engineering"]["files"]),
                      "gate_status": first["gate_status"], "summary": first["summary"],
                      "deterministic": True, "warning": "合成问题含唯一标记，仅验证规模与确定性，不代表真实检索质量"},
                     ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
