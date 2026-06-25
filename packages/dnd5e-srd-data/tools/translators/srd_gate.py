"""SRD license gate — three-source agreement on SRD-ness.

Three sources:
- Foundry pack metadata (pack file's CC-BY-4.0 tag)
- open5e v2 doc partition (SRD slugs are in specific document IDs)
- 5e-bits/5e-database ``srd`` boolean

Unanimous TRUE → SRD passes. Anything else → quarantine to
non_srd_excluded.json with the reason recorded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SrdSourceVerdict:
    foundry_srd: bool | None
    open5e_srd: bool | None
    five_e_bits_srd: bool | None


@dataclass(frozen=True)
class GateDecision:
    is_srd: bool
    quarantine_reason: str | None


def gate_decision(v: SrdSourceVerdict) -> GateDecision:
    verdicts = [v.foundry_srd, v.open5e_srd, v.five_e_bits_srd]
    if any(x is None for x in verdicts):
        missing = [
            name
            for name, val in zip(["foundry", "open5e", "five_e_bits"], verdicts, strict=True)
            if val is None
        ]
        return GateDecision(is_srd=False, quarantine_reason=f"missing_source:{','.join(missing)}")
    if all(x is True for x in verdicts):
        return GateDecision(is_srd=True, quarantine_reason=None)
    if all(x is False for x in verdicts):
        return GateDecision(is_srd=False, quarantine_reason="unanimous_non_srd")
    return GateDecision(is_srd=False, quarantine_reason="disagreement")
