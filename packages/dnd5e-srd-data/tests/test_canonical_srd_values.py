"""Real-SRD-value assertions against canonical output.

Catches translator regressions where fixture tests miss real-pack shapes.
Each assertion is keyed to a codex Phase 7a PR 1 review finding.
"""

from __future__ import annotations

from dnd5e_srd_data import Armor, BundledAssetLoader, Item, ItemRarity, MagicItem, Weapon


def test_armored_monster_ac_populated_when_foundry_provides_flat():
    """Codex P1 #1: the translator must surface Foundry's flat AC when present
    rather than a silent AC=10 default. 2024 actors24 ships a concrete flat AC
    for goblin-warrior (15) and aboleth (17)."""
    loader = BundledAssetLoader()
    goblin = loader.get_monster("goblin-warrior")
    assert goblin is not None
    assert goblin.ac == 15, f"goblin-warrior AC must be 15 (2024 SRD), got {goblin.ac}"
    # Unarmored creatures DO ship flat AC and must populate:
    aboleth = loader.get_monster("aboleth")
    assert aboleth is not None and aboleth.ac == 17


def test_proficiency_bonus_derived_from_cr():
    """Codex P1 #2: proficiency bonus must scale with CR, not hard-coded to 2."""
    loader = BundledAssetLoader()
    pit_fiend = loader.get_monster("pit-fiend")
    assert pit_fiend is not None
    assert pit_fiend.cr == 20
    assert pit_fiend.proficiency_bonus == 6, (
        f"CR 20 monster must have prof=6 per SRD table, got {pit_fiend.proficiency_bonus}"
    )
    # Spot-check several CR tiers:
    goblin = loader.get_monster("goblin-warrior")
    assert goblin is not None and goblin.cr == 0.25 and goblin.proficiency_bonus == 2


def test_imp_damage_immunities_have_actual_types_not_dict_keys():
    """Codex P1 #3: traits.di is a dict {value, bypasses}; translator must read .value."""
    loader = BundledAssetLoader()
    imp = loader.get_monster("imp")
    assert imp is not None
    # Imp SRD: damage immunities fire, poison; condition immunity poisoned.
    assert "fire" in imp.damage_immunities, imp.damage_immunities
    assert "poison" in imp.damage_immunities, imp.damage_immunities
    assert "poisoned" in imp.condition_immunities, imp.condition_immunities
    # The bug was emitting ['value', 'bypasses', 'custom']:
    for forbidden in ("value", "bypasses", "custom"):
        assert forbidden not in imp.damage_immunities
        assert forbidden not in imp.condition_immunities


def test_very_rare_camelcase_normalized():
    """Codex P2 #1: rarity 'veryRare' must classify as ItemRarity.VERY_RARE."""
    loader = BundledAssetLoader()
    animated_shield = loader.get_armor("animated-shield")
    assert animated_shield is not None
    assert animated_shield.rarity == ItemRarity.VERY_RARE, (
        f"animated-shield rarity must be very_rare, got {animated_shield.rarity}"
    )


def test_thrown_weapon_preserves_range():
    """Codex P2 #2: dagger has thrown range 20/60 even though kind is melee."""
    loader = BundledAssetLoader()
    dagger = loader.get_weapon("dagger")
    assert dagger is not None
    # Dagger SRD: melee dagger, thrown range 20/60.
    assert dagger.range.value == 20, (
        f"dagger thrown range value should be 20, got {dagger.range.value}"
    )
    assert dagger.range.long == 60, (
        f"dagger thrown range long should be 60, got {dagger.range.long}"
    )


def test_goblin_stealth_is_real_srd_bonus_not_rank():
    """Iter 2 #1: Foundry skills.<short>.value is rank (0/1/2), not the bonus.
    2024 Goblin Warrior: dex 15 (+2) × expertise (rank 2) × prof 2 = +6 stealth."""
    loader = BundledAssetLoader()
    goblin = loader.get_monster("goblin-warrior")
    assert goblin is not None
    assert goblin.skills.stealth == 6, (
        f"Goblin Stealth must be +6 (SRD), got {goblin.skills.stealth}"
    )
    # Non-proficient skills are omitted (None) rather than serialized as 0.
    assert goblin.skills.perception is None, (
        f"Goblin has no Perception proficiency; expected None, got {goblin.skills.perception}"
    )
    assert goblin.skills.acrobatics is None
    assert goblin.skills.athletics is None


