# Code2KB Spec

[简体中文](README.md) | **English**

Code2KB Spec extracts evidence-backed business behavior and code logic from fixed source revisions into traceable, reviewable, publishable, and retrievable knowledge bases. The repository also provides a Python reference implementation, an AI agent skill, templates, and stack adapters. Source code alone cannot prove business-policy intent or live behavior; uncertainty remains part of the knowledge.

> Current project version: `0.8.0`. The knowledge file protocol has its own compatibility identifier; it does not follow the version of any project using this tool.

## Three layers

| Layer | Purpose | Entry point |
| --- | --- | --- |
| Code2KB Spec | File, evidence, review, and release contracts | [SPEC.md](SPEC.md) |
| Reference Implementation | Python validation, review, publishing, and audit tools | [Reference implementation](docs/reference-implementation.md) |
| Agent Toolkit | Skill, prompts, templates, and adapters | [AI Skill](skills/extract-app-knowledge/SKILL.md) |

The normative specification is currently written in Simplified Chinese. If a translation differs from the Chinese specification, the Chinese text controls.

## Quick start

```bash
git clone https://github.com/Ethereal-Space-one/code2kb-spec.git
cd code2kb-spec
python3 -B -m unittest discover -s validation/tests -q
python3 -B scripts/check_conformance.py --check-expected
python3 -m pip install -e .
code2kb --help
code2kb --version
```

Create a configuration from the template and point it to fixed Git commits:

```bash
cp templates/知识库配置.example.json /path/to/knowledge-project/知识库配置.json
code2kb check --project-root /path/to/knowledge-project
```

See the [Chinese README](README.md) and [usage guide](docs/usage.md) for the complete workflow.

## 0.4.0 highlights

- optional topic-sized Markdown retrieval units, separated by audience and bound to an audited base release;
- an independent retrieval manifest, routing index, evaluation gate, and tamper audit;
- read-only lookup of candidate evidence and source paths from the audited current retrieval release;
- an offline lexical baseline and a strict external-results import format;
- a compact authoring profile and a full-versus-compact topic comparison;
- task-scoped Agent Skill contracts with optional extensions.

See the [retrieval contract](docs/retrieval-contract.md) and [evaluation guide](docs/retrieval-evaluation.md). The default two-view release remains unchanged.

## What's new in 0.5.0

The optional [relation and evidence extension](docs/relation-contract.md) adds fixed-commit excerpt rebuilding, reviewed fact-to-topic links, coverage reports, and conservative TypeScript/Java candidates. Candidates do not become business facts automatically. See the [implementation plan](docs/0.5.0-implementation-plan.md) and [independent public evidence check](docs/0.5.0-public-evidence-check.md) for scope and validation limits.

## What's new in 0.6.0

The optional [local resumable runner](docs/0.6.0-runner.md) adds a durable task ledger, project locking, crash recovery, batch checkpoints, and thin Claude Code and Codex adapters. The ledger does not grant approval. Existing projects need not enable it or republish for this change. See [versioning](docs/versioning.md) for file-format compatibility and the [implementation plan](docs/0.6.0-implementation-plan.md) for scope.

## What's new in 0.7.0

New projects default to the independent `c2kb-file/1` file protocol identifier. Existing `0.8.3` projects retain their validation, publishing, and audit path; migration requires an explicit preview and apply step. Multilanguage adapters emit fixed-revision candidates, capability declarations, and conservative relationship clues. Candidates still need human evidence review before becoming knowledge facts. An independent [Spring PetClinic public sample](docs/0.7.0-public-sample-review.md) exercises manually anchored facts through both published views and retrieval units; it does not establish automatic cross-repository pairing or live behavior. See the [implementation and review record](docs/0.7.0-implementation-report.md).

## What's new in 0.8.0

The optional retrieval view conservatively retains conditions and unknowns that span sections, merges generic headings within a module, and reports omitted glossaries and whole-source units needing review. A read-only [project-wide source-upgrade preview](docs/source-upgrade-preview.md) compares fixed Git commits and locates changed evidence, facts, topics, available retrieval units, and unattributed paths. A controlled two-commit PetClinic sample runs actual SQLite FTS5 over generated units; it establishes narrow retrieval evidence, not final model-answer or production correctness. The [retrieval import contract](docs/retrieval-contract.md) describes staged snapshot replacement. Default two-view publishing and the knowledge file protocol remain unchanged.

## Boundaries

Code2KB validates deterministic structure, fixed source anchors, digests, audience separation, and governance records. It does not prove natural-language correctness, production behavior, business policy, authorization decisions, external report truth, or reviewer identity.

The project contains no company-specific knowledge, bot deployment, vector database, or production credentials.

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before contributing. Report security issues through [SECURITY.md](SECURITY.md).

Licensed under the [Apache License 2.0](LICENSE).
