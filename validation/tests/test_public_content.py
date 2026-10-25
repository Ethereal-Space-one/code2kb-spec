from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_public_content.py"
SPEC = importlib.util.spec_from_file_location("check_public_content", SCRIPT)
assert SPEC and SPEC.loader
public_content = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public_content)


class PublicContentTests(unittest.TestCase):
    def test_private_denylist_uses_literal_terms(self) -> None:
        with patch.dict(os.environ, {"CODE2KB_PUBLIC_DENYLIST": "private.module,a+b"}, clear=False), patch.object(
            public_content, "LOCAL_DENYLIST", Path("/path/that/does/not/exist")
        ):
            patterns = list(public_content.private_patterns().values())
        self.assertEqual(len(patterns), 2)
        self.assertTrue(any(pattern.search("PRIVATE.MODULE") for pattern in patterns))
        self.assertTrue(any(pattern.search("a+b") for pattern in patterns))
        self.assertFalse(any(pattern.fullmatch("ab") for pattern in patterns))

    def test_machine_specific_paths_are_detected(self) -> None:
        mac_path = "/" + "Users/example/project"
        linux_path = "/" + "home/example/project"
        windows_path = "C:" + "\\Users\\example\\project"
        self.assertTrue(public_content.FORBIDDEN["macOS 用户绝对路径"].search(mac_path))
        self.assertTrue(public_content.FORBIDDEN["Linux 用户绝对路径"].search(linux_path))
        self.assertTrue(public_content.FORBIDDEN["Windows 用户绝对路径"].search(windows_path))

    def test_new_source_fixture_formats_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = "/" + "Users/example/private-source"
            suffixes = (".java", ".ts", ".tsx", ".vue", ".js", ".jsx", ".php", ".go", ".rs", ".sh", ".sql", ".html", ".css")
            for suffix in suffixes:
                (root / f"sample{suffix}").write_text(f"// {marker}\n", encoding="utf-8")
            with patch.object(public_content, "ROOT", root), patch.object(
                public_content, "LOCAL_DENYLIST", root / ".code2kb-public-denylist"
            ), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(public_content.main(), 1)
            for suffix in suffixes:
                self.assertIn(f"sample{suffix}:1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