def test_pit_fiend_saves_derived_from_proficient_flag():
    """Iter 2 #2: Foundry leaves abilities.<ab>.save null; derive from
    abilities.<ab>.proficient (0/1) + ability_mod + prof_bonus."""
    loader = BundledAssetLoader()
    pit_fiend = loader.get_monster("pit-fiend")
    assert pit_fiend is not None
    # 2024 actors24 pit-fiend marks dex/wis proficient (NOT con/str/int/cha —
    # the 2024 stat block dropped the Con save proficiency). Prof bonus = 6.
    # dex 14 → +2 + 6 = +8; wis 18 → +4 + 6 = +10.
    assert pit_fiend.saving_throws.dex == 8, pit_fiend.saving_throws.dex
    assert pit_fiend.saving_throws.wis == 10, pit_fiend.saving_throws.wis
    # Non-proficient saves stay None.
    assert pit_fiend.saving_throws.con is None
    assert pit_fiend.saving_throws.str is None
    assert pit_fiend.saving_throws.int is None
    assert pit_fiend.saving_throws.cha is None


def test_holy_avenger_carries_attunement_metadata():
    """requires_attunement comes from Foundry's structural flag; the
    constraint qualifier ('by a paladin') is now extracted from description
    prose by the translator (Phase 7a PR1 oracle pass)."""
    loader = BundledAssetLoader()
    holy = loader.get_weapon("holy-avenger")
    assert holy is not None
    assert holy.requires_attunement is True
    assert holy.attunement_constraint == "by a Paladin", holy.attunement_constraint


def test_monster_languages_include_custom_text():
    """Iter 3 P1 #1: traits.languages.custom free-text must flow into canonical
    languages. 2024 skeleton: 'Understands Common plus one other language but
    can't speak' lives only in the custom field."""
    loader = BundledAssetLoader()
    skeleton = loader.get_monster("skeleton")
    assert skeleton is not None
    joined = " | ".join(skeleton.languages)
    assert "but can" in joined.lower(), skeleton.languages


def test_assassin_languages_no_sentinel():
    """Iter 3 P1 #1: literal 'custom' sentinel must not leak into the
    structured language list (assassin had ['cant', 'custom'] previously).
    2024 assassin speaks Common + Thieves' Cant."""
    loader = BundledAssetLoader()
    assassin = loader.get_monster("assassin")
    assert assassin is not None
    assert "custom" not in assassin.languages, assassin.languages
    assert "Common" in assassin.languages, assassin.languages


def test_attunement_constraint_extracted_from_prose():
    """Magic-item attunement constraints ('by a paladin', etc.) are now
    extracted from the description prose by the foundry translator. Items
    that don't ship a 'by ...' qualifier in their description retain
    attunement_constraint = None."""
    loader = BundledAssetLoader()
    holy = loader.get_weapon("holy-avenger")
    assert holy is not None and holy.attunement_constraint == "by a Paladin"


def test_ingest_date_matches_pins():
    """Iter 3 P2 #2: regen sources ingest_date from PINS.json, not
    date.today(). All canonical entries' provenance.ingest_date must equal
    PINS.foundry.pinned_date for deterministic regen across calendar days."""
    import json
    from datetime import date
    from pathlib import Path

    pins_path = Path(__file__).resolve().parent.parent / "raw_sources" / "PINS.json"
    pinned = date.fromisoformat(json.loads(pins_path.read_text())["foundry"]["pinned_date"])

    loader = BundledAssetLoader()
    for slug in ("goblin-warrior", "aboleth", "commoner"):
        m = loader.get_monster(slug)
        assert m is not None
        assert m.provenance.ingest_date == pinned, (slug, m.provenance.ingest_date)
    for slug in ("longsword", "club", "holy-avenger"):
        w = loader.get_weapon(slug)
        assert w is not None
        assert w.provenance.ingest_date == pinned, (slug, w.provenance.ingest_date)


