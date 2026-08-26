"""C19 — Character derivation.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 19
(specs/catalog-v2/c19.md). Almost every scenario is a pure
``derive_sheet(CharacterBuildSpec) -> DerivedSheet`` call — no combat
handle required. ``derive_sheet``/``DerivedSheet`` do not exist on the
engine today; every scenario presumes them, imported inside the test
body (mirrors the ``dnd5e_engine.build_spec.derive_spell_slots`` idiom
C17 already uses) so their absence drives the xfail rather than a
collection error.
"""

from __future__ import annotations

from dnd5e_srd_data.loader import BundledAssetLoader

from tests.e2e.harness import xfail_cluster


@xfail_cluster(19, "character derivation")
def test_c19_s01_level1_hp_is_hit_die_max_plus_con_modifier_single_class_fighter():
    """C19-S01: SRD 5.2 §Character Creation, "Step 5: Choose Equipment...
    Hit Points" — "Your class and Constitution modifier determine your
    Hit Point maximum at level 1... Fighter, Paladin, or Ranger:
    10 + Con. modifier"
    (packs/_source/content24/chapter-2/character-creation.yml,
    _id: O1kCtOyXyxlJ1hz9). ``derive_sheet`` does not exist in the
    engine at all — HP arrives pre-computed on the host-supplied
    ``CombatInstance`` today, and ``CharacterBuildSpec.classes``
    (multiclass dict) is not yet a field either.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    assert loader.get_class("fighter").hit_die == "d10"

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 1},  # API delta (C19): multiclass dict, not class_slug
        ability_scores={"constitution": 14},
        level=1,
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.hp_max == 12


@xfail_cluster(19, "character derivation")
def test_c19_s02_level5_hp_accumulates_fixed_per_level_gains():
    """C19-S02: SRD 5.2 §Character Creation, "Gaining a Level" — "Each
    time you gain a level, you gain an additional Hit Die... Fixed Hit
    Points by Class table: Fighter, Paladin, or Ranger: 6 + Con.
    modifier" (packs/_source/content24/chapter-2/character-creation.yml,
    _id: iHbj5aJvc1T7i5YI). Level 1: 10 + 2 = 12; levels 2-5 (4 more) at
    6 + 2 = 8 each -> 12 + 4*8 = 44 (the c19 rule card's "12 + 4x7 = 40"
    shorthand is informal and inconsistent with the SRD table it cites;
    this scenario asserts the table-derived 44). No per-level HP
    accumulation exists anywhere in the engine today.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 5},  # API delta (C19)
        ability_scores={"constitution": 14},
        level=5,
        hp_mode="fixed",  # API delta (C19)
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.hp_max == 44


@xfail_cluster(19, "character derivation")
def test_c19_s03_chain_mail_ac_ignores_dex_shield_stacks_plus2():
    """C19-S03: SRD 5.2 §Equipment, Armor Table — "your AC is 16 in
    Chain Mail" (heavy armor, no DEX bonus); shields "+2" flat, stacking
    with body armor (packs/_source/content24/chapter-6/equipment.yml,
    _id: adlJqek4sIyJePKO). Verified corpus:
    ``loader.get_armor("chain-mail")`` -> ``base_ac=16, dex_bonus_max=0``;
    ``loader.get_armor("shield")`` -> ``base_ac=2``. No AC computation
    exists in the engine today; ``Armor.base_ac``/``dex_bonus_max`` are
    read nowhere in ``src/``.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    chain_mail = loader.get_armor("chain-mail")
    assert chain_mail.base_ac == 16
    assert chain_mail.dex_bonus_max == 0

    spec_a = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 1},  # API delta (C19)
        ability_scores={"dexterity": 18},
        equipment=("chain-mail",),
        level=1,
    )
    spec_b = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 1},
        ability_scores={"dexterity": 18},
        equipment=("chain-mail", "shield"),
        level=1,
    )
    sheet_a = derive_sheet(spec_a, loader=loader)
    sheet_b = derive_sheet(spec_b, loader=loader)

    assert sheet_a.ac == 16
    assert sheet_b.ac == 18


@xfail_cluster(19, "character derivation")
def test_c19_s04_scale_mail_caps_dex_bonus_at_plus2():
    """C19-S04: SRD 5.2 §Equipment, Armor Table — medium armor caps the
    DEX bonus; Scale Mail's base AC is "14 + Dex modifier (max 2)"
    (packs/_source/content24/chapter-6/equipment.yml, _id:
    adlJqek4sIyJePKO). Verified corpus: ``loader.get_armor("scale-mail")``
    -> ``base_ac=14, dex_bonus_max=2``. Same AC-computation gap as S03.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    scale_mail = loader.get_armor("scale-mail")
    assert scale_mail.base_ac == 14
    assert scale_mail.dex_bonus_max == 2

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"rogue": 1},  # API delta (C19)
        ability_scores={"dexterity": 20},
        equipment=("scale-mail",),
        level=1,
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.ac == 16


