from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from validation.adapters.ts_java import scan


class CandidateAdapterTests(unittest.TestCase):
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