def test_goblin_senses_use_none_for_unavailable():
    """Iter 2 #4: Foundry ships 0/null for absent senses; schema uses None
    ('unavailable'). Also: passive_perception is derived (not shipped). 2024
    actors24 nest per-sense ranges under senses.ranges — the translator must
    read that nested shape (darkvision 60 for goblin-warrior)."""
    loader = BundledAssetLoader()
    goblin = loader.get_monster("goblin-warrior")
    assert goblin is not None
    assert goblin.senses.blindsight is None
    assert goblin.senses.tremorsense is None
    assert goblin.senses.truesight is None
    assert goblin.senses.darkvision == 60
    # Goblin: wis 8 → -1, not perception proficient → 10 + -1 = 9.
    assert goblin.senses.passive_perception == 9, (
        f"Goblin passive perception must be 9 (10 + wis mod -1), "
        f"got {goblin.senses.passive_perception}"
    )


def test_provenance_url_preserves_nested_pack_path():
    """Iter 2 #5: source_url must include the full nested 2024 pack path
    (equipment24/weapons/<category>/, actors24/<type>/), not just the immediate
    parent."""
    loader = BundledAssetLoader()
    longsword = loader.get_weapon("longsword")
    assert longsword is not None
    assert "equipment24/weapons/martial-melee/longsword.yml" in longsword.provenance.source_url, (
        longsword.provenance.source_url
    )
    aboleth = loader.get_monster("aboleth")
    assert aboleth is not None
    assert "actors24/aberration/aboleth.yml" in aboleth.provenance.source_url, (
        aboleth.provenance.source_url
    )


def test_club_price_converts_silver_to_gp():
    """Codex P2 #3: club is 1 sp; cost_gp must be 0.1, not 1.0."""
    loader = BundledAssetLoader()
    club = loader.get_weapon("club")
    assert club is not None
    assert club.cost_gp == 0.1, f"club cost_gp must be 0.1 (1 sp), got {club.cost_gp}"


def test_rarity_bearing_item_is_magic_item():
    """Codex iter-6 P3: items that carry a rarity grade classify as MagicItem.
    2024 bag-of-holding ships rarity 'uncommon'. (2024 Foundry ships
    potion-of-healing with an EMPTY rarity in adventuring-gear, so it correctly
    surfaces as a plain Item — the magic classification keys off rarity.)"""
    loader = BundledAssetLoader()
    bag = loader.get_item("bag-of-holding")
    assert bag is not None
    assert isinstance(bag, MagicItem), f"got {type(bag).__name__}"
    potion = loader.get_item("potion-of-healing")
    assert potion is not None
    assert isinstance(potion, Item) and not isinstance(potion, MagicItem)


def test_mundane_gear_is_plain_item():
    """Codex iter-6 P2: mundane gear is Item not MagicItem. (2024 SRD dropped
    the abacus; bedroll is the equivalent rarity-less adventuring-gear entry.)"""
    loader = BundledAssetLoader()
    bedroll = loader.get_item("bedroll")
    assert bedroll is not None
    assert isinstance(bedroll, Item) and not isinstance(bedroll, MagicItem)


def test_longsword_is_weapon():
    loader = BundledAssetLoader()
    item = loader.get_item("longsword")
    assert isinstance(item, Weapon)


def test_chain_shirt_is_armor():
    loader = BundledAssetLoader()
    item = loader.get_item("chain-shirt")
    assert isinstance(item, Armor)


def test_goblin_has_action_named_scimitar():
    """Codex iter-7 P1: monster actions must be extracted from Foundry's
    embedded items[] array, not stubbed as []."""
    loader = BundledAssetLoader()
    goblin = loader.get_monster("goblin-warrior")
    action_slugs = {a.slug for a in goblin.actions}
    assert "scimitar" in action_slugs, f"goblin actions: {action_slugs}"


def test_aboleth_has_tentacle_action():
    """Codex iter-7 P1: aboleth's Tentacle is a weapon attack action."""
    loader = BundledAssetLoader()
    aboleth = loader.get_monster("aboleth")
    action_slugs = {a.slug for a in aboleth.actions}
    assert "tentacle" in action_slugs, f"aboleth actions: {action_slugs}"


