"""C22 — dataset ``Condition`` model (SRD 5.2 rules-glossary conditions)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from dnd5e_srd_data.schema.common import Provenance, ReviewState
from dnd5e_srd_data.schema.condition import Condition, ConditionEffect, ConditionEffectKind


def _provenance() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="https://example.invalid/rules-glossary.yml",
        ingest_date=date(2026, 8, 27),
        ingest_version="foundry-translator-v1",
        srd_version=frozenset({"5.2"}),
    )


def test_condition_round_trips_with_typed_effects():
    prone = Condition(
        slug="prone",
        name="Prone",
        description="An attack roll against you has Advantage if the attacker is within 5 feet of you.",
        effects=[
            ConditionEffect(
                kind=ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST,
                value=5,
                qualifier="if the attacker is within 5 feet of you",
            ),
            ConditionEffect(kind=ConditionEffectKind.DISADVANTAGE_OWN_ATTACKS),
        ],
        implies=[],
        provenance=_provenance(),
        review=ReviewState(),
    )
    dumped = prone.model_dump(mode="json")
    assert dumped["effects"][0]["kind"] == "advantage_attacks_against"
    assert Condition.model_validate(dumped) == prone


def test_condition_effect_kind_is_closed():
    with pytest.raises(ValidationError):
        ConditionEffect.model_validate({"kind": "not_a_kind"})


def test_condition_effect_kind_has_exactly_the_documented_members():
    # The closed set Task 2's mechanics table is written against. Adding a
    # member is a schema change that must be reflected in that table.
    assert len(ConditionEffectKind) == 29
    assert ConditionEffectKind.AUTO_FAIL_SAVE.value == "auto_fail_save"


def test_implies_are_sibling_slugs():
    c = Condition(
        slug="unconscious",
        name="Unconscious",
        description="",
        implies=["incapacitated", "prone"],
        provenance=_provenance(),
        review=ReviewState(),
    )
    assert c.implies == ["incapacitated", "prone"]
