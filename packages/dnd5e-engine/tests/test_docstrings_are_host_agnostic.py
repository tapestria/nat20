"""Guards the engine's prose against private-host and campaign-internal leakage.

Docstrings in this package are rendered verbatim onto the public documentation
site by mkdocstrings. A reference to a private downstream application, an
internal planning phase, or a file that does not exist in this repository is a
documentation defect a reader cannot resolve — so it fails the build here
rather than shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "dnd5e_engine"
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Patterns that must never appear in engine source prose, with the reason a
#: reviewer would give for rejecting each.
FORBIDDEN: dict[str, str] = {
    r"\bTapestria\b": "names a private downstream application",
    r"\bEffectStore\b": "names a class that does not exist in this package",
    r"\beffect_store\b": "names a private host component",
    r"\bws_player_action\b": "names a private host entry point",
    r"\bAvrae\b": "names a retired third-party evaluator",
    r"\bRedis\b": "names host infrastructure the engine does not use",
    r"\bapp\.[a-z_]+\.": "references a private host module path",
    r"\bPhase \d": "campaign-internal planning reference",
    r"\bCluster \d": "campaign-internal planning reference",
    r"\bC\d\d-S\d\d": "campaign-internal scenario id",
    r"\biter-\d": "campaign-internal review-iteration reference",
    r"docs/(?:superpowers|agent-prompts|design)/": "path does not exist in this repo",
    r"\bspecs/": "path does not exist in this repo",
    r"CLAUDE\.md": "names a file that does not exist in this repo",
    r"(?i)\bruling\b": "campaign-internal decision reference",
    r"\bR\d+\b": "campaign-internal ruling id",
    r"\bspec §|\bD\d\b": "campaign-internal decision id",
    r"\b[Tt]asks? \d|\btask-\d|\btask brief\b": "campaign-internal planning reference",
    r"(?i)\bfix round\b": "campaign-internal review-iteration reference",
    r"\bWS\b|\bws_projection\b": "names a private host's transport",
    r"(?i)\bcodex\b": "campaign-internal review reference",
}

PY_FILES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("pattern,reason", list(FORBIDDEN.items()))
def test_no_forbidden_prose(pattern: str, reason: str) -> None:
    compiled = re.compile(pattern)
    hits = [
        f"{path.relative_to(SRC)}:{lineno}: {line.strip()}"
        for path in PY_FILES
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if compiled.search(line)
    ]
    assert not hits, f"{pattern} — {reason}:\n" + "\n".join(hits)


def test_referenced_repo_docs_exist() -> None:
    """Every ``docs/...md`` or ``BACKLOG.md`` path named in source must resolve."""
    referenced: set[str] = set()
    for path in PY_FILES:
        referenced.update(
            re.findall(r"(?:docs/[A-Za-z0-9_./-]+\.md|BACKLOG\.md)", path.read_text())
        )
    missing = sorted(ref for ref in referenced if not (REPO_ROOT / ref).is_file())
    assert not missing, f"source references documentation that does not exist: {missing}"


#: The public Markdown: every page the docs site renders and the repository's
#: own guides. Listed explicitly so an untracked local file never joins the scan.
_MARKDOWN_GLOBS = (
    "docs/**/*.md",
    "docs/llms.txt",
    "README.md",
    "CONTRIBUTING.md",
    "BACKLOG.md",
    "packages/*/README.md",
    "packages/*/CHANGELOG.md",
    "apps/*/README.md",
)
MARKDOWN_FILES = sorted({p for pattern in _MARKDOWN_GLOBS for p in REPO_ROOT.glob(pattern)})
#: The engine's test modules, this guard excepted: its patterns name what they forbid.
TEST_FILES = sorted(
    p for p in Path(__file__).resolve().parent.rglob("*.py") if p.name != Path(__file__).name
)

#: Labels the public Markdown must not carry. A product name may appear only
#: as a link's text, which is how the project credits its authors.
MARKDOWN_FORBIDDEN: dict[str, str] = {
    r"\bspecs/": "path does not exist in this repo",
    r"CLAUDE\.md": "names a file that does not exist in this repo",
    r"(?i)\bruling\b": "campaign-internal decision reference",
    r"\bR\d+\b": "campaign-internal ruling id",
    r"\b[Tt]asks? \d|\btask brief\b": "campaign-internal planning reference",
    r"(?i)\bfix round\b": "campaign-internal review-iteration reference",
    r"\bTapestria\b(?!\]\()": "names a private downstream application outside an attribution link",
}
#: Labels the engine's test prose must not carry.
TEST_FORBIDDEN: dict[str, str] = {
    r"\bspecs/": "path does not exist in this repo",
    r"(?i)\bruling\b": "campaign-internal decision reference",
    r"\bTapestria\b": "names a private downstream application",
    r"docs/(?:superpowers|agent-prompts|design)/": "path does not exist in this repo",
}


def _hits(paths: list[Path], pattern: str) -> list[str]:
    compiled = re.compile(pattern)
    return [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()[:120]}"
        for path in paths
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if compiled.search(line)
    ]


@pytest.mark.parametrize("pattern,reason", list(MARKDOWN_FORBIDDEN.items()))
def test_no_internal_labels_in_public_markdown(pattern: str, reason: str) -> None:
    assert len(MARKDOWN_FILES) > 20
    hits = _hits(MARKDOWN_FILES, pattern)
    assert not hits, f"{pattern} — {reason}:\n" + "\n".join(hits)


@pytest.mark.parametrize("pattern,reason", list(TEST_FORBIDDEN.items()))
def test_no_internal_labels_in_test_prose(pattern: str, reason: str) -> None:
    hits = _hits(TEST_FILES, pattern)
    assert not hits, f"{pattern} — {reason}:\n" + "\n".join(hits)
