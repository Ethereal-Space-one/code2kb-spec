"""Offline lexical baseline and strict retrieval-result evaluator."""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
import re

try:
    from .retrieval_model import RetrievalError, digest, json_bytes, read_unit, strict_json
except ImportError:
    from retrieval_model import RetrievalError, digest, json_bytes, read_unit, strict_json


def tokens(text: str) -> Counter:
    result = Counter()
    normalized = text.casefold()
    for word in re.findall(r"[a-z0-9_.-]+", normalized):
        result[word] += 1
    for chunk in re.findall(r"[\u3400-\u9fff]+", normalized):
        for index, char in enumerate(chunk):
            result[char] += 1
            if index + 1 < len(chunk):
                result[chunk[index:index + 2]] += 1
    return result


def lexical(query: str, units: list[dict], top_k: int) -> list[str]:
    query_tokens = tokens(query)
    scored = []
    for item in units:
        meta, body = item["meta"], item["body"]
        fields = (
            (meta["module_id"], 6.0), (meta["topic"], 5.0),
            (meta["question_variants"], 4.0), (body, 1.0),
        )
        score = 0.0
        for value, weight in fields:
            corpus = tokens(value)
            score += weight * sum(min(count, corpus[token]) / math.sqrt(1 + corpus[token]) for token, count in query_tokens.items() if token in corpus)
        if score > 0:
            scored.append((-score, meta["unit_id"]))
    scored.sort()
    return [unit_id for _, unit_id in scored[:top_k]]


def load_suite(path: Path) -> dict:
    suite = strict_json(path)
    if set(suite) != {"schema_version", "suite_id", "audience", "cases"} or suite["schema_version"] not in {"0.1", "0.2"} or suite["audience"] not in {"business", "engineering"} or not isinstance(suite["suite_id"], str) or not suite["suite_id"] or not isinstance(suite["cases"], list) or not suite["cases"]:
        raise RetrievalError("检索评测问题集结构无效")
    ids = set()
    required = {"case_id", "query", "expected_module_ids", "expected_unit_ids", "required_phrases", "required_unknown_phrases", "forbidden_phrases", "top_k"}
    if suite["schema_version"] == "0.2":
        required.add("expected_decision")
    for case in suite["cases"]:
        if not isinstance(case, dict) or set(case) != required or not isinstance(case["case_id"], str) or not case["case_id"] or case["case_id"] in ids or not isinstance(case["query"], str) or not case["query"] or type(case["top_k"]) is not int or not 1 <= case["top_k"] <= 20:
            raise RetrievalError("检索评测用例结构无效或 ID 重复")
        ids.add(case["case_id"])
        if suite["schema_version"] == "0.2" and (not isinstance(case["expected_decision"], str) or case["expected_decision"] not in {"answer", "abstain"}):
            raise RetrievalError("检索评测预期决策无效")
        for field in required - {"case_id", "query", "top_k", "expected_decision"}:
            if not isinstance(case[field], list) or any(not isinstance(value, str) or not value for value in case[field]) or len(case[field]) != len(set(case[field])):
                raise RetrievalError(f"检索评测用例 {field} 无效")
        if suite["schema_version"] == "0.2" and case["expected_decision"] == "abstain":
            if case["expected_module_ids"] or case["expected_unit_ids"] or case["required_phrases"] or case["required_unknown_phrases"]:
                raise RetrievalError("不可回答题不能指定支持答案的单元或短语")
        elif not case["expected_module_ids"] and not case["expected_unit_ids"]:
            raise RetrievalError("评测用例至少要指定预期模块或单元")
    return suite


def load_units(release_root: Path, manifest: dict) -> dict[str, dict]:
    units = {}
    for entry in manifest["units"]:
        path = release_root.parent / entry["path"]
        meta, body = read_unit(path)
        if meta["unit_id"] in units:
            raise RetrievalError("检索单元 ID 重复")
        if meta["release_id"] != manifest["release_id"] or meta["source_documents"].split(" | ") != entry["source_documents"]:
            raise RetrievalError("检索单元与发布身份或出处不一致")
        units[meta["unit_id"]] = {"entry": entry, "meta": meta, "body": body}
    return units


