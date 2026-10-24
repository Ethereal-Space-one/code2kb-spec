#!/usr/bin/env python3
"""Execute the portable relation-contract examples without private source code."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.relation_model import RelationError, strict_object, validate


def main() -> int:
    fixtures = ROOT / "conformance" / "relations"
    with tempfile.TemporaryDirectory() as temporary:
        module = Path(temporary)
        (module / "常见问答.md").write_text("## 查询结果\n\n只有已审核的结论可用于回答。\n", encoding="utf-8")
        known = {"fact": {"F-01"}}
        valid = strict_object((fixtures / "valid-candidate.json").read_bytes())
        validate(valid, known=known, module_dir=module, repositories={})
        invalid = strict_object((fixtures / "invalid-unverified.json").read_bytes())
        try:
            validate(invalid, known=known, module_dir=module, repositories={})
        except RelationError as exc:
            if "已证实关系缺少固定证据" not in str(exc):
                raise
        else:
            raise RelationError("缺少固定证据的已证实连接被接受")
    print("关系契约一致性：2/2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
