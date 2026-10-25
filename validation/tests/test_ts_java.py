from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from validation.adapters.ts_java import scan
from validation.adapters.platform import scan as scan_platform
from validation.adapters.sdk import validate_result


class CandidateAdapterTests(unittest.TestCase):
    def test_platform_reports_levels_and_never_verifies_route_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "api.ts").write_text("const request = { url: '/orders' };\nconst dynamic = { url: routeFromServer };\n", encoding="utf-8")
            (repo / "Order.java").write_text("@GetMapping(\"/orders\")\npublic Order getOrder() { return null; }\n", encoding="utf-8")
            (repo / "tool.sh").write_text("echo ready\n", encoding="utf-8")
            (repo / "ignored.sql").write_text("select 1;\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            settings = {"path": str(repo), "commit": commit}
            first = scan_platform("source", settings)
            self.assertEqual(first["schema_version"], "0.2")
            self.assertTrue(any(item["language"] == "shell" and item["capability"] == "L1" for item in first["candidates"]))
            self.assertTrue(all(edge["status"] == "candidate" and len(edge["evidence"]) == 2 for edge in first["edges"]))
            self.assertEqual(len(first["edges"]), 1)
            self.assertTrue(any(item["status"] == "unresolved" for item in first["candidates"]))
            (repo / "api.ts").write_text("const changed = { url: '/other' };\n", encoding="utf-8")
            self.assertEqual(first, scan_platform("source", settings))
            scoped = scan_platform("source", settings, scope="tool.sh")
            self.assertEqual({item["source_path"] for item in scoped["candidates"]}, {"tool.sh"})
            self.assertEqual(scoped["edges"], [])
            fallback = scan_platform("source", settings, adapter_name="universal-l1")
            self.assertEqual(fallback["adapter"]["name"], "universal-l1")
            self.assertEqual({item["kind"] for item in fallback["candidates"]}, {"source_file"})
            invalid = dict(first)
            invalid["candidates"] = [dict(item) for item in first["candidates"]]
            invalid["candidates"][0]["status"] = "verified"
            with self.assertRaisesRegex(ValueError, "状态无效"):
                validate_result(invalid)

    def test_fixed_commit_candidates_and_unresolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "pages.json").write_text(json.dumps({"pages": [{"path": "pages/home"}]}, ensure_ascii=False), encoding="utf-8")
            (repo / "api.ts").write_text("const request = { url: '/orders' };\nconst dynamic = { url: routeFromServer };\nconst template = { url: `/orders/${id}` };\n", encoding="utf-8")
            (repo / "Order.java").write_text("@GetMapping(\"/orders\")\npublic Order getOrder() { return null; }\n@RequestMapping(path = routeFromConfig)\n@PostMapping(\"/orders/\" + suffix)\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            settings = {"path": str(repo), "commit": commit}
            first = scan("source", settings, uniapp_manifest="pages.json")
            self.assertEqual(first["capability"], "deterministic_candidates_only")
            self.assertEqual(first["unresolved"], 4)
            self.assertEqual({item["kind"] for item in first["candidates"]}, {"typescript_path", "typescript_dynamic_path", "java_route", "java_method", "uniapp_route"})
            self.assertEqual(sum(item["expression"] == "/orders" for item in first["candidates"]), 2)
            (repo / "api.ts").write_text("const request = { url: '/changed' };\n", encoding="utf-8")
            self.assertEqual(first, scan("source", settings, uniapp_manifest="pages.json"))


if __name__ == "__main__":
    unittest.main()
