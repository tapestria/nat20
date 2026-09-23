"""C18 §Monster action economy — Task 8 typed-trait consumers: Pack Tactics,
Sunlight Sensitivity (attack-roll sources), Undead Fortitude (``apply_damage``),
Swarm (``resolve_heal``). Every rule quotes the SRD 5.2 sentence it pins.

Pack Tactics' orchestrator-level ally-adjacency geometry (``_pack_tactics_map``)
and its Incapacitated exclusion are unit-tested against live combat state in
``tests/test_c18_monster_economy_units.py``; this module pins the PURE
resolver behaviour once the sidecar/flag is already on the context.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.monster import MonsterTraitMechanic

from dnd5e_engine.activities.apply import apply_damage
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.heal import resolve_heal
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackRolled, DamageApplied, HealingApplied, SaveRolled
from dnd5e_engine.types.combat import Combatant

_ABILITIES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def _wolf_bite():
    """The real ``wolf`` monster's ``bite`` attack activity — a bundled,
    Weapon-less monster ``AttackActivity`` fixture (Pack Tactics is one of
    ITS own stat-block traits, but the trait tag on the test's own
    ``Combatant`` is what actually drives the resolver)."""
    monster = BundledAssetLoader().get_monster("wolf")
    bite = next(a for a in monster.actions if a.slug == "bite")
    return bite.activities[0]


def _attack_rolled(events: list) -> AttackRolled:
    return next(e for e in events if isinstance(e, AttackRolled))


def test_pack_tactics_adds_trait_advantage_only_with_an_adjacent_ally():
    """SRD 5.2 stat-block trait "Pack Tactics": "Advantage on an attack roll
    against a creature if at least one of the [monster]'s allies is within
    5 feet of the creature ..." The orchestrator-precomputed per-target flag
    (``ctx.pack_tactics_ally_adjacent``) gates the trait; this resolver never
    touches the spatial seam itself."""
    wolf = Combatant(
        entity_id="mon:wolf",
        entity_type="Monster",
        name="Wolf",
        initiative=10,
        hp_current=11,
        hp_max=11,
        trait_mechanics=[MonsterTraitMechanic.PACK_TACTICS],
    )
    hero = Combatant(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=20,
        hp_current=30,
        hp_max=30,
        ac=14,
    )
    activity = _wolf_bite()

    with_ally: list = []
    resolve_activity(
        activity,
        ActivityResolutionContext(
            rng=random.Random(1),
            caster=wolf,
            targets=[hero],
            event_emitter=with_ally.append,
            caster_abilities=_ABILITIES,
            pack_tactics_ally_adjacent={"char:hero": True},
        ),
        weapon=None,
    )
    rolled = _attack_rolled(with_ally)
    assert rolled.advantage == "advantage"
    assert rolled.advantage_sources == ["trait"]

    solo: list = []
    resolve_activity(
        activity,
        ActivityResolutionContext(
            rng=random.Random(1),
            caster=wolf,
            targets=[hero],
            event_emitter=solo.append,
            caster_abilities=_ABILITIES,
            pack_tactics_ally_adjacent={},
        ),
        weapon=None,
    )
    rolled_solo = _attack_rolled(solo)
    assert rolled_solo.advantage == "normal"
    assert rolled_solo.advantage_sources == []


def test_pack_tactics_is_inert_without_the_trait():
    """The ally-adjacent flag alone never grants advantage — only a caster
    that actually carries the ``PACK_TACTICS`` trait mechanic reads it."""
    non_pack_wolf = Combatant(
        entity_id="mon:wolf",
        entity_type="Monster",
        name="Wolf",
        initiative=10,
        hp_current=11,
        hp_max=11,
    )
    hero = Combatant(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=20,
        hp_current=30,
        hp_max=30,
        ac=14,
    )
    events: list = []
    resolve_activity(
        _wolf_bite(),
        ActivityResolutionContext(
            rng=random.Random(1),
            caster=non_pack_wolf,
            targets=[hero],
            event_emitter=events.append,
            caster_abilities=_ABILITIES,
            pack_tactics_ally_adjacent={"char:hero": True},
        ),
        weapon=None,
    )
    assert _attack_rolled(events).advantage == "normal"


def test_sunlight_sensitivity_adds_trait_disadvantage_only_in_sunlight():
    """SRD 5.2 stat-block trait "Sunlight Sensitivity": "the [monster] has
    Disadvantage on attack rolls ... while [it] ... is in direct sunlight."
    The scene-wide flag (``ctx.attacker_in_sunlight``) gates the trait."""
    sensitive = Combatant(
        entity_id="mon:kobold",
        entity_type="Monster",
        name="Kobold",
        initiative=10,
        hp_current=5,
        hp_max=5,
        trait_mechanics=[MonsterTraitMechanic.SUNLIGHT_SENSITIVITY],
    )
    hero = Combatant(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=20,
        hp_current=30,
        hp_max=30,
        ac=14,
    )
    activity = _wolf_bite()

    sunlit: list = []
    resolve_activity(
        activity,
        ActivityResolutionContext(
            rng=random.Random(1),
            caster=sensitive,
            targets=[hero],
            event_emitter=sunlit.append,
            caster_abilities=_ABILITIES,
            attacker_in_sunlight=True,
        ),
        weapon=None,
    )
    rolled = _attack_rolled(sunlit)
    assert rolled.advantage == "disadvantage"
    assert rolled.disadvantage_sources == ["trait"]

    shaded: list = []
    resolve_activity(
        activity,
        ActivityResolutionContext(
            rng=random.Random(1),
            caster=sensitive,
            targets=[hero],
            event_emitter=shaded.append,
            caster_abilities=_ABILITIES,
            attacker_in_sunlight=False,
        ),
        weapon=None,
    )
    rolled_shaded = _attack_rolled(shaded)
    assert rolled_shaded.advantage == "normal"
    assert rolled_shaded.disadvantage_sources == []


def _zombie(*, hp_current: int = 3) -> Combatant:
    return Combatant(
        entity_id="mon:zombie",
        entity_type="Monster",
        name="Zombie",
        initiative=1,
        hp_current=hp_current,
        hp_max=22,
        constitution=16,
        trait_mechanics=[MonsterTraitMechanic.UNDEAD_FORTITUDE],
    )


def _damage_ctx(target: Combatant, events: list, *, seed: int) -> ActivityResolutionContext:
    caster = Combatant(
        entity_id="char:hero",
        entity_type="Character",
        name="Hero",
        initiative=20,
        hp_current=30,
        hp_max=30,
    )
    return ActivityResolutionContext(
        rng=random.Random(seed),
        caster=caster,
        targets=[target],
        event_emitter=events.append,
        caster_abilities=_ABILITIES,
    )


def test_undead_fortitude_con_save_keeps_the_zombie_at_one_hp():
    """SRD 5.2 stat-block trait "Undead Fortitude": "If damage reduces the
    [monster] to 0 Hit Points, it makes a Constitution saving throw (DC 5
    plus the damage taken) unless the damage is Radiant or from a Critical
    Hit. On a successful save, the [monster] drops to 1 Hit Point instead."
    Seed 3's first d20 draw (8) + CON 16's +3 mod = 11, clearing DC 10
    (5 + 5 damage)."""
    target = _zombie(hp_current=3)
    events: list = []
    ctx = _damage_ctx(target, events, seed=3)

    total = apply_damage(target, {"bludgeoning": 5}, ctx)

    assert total == 5
    assert target.hp_current == 1
    saves = [e for e in events if isinstance(e, SaveRolled)]
    assert len(saves) == 1
    save = saves[0]
    assert save.target_id == "mon:zombie"
    assert save.ability == "con"
    assert save.dc == 10
    assert save.succeeded is True
    damages = [e for e in events if isinstance(e, DamageApplied)]
    assert len(damages) == 1
    assert damages[0].amount == 5
    assert damages[0].is_overkill is False


def test_undead_fortitude_does_not_trigger_on_radiant_or_crit():
    """Radiant damage and a Critical Hit both bypass the trait — no save is
    rolled (zero extra RNG draws) and the zombie drops the rest of the way."""
    radiant_target = _zombie(hp_current=3)
    radiant_events: list = []
    apply_damage(
        radiant_target, {"radiant": 5}, _damage_ctx(radiant_target, radiant_events, seed=3)
    )
    assert not [e for e in radiant_events if isinstance(e, SaveRolled)]
    assert radiant_target.hp_current == 3  # apply_damage never mutates hp on its own
    damage_event = next(e for e in radiant_events if isinstance(e, DamageApplied))
    assert damage_event.amount == 5
    assert damage_event.is_overkill is True

    crit_target = _zombie(hp_current=3)
    crit_events: list = []
    apply_damage(
        crit_target,
        {"bludgeoning": 5},
        _damage_ctx(crit_target, crit_events, seed=3),
        is_crit=True,
    )
    assert not [e for e in crit_events if isinstance(e, SaveRolled)]
    crit_damage = next(e for e in crit_events if isinstance(e, DamageApplied))
    assert crit_damage.amount == 5
    assert crit_damage.is_overkill is True


def test_swarm_never_regains_hp():
    """SRD 5.2 stat-block trait "Swarm": "The swarm can't regain Hit Points
    or gain Temporary Hit Points" (e.g. swarm-of-rats.json). ``resolve_heal``
    skips a Swarm target entirely — no ``HealingApplied``."""
    from dnd5e_srd_data.schema.common import DamagePartBlock, HealActivity

    swarm = Combatant(
        entity_id="mon:swarm",
        entity_type="Monster",
        name="Swarm of Rats",
        initiative=1,
        hp_current=5,
        hp_max=24,
        trait_mechanics=[MonsterTraitMechanic.SWARM],
    )
    activity = HealActivity(
        healing=DamagePartBlock(number=2, denomination=4, types=["healing"]),
    )
    events: list = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=swarm,
        targets=[swarm],
        event_emitter=events.append,
        caster_abilities=_ABILITIES,
    )
    resolve_heal(activity, ctx)
    assert not [e for e in events if isinstance(e, (HealingApplied,))]
