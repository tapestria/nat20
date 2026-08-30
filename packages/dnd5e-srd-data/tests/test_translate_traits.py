"""C22 — typed monster trait mechanics + the de-duplicated ``traits/`` category."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from dnd5e_srd_data.schema.monster import MonsterTraitMechanic
from tools.translators.foundry import (
    _TRAIT_MECHANICS,
    substitute_lookup_labels,
    translate_monster_traits,
    translate_monster_yaml,
)

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal" / "monsters"
INGEST = dict(ingest_date=date(2026, 8, 27), ingest_version="foundry-translator-v1")


def test_special_abilities_carry_a_typed_mechanic_when_known():
    m = translate_monster_yaml(yaml_path=FIXTURE / "hell-hound-lite.yml", **INGEST)
    by_slug = {a.slug: a for a in m.special_abilities}
    assert by_slug["magic-resistance"].mechanic is MonsterTraitMechanic.MAGIC_RESISTANCE
    assert by_slug["pack-tactics"].mechanic is MonsterTraitMechanic.PACK_TACTICS
    assert by_slug["odd-trait"].mechanic is None  # prose fallback
    # Actions (non-trait items) never get a mechanic.
    assert all(a.mechanic is None for a in m.actions)


def test_translate_monster_traits_dedupes_by_identifier_and_keeps_first_path():
    paths = [FIXTURE / "hell-hound-lite.yml", FIXTURE / "hell-hound-lite.yml"]
    traits = translate_monster_traits(paths, **INGEST)
    slugs = [t.slug for t in traits]
    assert slugs == ["magic-resistance", "odd-trait", "pack-tactics"]  # sorted, unique
    mr = traits[0]
    assert mr.mechanic is MonsterTraitMechanic.MAGIC_RESISTANCE
    assert mr.description == (
        "The monster has Advantage on saving throws against spells and other magical effects."
    )
    assert mr.provenance.source_url.endswith("monsters/hell-hound-lite.yml")


def test_unlicensed_and_placeholder_items_are_rejected_from_traits_but_kept_as_special_abilities():
    m = translate_monster_yaml(yaml_path=FIXTURE / "hell-hound-lite.yml", **INGEST)
    special_slugs = {a.slug for a in m.special_abilities}
    assert {"unlicensed-trait", "new-feature"} <= special_slugs

    traits = translate_monster_traits([FIXTURE / "hell-hound-lite.yml"], **INGEST)
    trait_slugs = {t.slug for t in traits}
    assert "unlicensed-trait" not in trait_slugs
    assert "new-feature" not in trait_slugs


def test_substitute_lookup_labels_keeps_the_label_text():
    assert (
        substitute_lookup_labels("The [[lookup @name lowercase]]{monster} bites.")
        == "The monster bites."
    )
    assert substitute_lookup_labels("no enricher") == "no enricher"


def test_every_mechanic_member_has_at_least_one_identifier_row():
    covered = set(_TRAIT_MECHANICS.values())
    assert covered == set(MonsterTraitMechanic)


def test_bare_item_id_tokens_are_labelled_with_the_sibling_name():
    m = translate_monster_yaml(yaml_path=FIXTURE / "hell-hound-lite.yml", **INGEST)
    multiattack = next(a for a in m.actions if a.slug == "multiattack")
    assert "[[/item .mmBite0000000000]]{Bite}" in multiattack.description
    assert "[[/item .mmClaw0000000000]]{Claw}" in multiattack.description
    # Unknown ids are left untouched (the engine's fallback still handles them).
    assert "[[/item .zzzzUnknownId000]] attacks" in multiattack.description
    # Already-labelled tokens are never double-labelled.
    assert "{Bite}{Bite}" not in multiattack.description
