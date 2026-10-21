from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
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


if __name__ == "__main__":
    unittest.main()