@xfail_cluster(19, "character derivation")
def test_c19_s05_unarmored_defense_barbarian_replaces_base_with_dex_plus_con():
    """C19-S05: SRD 5.2, Barbarian class feature Unarmored Defense —
    "your base Armor Class equals 10 plus your Dexterity and
    Constitution modifiers"
    (raw_sources/foundry/packs/_source/classes24/barbarian/class-features/unarmored-defense.yml).
    ``activities/passive_stats.py`` explicitly defers the ``ac.calc``
    key into ``skipped_keys`` — no consumer computes this alternative
    AC mode today.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"barbarian": 1},  # API delta (C19)
        ability_scores={"dexterity": 14, "constitution": 16},
        equipment=(),
        level=1,
        ac_calc_mode="unarmored_barbarian",  # API delta (C19)
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.ac == 15


@xfail_cluster(19, "character derivation")
def test_c19_s06_save_and_skill_proficiencies_derive_from_class_and_background():
    """C19-S06: SRD 5.2 §Character Creation, "Note Proficiencies" —
    "Your background gives proficiency in two skills... Your class
    also gives proficiencies"
    (packs/_source/content24/chapter-2/character-creation.yml,
    _id: t1WP9VEevo4TOTXw). Verified corpus:
    ``loader.get_class("fighter").saving_throws ==
    frozenset({"str", "con"})``; ``loader.get_background("soldier")
    .skill_proficiencies == ["ath", "itm"]``. ``CharacterBuildSpec`` has
    no ``background_slug`` field at all today; ``Class.saving_throws``
    and ``Background.skill_proficiencies`` are shipped corpus data with
    zero consumers.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    assert loader.get_class("fighter").saving_throws == frozenset({"str", "con"})
    assert loader.get_background("soldier").skill_proficiencies == ["ath", "itm"]

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 1},  # API delta (C19)
        background_slug="soldier",  # API delta (C19)
        ability_scores={},
        level=1,
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.save_proficiencies == frozenset({"str", "con"})
    assert frozenset({"ath", "itm"}) <= sheet.skill_proficiencies


@xfail_cluster(19, "character derivation")
def test_c19_s07_asi_at_level4_from_selected_choices_raises_ability_score():
    """C19-S07: SRD 5.2 §Character Creation, "Gaining a Level" step 5,
    "Adjust Ability Modifiers... your ability modifier also changes if
    the new score is an even number"
    (packs/_source/content24/chapter-2/character-creation.yml,
    _id: iHbj5aJvc1T7i5YI). ``AdvancementType.ABILITY_SCORE_IMPROVEMENT``
    is ignored entirely by ``build_party.py``/``activities/scale.py``
    today (only ``SCALE_VALUE`` is walked); ``selected_choices`` is
    accepted on the model but read nowhere.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 4},  # API delta (C19)
        ability_scores={"strength": 16},
        level=4,
        selected_choices=("asi:4:strength+2",),
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.ability_scores.strength == 18
    assert sheet.ability_modifiers["strength"] == 4


@xfail_cluster(19, "character derivation")
def test_c19_s08_subclass_below_level3_is_rejected():
    """C19-S08: SRD 5.2 §Character Creation, "Step 4: Choose a Class" /
    "Gaining a Level" — the subclass is a ``Subclass``-type advancement
    gated at level 3 (packs/_source/content24/chapter-2/character-creation.yml,
    _id: iHbj5aJvc1T7i5YI; corpus-verified every SRD 5.2 class's
    ``Subclass`` advancement entry carries ``level: 3``).
    ``build_party.py:59-68`` accepts ``build_spec.subclass_slug``
    unconditionally at any level today — no validation exists.
    """
    import pytest

    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 2},  # API delta (C19)
        subclass_slug="champion",
        level=2,
    )
    with pytest.raises(ValueError):
        derive_sheet(build_spec, loader=loader)


@xfail_cluster(19, "character derivation")
def test_c19_s09_multiclass_fighter3_rogue2_hp_and_proficiency_bonus():
    """C19-S09: SRD 5.2 §Character Creation, "Multiclassing" — "You gain
    the level 1 Hit Points for a class only when your total character
    level is 1"; "if you are a level 3 Fighter / level 2 Rogue, you
    have the Proficiency Bonus of a level 5 character, which is +3"
    (packs/_source/content24/chapter-2/character-creation.yml,
    _id: vcs4jfEKRxPCsgXm). ``CharacterBuildSpec.class_slug`` is
    single-class only today — this setup cannot even be constructed.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    assert loader.get_class("fighter").hit_die == "d10"
    assert loader.get_class("rogue").hit_die == "d8"

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 3, "rogue": 2},  # API delta (C19)
        ability_scores={"constitution": 14},
        level=5,
        hp_mode="fixed",
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.hp_max == 12 + 2 * 8 + 2 * 7 == 42
    assert sheet.proficiency_bonus == 3
    assert sheet.extra_attack_count == 1


