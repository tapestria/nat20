"""build_party_member folds always-on species + feature passives onto the spec.

Real lib data via BundledAssetLoader. The dwarf is the canonical case:
``trait_grants=['dr:poison']`` → poison resistance, and ``senses.darkvision=120``.
Activation-gated (Rage, disabled=true) and conditional-non-transfer
(Stonecunning, transfer=false) passives must NOT project at rest.
"""

import logging

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.build_party import build_party_member, granted_feature_slugs
from dnd5e_engine.build_spec import CombatInstance, make_build_spec

_LOADER = BundledAssetLoader()
_INST = CombatInstance(
    entity_id="char:1",
    name="Thrain",
    hp_current=30,
    hp_max=30,
    ac=16,
    attack_bonus=5,
    initiative=12,
    zone_id="zone:a",
)


def test_dwarf_gets_poison_resistance_and_darkvision():
    spec = build_party_member(
        make_build_spec(species_slug="dwarf", class_slug="barbarian", level=1),
        _INST,
        loader=_LOADER,
    )
    assert "poison" in spec.damage_resistances  # from trait_grants dr:poison
    assert spec.senses.darkvision == 120  # from Species.senses


def test_rage_resistances_not_projected_at_rest():
    # an L5 barbarian's Rage dr changes are disabled:true (activation-gated);
    # they must not appear on the resting spec.
    spec = build_party_member(
        make_build_spec(species_slug="dwarf", class_slug="barbarian", level=5),
        _INST,
        loader=_LOADER,
    )
    assert "slashing" not in spec.damage_resistances
    assert "piercing" not in spec.damage_resistances
    assert "bludgeoning" not in spec.damage_resistances


def test_dwarf_stonecunning_transfer_false_no_tremorsense_at_rest():
    # Stonecunning grants tremorsense 60 but is transfer:false (conditional) →
    # not always-on, so the resting spec must not carry tremorsense.
    spec = build_party_member(
        make_build_spec(species_slug="dwarf", class_slug="fighter", level=1),
        _INST,
        loader=_LOADER,
    )
    assert spec.senses.tremorsense is None
    # darkvision (species, always-on) still projects
    assert spec.senses.darkvision == 120


def test_movement_feature_change_not_projected_and_no_resistance_leak():
    # fast-movement (L5 barbarian, always-on) has a movement.walk change which
    # is deferred (skipped) — it must not corrupt resistances/senses.
    spec = build_party_member(
        make_build_spec(species_slug="dwarf", class_slug="barbarian", level=5),
        _INST,
        loader=_LOADER,
    )
    # poison still present from species; nothing spurious from the movement change
    assert spec.damage_resistances == ["poison"]


class _UnresolvableFeatureLoader:
    """Delegates to a real loader but makes every granted-feature slug
    fail to resolve, exercising the unresolved-slug branch."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def get_feature(self, slug):
        return None


def test_unresolved_granted_feature_slug_logs_warning_and_skips(caplog):
    # an L1 barbarian dwarf grants at least one feature; force every slug to
    # not resolve and assert each is logged at WARNING and skipped (no crash).
    build_spec = make_build_spec(species_slug="dwarf", class_slug="barbarian", level=1)
    expected_slugs = granted_feature_slugs(
        [_LOADER.get_class("barbarian"), None, _LOADER.get_species("dwarf")],
        level=1,
    )
    assert expected_slugs  # guard: the case must actually grant features

    with caplog.at_level(logging.WARNING, logger="dnd5e_engine.build_party"):
        spec = build_party_member(
            build_spec, _INST, loader=_UnresolvableFeatureLoader(_LOADER)
        )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == len(expected_slugs)
    logged_slugs = {r.granted_feature_slug for r in warnings}
    assert logged_slugs == set(expected_slugs)
    # skipped feature passives must not corrupt the spec; species poison stays
    assert spec.damage_resistances == ["poison"]
