"""Foundry pack prose cleanup. Deterministic, regex-grade."""

from __future__ import annotations

import re

_UUID_WITH_LABEL = re.compile(r"@UUID\[[^\]]+\]\{([^}]+)\}")
_UUID_NO_LABEL = re.compile(r"@UUID\[[^\]]*\.([^\].]+)\]")
_SAVE_MACRO = re.compile(r"\[\[/save\s+(\w+)\s+(\d+)\]\]")
# Block-level tags become paragraph breaks; inline tags get dropped.
# This avoids "</p><p>" silently merging adjacent words (e.g. staff-of-fire
# rendered as "wizard)Youhave"). Match opening + closing variants in one pass.
_HTML_BLOCK_TAG = re.compile(
    r"</?(?:p|div|br|li|ul|ol|h[1-6]|tr|td|table|thead|tbody|hr|blockquote|pre|section|article)\b[^>]*>",
    re.IGNORECASE,
)
_HTML_INLINE_TAG = re.compile(r"<[^>]+>")
_MULTI_BLANK = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")

_ABILITY_FULLNAME = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}


def cleanup_prose(text: str) -> str:
    text = _UUID_WITH_LABEL.sub(r"\1", text)
    text = _UUID_NO_LABEL.sub(r"\1", text)

    def _save(m: re.Match[str]) -> str:
        ability_short = m.group(1).lower()
        dc = m.group(2)
        ability_full = _ABILITY_FULLNAME.get(ability_short, ability_short.capitalize())
        return f"DC {dc} {ability_full} save"

    text = _SAVE_MACRO.sub(_save, text)
    text = _HTML_BLOCK_TAG.sub("\n", text)
    text = _HTML_INLINE_TAG.sub("", text)
    # Collapse multi-space artifacts left behind by tag deletion, and squeeze
    # runs of 3+ blank lines to a single paragraph break.
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    # Collapse single-newline soft-wraps inside paragraphs back to spaces so
    # consumer prose flows naturally. Paragraph breaks (double-newline) survive.
    lines = text.split("\n\n")
    lines = [re.sub(r"\s*\n\s*", " ", ln).strip() for ln in lines]
    return "\n\n".join(ln for ln in lines if ln).strip()