@xfail_cluster(19, "character derivation")
def test_c19_s10_jack_of_all_trades_adds_floor_pb_over_2_to_non_proficient_check():
    """C19-S10: SRD 5.2, Bard class feature Jack of All Trades — "You
    can add half your Proficiency Bonus (round down) to any ability
    check you make that uses a skill proficiency you lack"
    (raw_sources/foundry/packs/_source/classes24/bard/class-features/jack-of-all-trades.yml).
    ``rules/skills.py::skill_check(..., jack_of_all_trades=...)``
    already implements the formula, but ``CheckSpec`` has no
    ``jack_of_all_trades`` field today — ``resolve_check`` never passes
    it through.
    """
    import random

    from dnd5e_engine.check import CheckSpec, resolve_check

    base_spec = CheckSpec(
        kind="skill",
        skill="arcana",
        ability_scores={"intelligence": 12},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=3,
        rng=random.Random(1),
    )
    joat_spec = CheckSpec(
        kind="skill",
        skill="arcana",
        ability_scores={"intelligence": 12},
        proficient_skills=(),
        proficient_saves=(),
        proficiency_bonus=3,
        rng=random.Random(1),
        jack_of_all_trades=True,  # API delta (C19)
    )

    base = resolve_check(base_spec)
    joat = resolve_check(joat_spec)

    assert joat.modifier - base.modifier == 1
    assert joat.roll_total - base.roll_total == 1


@xfail_cluster(19, "character derivation")
def test_c19_s11_fourth_attuned_item_rejected_at_3_item_cap():
    """C19-S11: SRD 5.2 §Appendix, "Attunement" — "A creature can have
    Attunement with no more than three magic items at a time."
    (packs/_source/content24/appendices/rules-glossary.yml, name:
    Attunement). ``Item.requires_attunement``/``attunement_constraint``
    are shipped with zero consumers; ``PartyMemberSpec``/``Combatant``
    carry only a flat ``equipment`` slug list with no attuned-subset
    tracking at all.
    """
    import pytest

    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    items = ("ring-of-protection", "cloak-of-protection", "amulet-of-health", "boots-of-speed")
    for slug in items:
        assert loader.get_item(slug).requires_attunement is True

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"wizard": 5},  # API delta (C19)
        equipment=items,
        attuned_items=items,  # API delta (C19)
        level=5,
    )
    with pytest.raises(ValueError):
        derive_sheet(build_spec, loader=loader)


@xfail_cluster(19, "character derivation")
def test_c19_s12_heavy_armor_without_str_requirement_imposes_flat_speed_penalty():
    """C19-S12: SRD 5.2 §Equipment, armor rules preamble — "that armor
    reduces the wearer's speed by 10 feet unless the wearer has a
    Strength score equal to or higher than the listed score"
    (packs/_source/content24/chapter-6/equipment.yml, _id:
    flJnTPWIwTrAzqTi). Verified corpus:
    ``loader.get_armor("chain-mail").strength_min == 13``.
    ``Armor.strength_min`` has zero consumers anywhere — no
    speed-penalty apply logic exists in the engine or bridge.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_sheet

    loader = BundledAssetLoader()
    assert loader.get_armor("chain-mail").strength_min == 13

    build_spec = CharacterBuildSpec(
        species_slug="human",
        classes={"fighter": 1},  # API delta (C19)
        ability_scores={"strength": 11},
        equipment=("chain-mail",),
        level=1,
    )
    sheet = derive_sheet(build_spec, loader=loader)

    assert sheet.base_speed == 20
