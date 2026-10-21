# Code2KB Spec

[简体中文](README.md) | **English**

Code2KB Spec is an open specification for turning fixed source revisions into traceable, reviewable, and publishable knowledge bases. The repository also provides a Python reference implementation, an AI agent skill, templates, and stack adapters.

> Project version: `0.2.0`; knowledge specification version: `0.8.3`. They evolve independently.

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

## 0.2.0 highlights

- safe environment-variable repository paths;
- separate human and policy-based automated review modes;
- semantic gates for high-impact fields, configuration keys, and document consistency;
- a closed evidence chain for business intent;
- strict JSON, review provenance, and artifact-only release audits;
- an installable `code2kb` command.

## Boundaries

Code2KB validates deterministic structure, fixed source anchors, digests, audience separation, and governance records. It does not prove natural-language correctness, production behavior, business policy, authorization decisions, external report truth, or reviewer identity.

The project contains no company-specific knowledge, bot deployment, vector database, or production credentials.

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before contributing. Report security issues through [SECURITY.md](SECURITY.md).

Licensed under the [Apache License 2.0](LICENSE).