def evaluate_data(suite: dict, units: dict[str, dict], external: dict | None, corpus_sha256: str, release_id: str | None = None) -> dict:
    if not units:
        raise RetrievalError("检索语料为空")
    if external is not None:
        if set(external) != {"schema_version", "suite_id", "retriever_id", "corpus_sha256", "cases"} or external["schema_version"] != suite["schema_version"] or external["suite_id"] != suite["suite_id"] or external["corpus_sha256"] != corpus_sha256 or not isinstance(external["retriever_id"], str) or not external["retriever_id"] or not isinstance(external["cases"], dict):
            raise RetrievalError("外部检索结果身份或语料摘要不匹配")
        if set(external["cases"]) != {case["case_id"] for case in suite["cases"]}:
            raise RetrievalError("外部检索结果用例集合不匹配")
    retriever_id = external["retriever_id"] if external else "lexical-v1"
    expected_release = release_id or next(iter(units.values()))["meta"]["release_id"]
    corpus_identity_correct = all(unit["meta"]["release_id"] == expected_release and bool(unit["meta"]["source_documents"]) for unit in units.values())
    rows = []
    for case in suite["cases"]:
        audience = suite["audience"]
        allowed = [unit for unit in units.values() if audience == "engineering" or unit["meta"]["audience"] == "business"]
        if external:
            submitted = external["cases"][case["case_id"]]
            if suite["schema_version"] == "0.2":
                if not isinstance(submitted, dict) or set(submitted) != {"hits", "decision"} or not isinstance(submitted["decision"], str) or submitted["decision"] not in {"answer", "abstain"}:
                    raise RetrievalError("外部检索决策格式无效")
                hits, decision = submitted["hits"], submitted["decision"]
            else:
                hits, decision = submitted, "answer" if submitted else "abstain"
            if not isinstance(hits, list) or any(not isinstance(hit, dict) or set(hit) != {"unit_id", "score"} or not isinstance(hit["unit_id"], str) or type(hit["score"]) not in (int, float) or not math.isfinite(hit["score"]) for hit in hits):
                raise RetrievalError("外部检索结果格式无效")
            all_ids = [hit["unit_id"] for hit in hits]
            if len(all_ids) != len(set(all_ids)) or any(unit_id not in units for unit_id in all_ids):
                raise RetrievalError("外部检索结果包含重复或未知单元 ID")
            result_ids = all_ids[:case["top_k"]]
        else:
            result_ids = lexical(case["query"], allowed, case["top_k"])
            # This is only a baseline policy: lexical-v1 cannot judge semantic support.
            decision = "answer" if result_ids else "abstain"
        selected = [units[unit_id] for unit_id in result_ids]
        expected_modules = set(case["expected_module_ids"])
        expected_units = set(case["expected_unit_ids"])
        expected_decision = case.get("expected_decision", "answer")
        relevant = [unit for unit in selected if unit["meta"]["unit_id"] in expected_units or unit["meta"]["module_id"] in expected_modules]
        text = "\n".join(unit["body"] for unit in relevant)
        all_text = "\n".join(unit["body"] for unit in selected)
        found_modules = {unit["meta"]["module_id"] for unit in selected}
        found_units = set(result_ids)
        module_recall = len(expected_modules & found_modules) / len(expected_modules) if expected_modules else (None if expected_decision == "abstain" else 1.0)
        unit_recall = len(expected_units & found_units) / len(expected_units) if expected_units else (None if expected_decision == "abstain" else 1.0)
        rank = next((index for index, unit_id in enumerate(result_ids, 1) if unit_id in expected_units or units[unit_id]["meta"]["module_id"] in expected_modules), None)
        required = [phrase for phrase in case["required_phrases"] if phrase not in text]
        unknown = [phrase for phrase in case["required_unknown_phrases"] if phrase not in text]
        forbidden = [phrase for phrase in case["forbidden_phrases"] if phrase in all_text]
        leakage = [unit_id for unit_id in result_ids if audience == "business" and units[unit_id]["meta"]["audience"] != "business"]
        hashes = [digest(re.sub(r"\s+", "", unit["body"].split("## 出处", 1)[0]).encode("utf-8")) for unit in selected]
        duplicate_hits = len(hashes) - len(set(hashes))
        decision_correct = decision == expected_decision
        recall_correct = expected_decision == "abstain" or (module_recall == 1 and unit_recall == 1)
        passed = decision_correct and recall_correct and not required and not unknown and not forbidden and not leakage and duplicate_hits == 0 and corpus_identity_correct
        rows.append({
            "case_id": case["case_id"], "query": case["query"], "hits": result_ids,
            "expected_decision": expected_decision, "decision": decision, "decision_correct": decision_correct,
            "module_recall_at_k": module_recall, "unit_recall_at_k": unit_recall,
            "reciprocal_rank": 1 / rank if rank else (None if expected_decision == "abstain" else 0.0),
            "missing_required_phrases": required, "missing_unknown_phrases": unknown,
            "forbidden_phrase_hits": forbidden, "audience_leakage": leakage,
            "duplicate_hits": duplicate_hits, "passed": passed,
            "source_release_correct": corpus_identity_correct,
        })
    answer_rows = [row for row in rows if row["expected_decision"] == "answer"]
    abstain_rows = [row for row in rows if row["expected_decision"] == "abstain"]
    return {
        "schema_version": suite["schema_version"], "suite_id": suite["suite_id"], "suite_audience": suite["audience"],
        "retriever_id": retriever_id, "corpus_sha256": corpus_sha256,
        "cases": rows,
        "summary": {"total": len(rows), "passed": sum(row["passed"] for row in rows),
                    "module_recall_at_k": sum(row["module_recall_at_k"] for row in answer_rows) / len(answer_rows) if answer_rows else None,
                    "unit_recall_at_k": sum(row["unit_recall_at_k"] for row in answer_rows) / len(answer_rows) if answer_rows else None,
                    "mrr": sum(row["reciprocal_rank"] for row in answer_rows) / len(answer_rows) if answer_rows else None,
                    "abstain_total": len(abstain_rows),
                    "abstain_correct": sum(row["decision_correct"] for row in abstain_rows),
                    "audience_leakage": sum(len(row["audience_leakage"]) for row in rows),
                    "required_phrase_coverage": 1 - sum(len(row["missing_required_phrases"]) for row in rows) / max(1, sum(len(case["required_phrases"]) for case in suite["cases"])),
                    "unknown_phrase_coverage": 1 - sum(len(row["missing_unknown_phrases"]) for row in rows) / max(1, sum(len(case["required_unknown_phrases"]) for case in suite["cases"])),
                    "forbidden_phrase_hits": sum(len(row["forbidden_phrase_hits"]) for row in rows),
                    "duplicate_hit_ratio": sum(row["duplicate_hits"] for row in rows) / max(1, sum(len(row["hits"]) for row in rows)),
                    "source_release_correct": all(row["source_release_correct"] for row in rows)},
        "gate_status": "passed" if all(row["passed"] for row in rows) else "failed",
    }


