"""Render reviewed factual clauses for each audience without model rewriting."""

from __future__ import annotations



HEADER = "| fact_id | 适用条件 | 结论 | 例外与失败 | 未知边界 |"
FACT_HEADER = "| fact_id | 单一结论与条件 | 证据等级 | 固定提交锚点 | 影响的知识文件 |"


class FactRenderError(ValueError):
    pass


def normalized_facts(spec, core) -> dict[str, dict]:
    if "## 规范化事实" not in spec.body:
        return {}
    raw = {row[0]: row for row in core.table_rows(spec.body, "## 入口与调用链", FACT_HEADER)}
    result = {}
    for fact_id, condition, conclusion, exception, unknown in core.table_rows(spec.body, "## 规范化事实", HEADER):
        if fact_id in result or fact_id not in raw:
            raise FactRenderError("规范化事实编号重复或未在主事实表登记")
        if any(not value or "\n" in value for value in (condition, conclusion, exception, unknown)):
            raise FactRenderError("规范化事实条件、结论、例外或未知不能为空；没有时写 无")
        if conclusion not in raw[fact_id][1]:
            raise FactRenderError("规范化事实结论与主事实表不一致")
        result[fact_id] = {
            "fact_id": fact_id, "condition": condition, "conclusion": conclusion,
            "exception": exception, "unknown": unknown,
            "level": raw[fact_id][2], "source_anchors": raw[fact_id][3],
        }
    return result


def render_topic(topic: dict, fact_ids: list[str], facts: dict[str, dict]) -> dict:
    if not fact_ids or any(fact_id not in facts for fact_id in fact_ids):
        raise FactRenderError("主题缺少已规范化且已复核的事实")
    ordered = [facts[fact_id] for fact_id in sorted(set(fact_ids))]
    conditions = [item["condition"] for item in ordered if item["condition"] != "无"]
    conclusions = [item["conclusion"] for item in ordered]
    exceptions = [item["exception"] for item in ordered if item["exception"] != "无"]
    unknowns = [item["unknown"] for item in ordered if item["unknown"] != "无"]
    def section(name: str, values: list[str]) -> str:
        return f"## {name}\n\n" + "\n".join(f"- {value}" for value in values) + "\n\n" if values else ""
    common = (section("适用条件", conditions) + section("结论", conclusions)
              + section("例外与失败", exceptions) + section("仍不能确定", unknowns)).rstrip() + "\n"
    engineering = common + "\n## 事实与源码\n\n" + "\n".join(
        f"- {item['fact_id']}（{item['level']}）：{item['source_anchors']}" for item in ordered
    ) + "\n"
    retrieval = (common if topic["audience"] == "business" else engineering).rstrip()
    retrieval += f"\n\n## 出处\n\n- {topic['source_document']} · {topic['source_heading']}\n"
    return {
        "topic_id": topic["topic_id"], "audience": topic["audience"],
        "fact_ids": sorted(set(fact_ids)), "business": common,
        "engineering": engineering, "retrieval": retrieval,
    }


def render_mapped(spec, mapping: dict, core, external_specs: dict | None = None) -> list[dict]:
    facts = normalized_facts(spec, core)
    if external_specs:
        for module_id, external in external_specs.items():
            if module_id == spec.module_id:
                continue
            for fact_id, item in normalized_facts(external, core).items():
                qualified = f"{module_id}#{fact_id}"
                facts[qualified] = {**item, "fact_id": qualified}
    linked: dict[str, list[str]] = {}
    for link in mapping["links"]:
        if link["from_type"] == "fact" and link["to_type"] == "topic" and link["status"] == "verified":
            linked.setdefault(link["to_id"], []).append(link["from_id"])
    return [render_topic(topic, linked[topic["topic_id"]], facts) for topic in mapping["topics"] if topic["topic_id"] in linked]