def test_adult_red_dragon_has_legendary_actions():
    """Codex iter-7 P1: legendary actions bucket populated for legendary
    creatures, with per-action legendary_cost preserved from activation.value.
    2024 redesigned the dragon legendary suite (Commanding Presence / Fiery
    Rays / Pounce), each a 1-cost action."""
    loader = BundledAssetLoader()
    dragon = loader.get_monster("adult-red-dragon")
    assert dragon.legendary_actions, "expected non-empty legendary_actions"
    assert all(a.legendary_cost == 1 for a in dragon.legendary_actions), (
        f"2024 adult-red-dragon legendary actions are all 1-cost; "
        f"got {[(a.name, a.legendary_cost) for a in dragon.legendary_actions]}"
    )


def test_backpack_landed_in_canonical():
    """Codex iter-7 P2/P3: container/ pack walked AND _container.yml docs
    survive the underscore filter."""
    loader = BundledAssetLoader()
    backpack = loader.get_item("backpack")
    assert backpack is not None
    assert isinstance(backpack, Item) and not isinstance(backpack, MagicItem)


def test_pouch_landed_in_canonical():
    """Codex iter-7 P2: mundane container gear surfaces as Item."""
    loader = BundledAssetLoader()
    pouch = loader.get_item("pouch")
    assert pouch is not None
    assert isinstance(pouch, Item) and not isinstance(pouch, MagicItem)


def test_staff_is_weapon():
    """Codex iter-9: spellcasting-focus/staff.yml is type: weapon — must
    dispatch to the weapon translator (not the generic item one) so damage
    parts survive into canonical."""
    loader = BundledAssetLoader()
    staff = loader.get_weapon("staff")
    assert staff is not None, "staff should be loadable as a Weapon"
    assert staff.damage_parts, f"staff.damage_parts empty: {staff.damage_parts}"


def test_aboleth_dominate_mind_has_uses_per_day():
    """Codex iter-9: Foundry encodes per-day caps as system.uses.max with a
    recovery period of 'day'. 2024 Aboleth's Dominate Mind (the 2024 rename of
    the 2014 Enslave action) is 2/day."""
    loader = BundledAssetLoader()
    aboleth = loader.get_monster("aboleth")
    assert aboleth is not None
    candidates = [
        *aboleth.actions,
        *aboleth.special_abilities,
        *aboleth.legendary_actions,
        *aboleth.lair_actions,
    ]
    dominate = next((a for a in candidates if a.name == "Dominate Mind"), None)
    assert dominate is not None, "aboleth missing Dominate Mind action"
    assert dominate.uses_per_day == 2, f"got uses_per_day={dominate.uses_per_day}"


# ---------------------------------------------------------------------------
# Phase 7a PR 2: spells / species / classes / subclasses
# ---------------------------------------------------------------------------


def test_fireball_surface_fields():
    """Fireball: 3rd-level evocation, V/S/M, 150 ft, instant, action, not ritual,
    not concentration. Material is non-cost (bat guano + sulfur)."""
    loader = BundledAssetLoader()
    fb = loader.get_spell("fireball")
    assert fb is not None
    assert fb.level == 3
    assert fb.school == "evo"
    assert set(fb.components) == {"V", "S", "M"}
    assert fb.ritual is False
    assert fb.concentration is False
    assert fb.casting_time.unit == "action" and fb.casting_time.value == 1
    assert fb.range.units == "ft" and fb.range.value == 150
    assert fb.duration.units == "inst"
    assert "guano" in fb.materials.value.lower()
    assert fb.materials.cost == 0


def test_revivify_material_consumed_and_cost():
    """Revivify carries a structured material flag + consumed flag. The 2024
    spells24 pack ships ``materials.cost = 0`` (the gp value lives only in the
    prose 'a diamond worth 300+ GP, which the spell consumes') — the translator
    preserves the structured field verbatim rather than parsing prose, so the
    mechanical facts we assert are the consumed flag + the diamond requirement."""
    loader = BundledAssetLoader()
    rev = loader.get_spell("revivify")
    assert rev is not None
    assert rev.materials.consumed is True
    assert "diamond" in rev.materials.value.lower()


def test_alarm_is_ritual():
    """Alarm carries the ritual property in Foundry's properties[]; canonical
    surfaces it as a structured bool."""
    loader = BundledAssetLoader()
    alarm = loader.get_spell("alarm")
    assert alarm is not None
    assert alarm.ritual is True


def test_concentration_flag_for_bless():
    """Bless requires concentration."""
    loader = BundledAssetLoader()
    bless = loader.get_spell("bless")
    assert bless is not None
    assert bless.concentration is True


