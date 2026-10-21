from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_conformance.py"
SPEC = importlib.util.spec_from_file_location("check_conformance", SCRIPT)
assert SPEC and SPEC.loader
conformance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(conformance)


class ConformanceTests(unittest.TestCase):
    def test_report_matches_checked_in_expectation(self) -> None:
        expected = conformance.strict_json(conformance.CONFORMANCE / "expected" / "report.json")
        self.assertEqual(conformance.build_report(), expected)

    def test_strict_json_rejects_duplicate_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text('{"value": 1, "value": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(conformance.ConformanceError, "重复字段"):
                conformance.strict_json(path)


if __name__ == "__main__":
    unittest.main()
