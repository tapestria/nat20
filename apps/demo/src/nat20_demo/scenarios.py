"""The demo's scenario catalog — five curated encounters.

Each :class:`Scenario` is a self-contained opening state (party, encounter,
grid) plus the menu of :class:`ActionOption` templates the UI offers each PC.
Movement is deliberately not an ``ActionOption`` — the grid renders candidate
move cells directly from the live view.

Scenarios are pure data; nothing here talks to the engine. ``fresh_specs``
hands the replay core deep copies so a scenario's module-level ``Scenario``
instance is never mutated by a replay.
"""

from __future__ import annotations

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    WallSegment,
    cell_id,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ActionOption",
    "Scenario",
    "all_scenarios",
    "fresh_specs",
    "get_scenario",
]


class ActionOption(BaseModel):
    """One menu entry offered to a PC on their turn.

    ``intent`` is a template: the renderer fills in ``target_id`` per living
    foe at render time when ``needs_target`` is set.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    intent: PlayerIntent
    needs_target: bool = False


class Scenario(BaseModel):
    """One curated encounter's opening state + action menu."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    tagline: str
    proves: str
    default_seed: int
    party: list[PartyMemberSpec]
    encounter: list[EncounterMemberSpec]
    grid: GridScene
    actions: dict[str, list[ActionOption]] = Field(default_factory=dict)


