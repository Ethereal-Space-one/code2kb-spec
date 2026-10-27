# Code2KB Spec

[简体中文](README.md) | **English**

Code2KB Spec helps teams turn **pinned Git revisions** into evidence-backed knowledge of business behavior and code logic. It provides an AI agent skill, file specification, templates, and Python reference tools. The agent reads and writes knowledge; the tools check structure, evidence, and release state.

> Current project version: `1.0.0`. New knowledge projects use the `c2kb-file/1` file protocol; existing `0.8.3` projects remain checkable and auditable. [Versioning](docs/versioning.md)

## What it does

- **Inventory scope:** record pages, actions, APIs, messages, scheduled jobs, and coverage gaps.
- **Build knowledge:** write business and engineering views from pinned code, with source anchors and explicit unknowns.
- **Review and release:** check impacts and claims, publish authorized views with a version manifest, then audit the snapshot.
- **Extend when needed:** build retrieval units or produce a [read-only source-upgrade review plan](docs/1.0.0-public-contract.md). The plan does not rewrite or approve knowledge.

This is a **knowledge-base production toolkit** for teams that need traceable answers across code repositories. It does not ship a domain knowledge base, bot, or hosted search service.

## Try the demo

Requires Git and Python 3.9+. The bundled demo needs no project configuration:

```bash
git clone https://github.com/Ethereal-Space-one/code2kb-spec.git
cd code2kb-spec
python3 -B examples/create_demo.py
```

The script creates a small source repository and knowledge project in a temporary directory, runs `check`, and prints the project path. It demonstrates the structure and validator; it does not generate a complete business knowledge base.

## Use your own code

1. **Create a separate knowledge project.** Copy the configuration template, remove unused example repositories, and set each repository's absolute local path and pinned commit SHA:

   ```bash
   python3 -m pip install -e .
   mkdir -p /path/to/knowledge-project
   cp templates/知识库配置.example.json /path/to/knowledge-project/知识库配置.json
   git -C /path/to/source-repo rev-parse HEAD
   ```

2. **Inventory before extraction.** Ask your coding agent to read the [Skill](skills/extract-app-knowledge/SKILL.md), verify the pinned commits, create `知识源/功能大纲.md`, then extract and write each module. A starting prompt:

   ```text
   Read <code2kb-spec-root>/skills/extract-app-knowledge/SKILL.md.
   The knowledge project is /path/to/knowledge-project. Verify its pinned source commits,
   inventory all in-scope entry points, and create 知识源/功能大纲.md.
   Record unknowns explicitly; do not infer production behavior from source alone.
   ```

3. **Check, review, and release.** Resolve module impact and claim reviews, prepare candidate packages, and obtain approval before publishing:

   ```bash
   code2kb check --project-root /path/to/knowledge-project
   code2kb publish --project-root /path/to/knowledge-project --release-id my-kb-v1
   code2kb audit-release --project-root /path/to/knowledge-project
   ```

   `publish` requires reviewed module packages; it will not work immediately after copying the template. See the [usage guide](docs/usage.md) for review commands and arguments. The tool does not decide business policy or grant release approval.

## Documentation

| Need | Read |
| --- | --- |
| Full workflow and commands | [Usage guide](docs/usage.md) |
| File, evidence, and release rules | [Specification](SPEC.md) |
| Optional retrieval units and evaluation | [Retrieval contract](docs/retrieval-contract.md) · [Evaluation guide](docs/retrieval-evaluation.md) |
| Changes and compatibility | [Changelog](CHANGELOG.md) · [Compatibility](docs/compatibility.md) |

**Limits:** source code alone cannot prove deployment, runtime behavior, or business policy. Without runtime evidence, retain `source_only` and unresolved questions. A retrieval hit is candidate evidence, not a verified final answer.

The normative specification is in Simplified Chinese; it controls if a translation differs. Contributions are welcome under the [contribution guide](CONTRIBUTING.md). Licensed under [Apache 2.0](LICENSE).