def evaluate_in_release(release_root: Path, release_id: str, suite_path: Path, external_path: Path | None = None) -> dict:
    manifest_path = release_root / "检索清单" / f"{release_id}.json"
    manifest = strict_json(manifest_path)
    if manifest.get("release_id") != release_id:
        raise RetrievalError("检索清单 release ID 不匹配")
    suite = load_suite(suite_path)
    units = load_units(release_root, manifest)
    corpus_sha256 = digest(json_bytes(manifest["views"]))
    external = strict_json(external_path) if external_path else None
    report = evaluate_data(suite, units, external, corpus_sha256, release_id)
    report.update({"release_id": release_id, "manifest_units_sha256": digest(json_bytes(manifest["units"])), "suite_sha256": digest(suite_path.read_bytes())})
    report_path = release_root / "检索评测" / f"{release_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path = release_root / "检索评测" / f"{release_id}.md"
    suite_copy = release_root / "检索评测" / "套件" / f"{release_id}.json"
    suite_copy.parent.mkdir(parents=True, exist_ok=True)
    suite_copy.write_bytes(suite_path.read_bytes())
    external_copy = None
    if external_path:
        external_copy = release_root / "检索评测" / "外部结果" / f"{release_id}.json"
        external_copy.parent.mkdir(parents=True, exist_ok=True)
        external_copy.write_bytes(external_path.read_bytes())
    report_path.write_bytes(json_bytes(report))
    markdown = [f"# 检索评测：{release_id}", "", f"- 问题集：{suite['suite_id']}", f"- 检索器：{report['retriever_id']}", f"- 门禁：{report['gate_status']}", f"- 通过：{report['summary']['passed']}/{report['summary']['total']}", "", "## 用例", ""]
    for row in report["cases"]:
        markdown.extend([f"### {row['case_id']}", "", f"- 查询：{row['query']}", f"- 结果：{', '.join(row['hits']) or '无命中'}", f"- 决策：{row['decision']}（预期：{row['expected_decision']}）", f"- 通过：{'是' if row['passed'] else '否'}", f"- 缺少必要短语：{', '.join(row['missing_required_phrases']) or '无'}", f"- 缺少未知边界：{', '.join(row['missing_unknown_phrases']) or '无'}", f"- 禁止断言命中：{', '.join(row['forbidden_phrase_hits']) or '无'}", f"- 受众泄漏：{', '.join(row['audience_leakage']) or '无'}", ""])
    markdown_path.write_text("\n".join(markdown), encoding="utf-8")
    manifest["evaluation"] = {"suite_id": suite["suite_id"], "suite_path": f"发布/检索评测/套件/{release_id}.json", "suite_sha256": report["suite_sha256"], "report_path": f"发布/检索评测/{release_id}.json", "report_sha256": digest(report_path.read_bytes()), "report_markdown_path": f"发布/检索评测/{release_id}.md", "report_markdown_sha256": digest(markdown_path.read_bytes()), "external_results_path": f"发布/检索评测/外部结果/{release_id}.json" if external_copy else None, "external_results_sha256": digest(external_copy.read_bytes()) if external_copy else None, "retriever_id": report["retriever_id"], "corpus_sha256": corpus_sha256}
    manifest["gate_status"] = report["gate_status"]
    manifest_path.write_bytes(json_bytes(manifest))
    pointer_path = release_root / "当前检索版本.json"
    if report["gate_status"] == "passed":
        pointer = {"retrieval_schema_version": "0.1", "release_id": release_id,
                   "base_registry_sha256": manifest["base_registry_sha256"],
                   "manifest_path": f"发布/检索清单/{release_id}.json",
                   "manifest_sha256": digest(manifest_path.read_bytes())}
        pointer_path.write_bytes(json_bytes(pointer))
    elif pointer_path.exists():
        pointer_path.unlink()
    return report
