from __future__ import annotations

import subprocess
from pathlib import Path
import tempfile
import unittest

from validation.evidence_snapshot import EvidenceError, snapshot, verify


class EvidenceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "source"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "main.java").write_text("class Example {\n  int count = 1;\n}\n", encoding="utf-8")
        self.commit()
        self.repositories = {"source": {"path": str(self.repo), "commit": self.head()}}

    def commit(self) -> None:
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=Fixture", "-c",
            "user.email=fixture@example.invalid", "commit", "-q", "-m", "fixture",
        ], check=True)

    def head(self) -> str:
        return subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()

    def test_fixed_commit_ignores_worktree_and_newer_commit(self) -> None:
        old = snapshot("source:main.java:2", self.repositories)
        verify(old, self.repositories)
        (self.repo / "main.java").write_text("class Example {\n  int count = 2;\n}\n", encoding="utf-8")
        verify(old, self.repositories)
        self.commit()
        verify(old, self.repositories)
        self.repositories["source"]["commit"] = self.head()
        with self.assertRaisesRegex(EvidenceError, "不一致"):
            verify(old, self.repositories)
        new = snapshot("source:main.java:2", self.repositories)
        self.assertNotEqual(old["snippet_sha256"], new["snippet_sha256"])
        self.assertNotEqual(old["blob_oid"], new["blob_oid"])

    def test_rejects_invalid_line_and_symlink(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "越界"):
            snapshot("source:main.java:20", self.repositories)
        with self.assertRaisesRegex(EvidenceError, "不安全"):
            snapshot("source:../main.java:1", self.repositories)
        (self.repo / "linked.java").symlink_to("main.java")
        self.commit()
        self.repositories["source"]["commit"] = self.head()
        with self.assertRaisesRegex(EvidenceError, "非普通"):
            snapshot("source:linked.java:1", self.repositories)

    def test_tampered_excerpt_digest_is_rejected(self) -> None:
        record = snapshot("source:main.java:1-2", self.repositories)
        changed = {**record, "snippet_sha256": "0" * 64}
        with self.assertRaisesRegex(EvidenceError, "不一致"):
            verify(changed, self.repositories)


if __name__ == "__main__":
    unittest.main()