def test_dwarf_size_and_speed():
    """2024 Dwarf: medium size (from Size advancement), 30 ft walk speed."""
    loader = BundledAssetLoader()
    dwarf = loader.get_species("dwarf")
    assert dwarf is not None
    assert dwarf.size == "medium"
    assert dwarf.movement.walk == 30


def test_human_size_medium():
    """2024 Human is Small or Medium (chosen at creation). Foundry's Size
    advancement ships ['sm', 'med']; the translator must resolve the standard
    playable default (medium) when multiple sizes include medium, matching the
    5e-bits oracle. Single-size species are unaffected."""
    loader = BundledAssetLoader()
    human = loader.get_species("human")
    assert human is not None
    assert human.size == "medium"


def test_dragonborn_humanoid():
    """All SRD species classify as humanoid."""
    loader = BundledAssetLoader()
    db = loader.get_species("dragonborn")
    assert db is not None
    assert db.creature_type.value == "humanoid"


def test_high_elf_darkvision():
    """2024 High Elf gets 60 ft darkvision per SRD; should round-trip via
    system.senses.darkvision."""
    loader = BundledAssetLoader()
    he = loader.get_species("elf-high")
    assert he is not None
    assert he.senses.darkvision == 60


def test_fighter_hit_die_and_advancement():
    """Fighter hit die is d10; advancement array preserves multiple entries."""
    loader = BundledAssetLoader()
    fighter = loader.get_class("fighter")
    assert fighter is not None
    assert fighter.hit_die == "d10"
    assert len(fighter.advancement) >= 5
    # At least one HitPoints entry per the SRD class spec.
    assert any(a.type == "HitPoints" for a in fighter.advancement)


def test_wizard_full_spellcaster():
    """Wizard: full progression, int caster. ``preparation`` is empty on the
    class document itself — Foundry encodes that at the character/spellbook
    level rather than on the class definition, so canonical reflects an empty
    string here."""
    loader = BundledAssetLoader()
    wiz = loader.get_class("wizard")
    assert wiz is not None
    assert wiz.spellcasting.progression == "full"
    assert wiz.spellcasting.ability == "int"


def test_barbarian_no_spellcasting():
    """Barbarian has no spellcasting."""
    loader = BundledAssetLoader()
    barb = loader.get_class("barbarian")
    assert barb is not None
    assert barb.spellcasting.progression == "none"


def test_champion_subclass_parent_link():
    """Champion is a Fighter subclass — class_identifier links to 'fighter'."""
    loader = BundledAssetLoader()
    champ = loader.get_subclass("champion")
    assert champ is not None
    assert champ.class_identifier == "fighter"


# ---------------------------------------------------------------------------
# PR 4a: 2024 weapon mastery + inline monster activities
# ---------------------------------------------------------------------------


def test_weapon_mastery_is_translated():
    """2024 SRD adds a Weapon Mastery property per weapon (system.mastery.value).
    The translator surfaces it onto Weapon.mastery; e.g. greatsword=Graze,
    longsword=Sap, dagger=Nick."""
    loader = BundledAssetLoader()
    greatsword = loader.get_weapon("greatsword")
    assert greatsword is not None
    assert greatsword.mastery == "graze", f"greatsword mastery: {greatsword.mastery!r}"
    longsword = loader.get_weapon("longsword")
    assert longsword is not None and longsword.mastery == "sap", longsword.mastery
    dagger = loader.get_weapon("dagger")
    assert dagger is not None and dagger.mastery == "nick", dagger.mastery


def test_monster_action_carries_inline_activities():
    """2024 actors24 embed resolvable activities inline on each action item; the
    translator populates Action.activities (PR 4a removed the 2014 deferral that
    stubbed them as []). Aboleth's Tentacle ships an attack activity with damage."""
    loader = BundledAssetLoader()
    aboleth = loader.get_monster("aboleth")
    assert aboleth is not None
    tentacle = next((a for a in aboleth.actions if a.slug == "tentacle"), None)
    assert tentacle is not None, "aboleth missing Tentacle action"
    assert tentacle.activities, "Tentacle must carry inline activities, not []"
    assert any(act.kind == "attack" for act in tentacle.activities), (
        f"expected an attack activity; got {[act.kind for act in tentacle.activities]}"
    )