def _goblin_ambush() -> Scenario:
    return Scenario(
        id="goblin-ambush",
        title="Goblin Ambush",
        tagline="Two heroes, three goblins, a wall to hide behind.",
        proves="Attack rolls, AC, cover folding into AC, grid movement and walls.",
        default_seed=1337,
        party=[
            PartyMemberSpec(
                entity_id="char:brynn",
                name="Brynn",
                initiative=18,
                hp_current=24,
                hp_max=24,
                ac=16,
                attack_bonus=5,
                strength=16,
                dexterity=12,
                constitution=14,
                zone_id=cell_id(1, 4),
                equipment=("longsword",),
                character_level=3,
            ),
            PartyMemberSpec(
                entity_id="char:sera",
                name="Sera",
                initiative=14,
                hp_current=18,
                hp_max=18,
                ac=14,
                attack_bonus=5,
                strength=10,
                dexterity=16,
                constitution=12,
                zone_id=cell_id(0, 6),
                equipment=("shortbow",),
                character_level=3,
            ),
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id=f"mon:gob{i}",
                entity_type="Monster",
                name=f"Goblin {i}",
                initiative=init,
                hp_current=10,
                hp_max=10,
                ac=13,
                dexterity=14,
                monster_template_slug="goblin-warrior",
                xp_value=50,
                zone_id=cell_id(col, row),
            )
            for i, (init, col, row) in enumerate([(12, 8, 3), (9, 9, 5), (7, 8, 7)], start=1)
        ],
        grid=GridScene(
            width=12,
            height=10,
            wall_segments=[WallSegment(x1=6, y1=2, x2=6, y2=5)],
            cover_cells={cell_id(6, 6): "half"},
            blocked_cells=[cell_id(5, 0), cell_id(5, 1)],
        ),
        actions={
            "char:brynn": [
                ActionOption(
                    label="Attack — Longsword",
                    intent=PlayerIntent(intent_type="attack", weapon_id="longsword"),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
            "char:sera": [
                ActionOption(
                    label="Attack — Shortbow",
                    intent=PlayerIntent(intent_type="attack", weapon_id="shortbow"),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
        },
    )


def _burning_hands() -> Scenario:
    return Scenario(
        id="burning-hands",
        title="Burning Hands at the Bottleneck",
        tagline="A wizard catches four giant rats in one fiery cone.",
        proves="AoE save spells: per-target Dex saves, half damage on save, spell slot spend.",
        default_seed=7,
        party=[
            PartyMemberSpec(
                entity_id="char:orin",
                name="Orin",
                initiative=16,
                hp_current=16,
                hp_max=16,
                ac=12,
                attack_bonus=4,
                strength=8,
                dexterity=14,
                constitution=12,
                intelligence=17,
                zone_id=cell_id(1, 2),
                spell_slots={1: 2},
                spells_known=["burning-hands", "magic-missile"],
                character_level=3,
                class_slug="wizard",
            ),
            PartyMemberSpec(
                entity_id="char:garrick",
                name="Garrick",
                initiative=11,
                hp_current=22,
                hp_max=22,
                ac=15,
                attack_bonus=5,
                strength=15,
                dexterity=11,
                constitution=14,
                zone_id=cell_id(1, 3),
                equipment=("spear",),
                character_level=3,
            ),
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id=f"mon:rat{i}",
                entity_type="Monster",
                name=f"Giant Rat {i}",
                initiative=init,
                hp_current=7,
                hp_max=7,
                ac=12,
                dexterity=15,
                monster_template_slug="giant-rat",
                xp_value=25,
                # All four share one zone — the cone-of-fire abstraction hits
                # every living combatant sharing the named target's zone, so
                # the pack is stacked at the corridor mouth to make that
                # broadcast land on all of them.
                zone_id=cell_id(4, 2),
            )
            for i, init in enumerate([13, 10, 8, 6], start=1)
        ],
        grid=GridScene(
            width=10,
            height=6,
            blocked_cells=[cell_id(3, 0), cell_id(3, 1), cell_id(3, 4), cell_id(3, 5)],
        ),
        actions={
            "char:orin": [
                ActionOption(
                    label="Burning Hands",
                    intent=PlayerIntent(
                        intent_type="cast_spell", spell_id="burning-hands", slot_level=1
                    ),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
            "char:garrick": [
                ActionOption(
                    label="Attack — Spear",
                    intent=PlayerIntent(intent_type="attack", weapon_id="spear"),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
        },
    )


def _hold_the_line() -> Scenario:
    return Scenario(
        id="hold-the-line",
        title="Hold the Line",
        tagline="A cleric binds a bandit captain still while a mace fighter holds the door.",
        proves="Conditions/effects: casting a hold, concentration under fire, concentration break.",
        default_seed=2,
        party=[
            PartyMemberSpec(
                entity_id="char:mira",
                name="Mira",
                initiative=15,
                hp_current=20,
                hp_max=20,
                ac=15,
                attack_bonus=4,
                strength=12,
                dexterity=10,
                constitution=13,
                wisdom=16,
                zone_id=cell_id(1, 3),
                spell_slots={1: 3, 2: 2},
                spells_known=["hold-person", "bless", "cure-wounds"],
                character_level=3,
                class_slug="cleric",
            ),
            PartyMemberSpec(
                entity_id="char:doran",
                name="Doran",
                initiative=17,
                hp_current=26,
                hp_max=26,
                ac=17,
                attack_bonus=5,
                strength=16,
                dexterity=10,
                constitution=15,
                zone_id=cell_id(2, 3),
                equipment=("mace",),
                character_level=3,
            ),
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:captain",
                entity_type="Monster",
                name="Bandit Captain",
                initiative=13,
                hp_current=25,
                hp_max=25,
                ac=15,
                attack_bonus=5,
                dexterity=14,
                monster_template_slug="bandit-captain",
                xp_value=450,
                zone_id=cell_id(6, 3),
            ),
            EncounterMemberSpec(
                entity_id="mon:bandit1",
                entity_type="Monster",
                name="Bandit 1",
                initiative=9,
                hp_current=11,
                hp_max=11,
                ac=12,
                dexterity=12,
                monster_template_slug="bandit",
                xp_value=25,
                # Close enough to reach Mira within one turn's move budget —
                # the captain is held, so a bandit landing a hit is what
                # proves concentration under fire.
                zone_id=cell_id(3, 2),
            ),
            EncounterMemberSpec(
                entity_id="mon:bandit2",
                entity_type="Monster",
                name="Bandit 2",
                initiative=6,
                hp_current=11,
                hp_max=11,
                ac=12,
                dexterity=12,
                monster_template_slug="bandit",
                xp_value=25,
                zone_id=cell_id(3, 4),
            ),
        ],
        grid=GridScene(width=8, height=7),
        actions={
            "char:mira": [
                ActionOption(
                    label="Hold Person",
                    intent=PlayerIntent(
                        intent_type="cast_spell", spell_id="hold-person", slot_level=2
                    ),
                    needs_target=True,
                ),
                ActionOption(
                    label="Cure Wounds",
                    intent=PlayerIntent(
                        intent_type="cast_spell", spell_id="cure-wounds", slot_level=1
                    ),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
            "char:doran": [
                ActionOption(
                    label="Attack — Mace",
                    intent=PlayerIntent(intent_type="attack", weapon_id="mace"),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
        },
    )


def _marsh_crossing() -> Scenario:
    return Scenario(
        id="marsh-crossing",
        title="Marsh Crossing",
        tagline="Two archers hold the near bank as zombies shamble through the mud.",
        proves="Difficult terrain halving movement, dash, ranged attacks at range, terrain cover.",
        default_seed=3,
        party=[
            PartyMemberSpec(
                entity_id="char:wren",
                name="Wren",
                initiative=16,
                hp_current=19,
                hp_max=19,
                ac=14,
                attack_bonus=5,
                dexterity=16,
                constitution=12,
                zone_id=cell_id(1, 3),
                equipment=("shortbow",),
                character_level=3,
            ),
            PartyMemberSpec(
                entity_id="char:tam",
                name="Tam",
                initiative=13,
                hp_current=17,
                hp_max=17,
                ac=13,
                attack_bonus=5,
                dexterity=15,
                constitution=11,
                zone_id=cell_id(1, 5),
                equipment=("shortbow",),
                character_level=3,
            ),
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id=f"mon:zom{i}",
                entity_type="Monster",
                name=f"Zombie {i}",
                initiative=init,
                hp_current=22,
                hp_max=22,
                ac=8,
                dexterity=6,
                monster_template_slug="zombie",
                xp_value=50,
                zone_id=cell_id(col, row),
            )
            for i, (init, col, row) in enumerate([(4, 12, 2), (3, 12, 4), (2, 12, 6)], start=1)
        ],
        grid=GridScene(
            width=14,
            height=8,
            difficult_terrain_cells=[
                cell_id(col, row) for col in range(5, 9) for row in range(2, 5)
            ],
            cover_cells={cell_id(6, 1): "half", cell_id(6, 6): "half"},
        ),
        actions={
            "char:wren": [
                ActionOption(
                    label="Attack — Shortbow",
                    intent=PlayerIntent(intent_type="attack", weapon_id="shortbow"),
                    needs_target=True,
                ),
                ActionOption(label="Dash", intent=PlayerIntent(intent_type="dash")),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
            "char:tam": [
                ActionOption(
                    label="Attack — Shortbow",
                    intent=PlayerIntent(intent_type="attack", weapon_id="shortbow"),
                    needs_target=True,
                ),
                ActionOption(label="Dash", intent=PlayerIntent(intent_type="dash")),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
        },
    )


def _last_stand() -> Scenario:
    return Scenario(
        id="last-stand",
        title="Last Stand",
        tagline="A battered fighter drops — can the healer save them before the pack finishes?",
        proves="Healing, death saving throws, a dramatic near-loss and recovery.",
        default_seed=5,
        party=[
            PartyMemberSpec(
                entity_id="char:korrin",
                name="Korrin",
                initiative=12,
                hp_current=9,
                hp_max=28,
                ac=16,
                attack_bonus=5,
                strength=16,
                dexterity=12,
                constitution=15,
                zone_id=cell_id(2, 3),
                equipment=("longsword",),
                character_level=4,
            ),
            PartyMemberSpec(
                entity_id="char:faye",
                name="Faye",
                initiative=15,
                hp_current=18,
                hp_max=18,
                ac=13,
                attack_bonus=3,
                dexterity=13,
                wisdom=16,
                constitution=12,
                zone_id=cell_id(1, 4),
                spell_slots={1: 2},
                spells_known=["healing-word", "cure-wounds"],
                character_level=4,
                class_slug="cleric",
            ),
        ],
        encounter=[
            EncounterMemberSpec(
                entity_id="mon:skel",
                entity_type="Monster",
                name="Skeleton",
                initiative=14,
                hp_current=13,
                hp_max=13,
                ac=13,
                attack_bonus=4,
                dexterity=14,
                monster_template_slug="skeleton",
                xp_value=50,
                zone_id=cell_id(3, 3),
            ),
            EncounterMemberSpec(
                entity_id="mon:wolf1",
                entity_type="Monster",
                name="Wolf 1",
                initiative=10,
                hp_current=11,
                hp_max=11,
                ac=13,
                attack_bonus=4,
                dexterity=15,
                monster_template_slug="wolf",
                xp_value=50,
                zone_id=cell_id(3, 2),
            ),
            EncounterMemberSpec(
                entity_id="mon:wolf2",
                entity_type="Monster",
                name="Wolf 2",
                initiative=8,
                hp_current=11,
                hp_max=11,
                ac=13,
                attack_bonus=4,
                dexterity=15,
                monster_template_slug="wolf",
                xp_value=50,
                zone_id=cell_id(3, 5),
            ),
        ],
        grid=GridScene(width=8, height=8),
        actions={
            "char:korrin": [
                ActionOption(
                    label="Attack — Longsword",
                    intent=PlayerIntent(intent_type="attack", weapon_id="longsword"),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
            "char:faye": [
                ActionOption(
                    label="Healing Word",
                    intent=PlayerIntent(
                        intent_type="cast_spell", spell_id="healing-word", slot_level=1
                    ),
                    needs_target=True,
                ),
                ActionOption(
                    label="Cure Wounds",
                    intent=PlayerIntent(
                        intent_type="cast_spell", spell_id="cure-wounds", slot_level=1
                    ),
                    needs_target=True,
                ),
                ActionOption(label="Dodge", intent=PlayerIntent(intent_type="dodge")),
                ActionOption(label="Pass turn", intent=PlayerIntent(intent_type="pass")),
            ],
        },
    )


_CATALOG: dict[str, Scenario] = {
    s.id: s
    for s in (
        _goblin_ambush(),
        _burning_hands(),
        _hold_the_line(),
        _marsh_crossing(),
        _last_stand(),
    )
}


def get_scenario(scenario_id: str) -> Scenario:
    """Look up a scenario by id. Raises ``KeyError`` on an unknown id."""
    return _CATALOG[scenario_id]


def all_scenarios() -> list[Scenario]:
    """All scenarios, in catalog order."""
    return list(_CATALOG.values())


def fresh_specs(
    s: Scenario,
) -> tuple[list[PartyMemberSpec], list[EncounterMemberSpec], GridScene]:
    """Deep-copied specs for one replay — never share mutable instances."""
    return (
        [p.model_copy(deep=True) for p in s.party],
        [e.model_copy(deep=True) for e in s.encounter],
        s.grid.model_copy(deep=True),
    )
