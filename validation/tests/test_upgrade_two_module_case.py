"""Keep the public two-module upgrade case reproducible and narrowly scoped."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


CASE = Path(__file__).resolve().parents[2] / "conformance/upgrade-two-module"


class UpgradeTwoModuleCaseTests(unittest.TestCase):
    def test_two_commits_change_only_order_rule(self) -> None:
        expected = json.loads((CASE / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual({item["module_id"] for item in expected["modules"]},
                         {"sample.order.delivery", "sample.account.profile"})
        self.assertIn(">= 10000 ? 0 : 500", (CASE / "base/src/main/java/example/OrderRule.java").read_text())
        self.assertIn(">= 8000 ? 0 : 500", (CASE / "revision-2/src/main/java/example/OrderRule.java").read_text())
        self.assertEqual((CASE / "base/src/main/java/example/AccountRule.java").read_bytes(),
                         (CASE / "revision-2/src/main/java/example/AccountRule.java").read_bytes())
        environment = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-26T00:00:00+00:00",
                       "GIT_COMMITTER_DATE": "2026-10-26T00:00:00+00:00"}
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "source"
            shutil.copytree(CASE / "base", repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            def commit(message: str) -> str:
                subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(repo), "-c", "user.name=Public Fixture",
                                "-c", "user.email=public@example.invalid", "commit", "-q", "-m", message],
                               check=True, env=environment)
                return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

            base = commit("base source")
            shutil.copy2(CASE / "revision-2/src/main/java/example/OrderRule.java",
                         repo / "src/main/java/example/OrderRule.java")
            target = commit("lower delivery threshold")
            changed = subprocess.check_output(["git", "-C", str(repo), "diff", "--name-only", base, target],
                                              text=True).splitlines()
            self.assertEqual(changed, expected["changed_paths"])
            for module in expected["modules"]:
                old_blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse",
                                                    f"{base}:{module['source_path']}"], text=True).strip()
                new_blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse",
                                                    f"{target}:{module['source_path']}"], text=True).strip()
                self.assertEqual(old_blob != new_blob, module["must_reinterpret"])


if __name__ == "__main__":
    unittest.main()
