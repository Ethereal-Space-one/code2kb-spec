"""Public five-module scope gate; deliberately does not claim execution savings."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from validation.evidence_snapshot import snapshot
from validation.relation_upgrade_project import preview_project
from validation.upgrade_plan import build


ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "conformance/upgrade-petclinic-five-module/expected.json"
PUBLIC = ROOT / "conformance/public-source/petclinic/backend"
CONTROLLERS = "src/main/java/org/springframework/samples/petclinic/rest/controller/v1"


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-26T00:00:00+00:00",
           "GIT_COMMITTER_DATE": "2026-10-26T00:00:00+00:00"}
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Public Fixture",
                    "-c", "user.email=public@example.invalid", "commit", "-q", "-m", message],
                   check=True, capture_output=True, env=env)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


class PetclinicFiveModuleUpgradeTests(unittest.TestCase):
    def test_scope_against_independently_labeled_public_source(self) -> None:
        expected = json.loads(CASE.read_text(encoding="utf-8"))
        modules = expected["modules"]
        self.assertEqual(len(modules), 5)
        self.assertEqual(sum(row["must_reinterpret"] for row in modules), 1)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "source"
            project = root / "project"
            source = project / "知识源"
            repo.mkdir()
            source.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            for row in modules:
                relative = Path(CONTROLLERS) / row["file"]
                original = PUBLIC / relative
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), row["original_sha256"])
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
            old_commit = _commit(repo, "fixed public source")
            repositories = {"backend": {"path": str(repo), "commit": old_commit}}
            (project / "知识库配置.json").write_text(
                json.dumps({"repositories": repositories}, ensure_ascii=False), encoding="utf-8")

            docs = []
            relations = {}
            facts = {}
            for row in modules:
                module_id = row["module_id"]
                module_dir = source / module_id
                module_dir.mkdir()
                anchor = f"backend:{CONTROLLERS}/{row['file']}:{row['line_span']}"
                record = snapshot(anchor, repositories)
                relation = {"nodes": [], "links": [{
                    "from_type": "method", "from_id": "METHOD-001",
                    "to_type": "fact", "to_id": "FACT-001", "status": "verified",
                    "evidence": [record], "reviewed_by": "Public fixture reviewer",
                    "reviewed_at": "2026-10-26",
                }]}
                (module_dir / "关系映射.json").write_text(
                    json.dumps(relation, ensure_ascii=False), encoding="utf-8")
                relations[module_id] = relation
                facts[module_id] = [{"fact_id": "FACT-001", "anchors": anchor,
                                     "documents": ["功能与范围.md"]}]
                for name, doc_type in (("结构化规格.md", "spec"), ("功能与范围.md", "scope"),
                                       ("发布清单.md", "release_manifest")):
                    relative = Path(module_id) / name
                    (source / relative).write_text(
                        f"---\nmodule_id: {module_id}\ndocument_type: {doc_type}\n"
                        f"review_status: reviewed\nsource_revisions: backend={old_commit}\n---\n\n"
                        f"# {row['base_answer']}\n", encoding="utf-8")
                    docs.append(SimpleNamespace(module_id=module_id, doc_type=doc_type,
                                                relative=relative,
                                                meta={"source_revisions": f"backend={old_commit}",
                                                      "review_status": "reviewed"}))
            _commit(project, "reviewed baseline fixture")

            owner = repo / CONTROLLERS / "OwnerRestControllerV1.java"
            before = owner.read_text(encoding="utf-8")
            self.assertEqual(before.count("if (lastName != null) {"), 1)
            owner.write_text(before.replace("if (lastName != null) {",
                                            "if (lastName != null && !lastName.isBlank()) {", 1),
                             encoding="utf-8")
            new_commit = _commit(repo, "controlled blank surname change")
            preview = preview_project(relations, facts, [], repositories, "backend", new_commit)
            # The answer labels were fixed before preview. Compare each original
            # source blob with the controlled target instead of using the plan as an oracle.
            for row in modules:
                path = f"{CONTROLLERS}/{row['file']}"
                old_blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse",
                                                    f"{old_commit}:{path}"], text=True).strip()
                new_blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse",
                                                    f"{new_commit}:{path}"], text=True).strip()
                self.assertEqual(old_blob != new_blob, row["must_reinterpret"])
                self.assertEqual(row["base_answer"] != row["target_answer"], row["must_reinterpret"])

            self.assertEqual(preview["unattributed_paths"], [])
            self.assertEqual(preview["possible_modules"], ["petclinic.owner.search"])
            from validation.knowledge import parse_frontmatter
            plan = build(project, source, preview, docs,
                         {module_id: {"data": relation, "links": relation["links"]}
                          for module_id, relation in relations.items()},
                         [row["module_id"] for row in modules], parse_frontmatter)
            self.assertEqual(plan["decision"], "selected_modules")
            self.assertEqual(plan["selected_modules"], ["petclinic.owner.search"])
            self.assertEqual(plan["fallback_reasons"], [])
            self.assertEqual(plan["review_scope_metrics"]["modules_total"], 5)
            self.assertEqual(plan["review_scope_metrics"]["semantic_review_modules"], 1)
            self.assertEqual(plan["review_scope_metrics"]["baseline_touch_modules"], 5)
            self.assertEqual(plan["review_scope_metrics"]["approval_refresh_modules"], 5)
            self.assertEqual(plan["review_scope_metrics"]["evidence_records_rebuildable"], 4)
            self.assertEqual(plan["review_scope_metrics"]["evidence_records_requiring_review"], 1)
            self.assertEqual(plan["review_scope_metrics"]["source_revision_files"], 15)
            self.assertEqual(plan["input_snapshot"]["knowledge_worktree_dirty"], False)
            self.assertEqual(subprocess.check_output(["git", "-C", str(project), "status", "--porcelain"]), b"")


if __name__ == "__main__":
    unittest.main()
