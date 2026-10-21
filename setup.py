"""Compatibility metadata for older pip/setuptools environments."""

from pathlib import Path
from setuptools import setup


ROOT = Path(__file__).resolve().parent

setup(
    name="code2kb-spec",
    version=(ROOT / "VERSION").read_text(encoding="utf-8").strip(),
    description="An evidence-aware specification and reference implementation for turning code into governed knowledge bases.",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    packages=["validation", "validation.adapters"],
    python_requires=">=3.9",
    license="Apache-2.0",
    entry_points={"console_scripts": ["code2kb=validation.knowledge:main"]},
)
