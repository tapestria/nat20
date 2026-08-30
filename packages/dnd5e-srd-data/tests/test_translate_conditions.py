"""C22 — rules-glossary condition pages → typed ``Condition`` entries."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dnd5e_srd_data.schema.condition import Condition, ConditionEffectKind
from tools.translators.conditions import (
    CONDITION_MECHANICS,
    SRD_CONDITION_SLUGS,
    translate_condition_pages,
)

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal" / "journals"


def _translate() -> dict[str, Condition]:
    out = translate_condition_pages(
        yaml_path=FIXTURE / "rules-glossary.yml",
        ingest_date=date(2026, 8, 27),
        ingest_version="foundry-translator-v1",
        require_complete=False,
    )
    return {c.slug: c for c in out}


def test_only_condition_pages_are_translated():
    by_slug = _translate()
    assert set(by_slug) == {"prone", "unconscious"}  # the rule page is skipped


def test_prone_carries_typed_effects_and_cleaned_prose():
    prone = _translate()["prone"]
    kinds = [e.kind for e in prone.effects]
    assert ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST in kinds
    assert ConditionEffectKind.DISADVANTAGE_OWN_ATTACKS in kinds
    adv = next(e for e in prone.effects if e.kind is ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST)
    assert adv.value == 5
    assert "within 5 feet" in adv.qualifier
    assert "<p>" not in prone.description
    assert "&amp;Reference" not in prone.description
    assert prone.provenance.srd_version == frozenset({"5.2"})
    assert prone.provenance.source_url.endswith("packs/_source/journals/rules-glossary.yml")


def test_unconscious_implies_incapacitated_and_prone_and_reference_markup_is_stripped():
    unconscious = _translate()["unconscious"]
    assert unconscious.implies == ["incapacitated", "prone"]
    assert "Incapacitated and Prone conditions" in unconscious.description


def test_mechanics_table_covers_exactly_the_srd_allowlist():
    assert set(CONDITION_MECHANICS) == set(SRD_CONDITION_SLUGS)
    assert len(SRD_CONDITION_SLUGS) == 15


def test_missing_srd_condition_is_a_hard_failure_when_complete_is_required():
    with pytest.raises(RuntimeError, match="missing SRD conditions"):
        translate_condition_pages(
            yaml_path=FIXTURE / "rules-glossary.yml",
            ingest_date=date(2026, 8, 27),
            ingest_version="foundry-translator-v1",
        )
