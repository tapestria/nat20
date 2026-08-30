"""Condition schema — the 15 SRD 5.2 rules-glossary conditions as typed data.

Foundry ships condition text only as journal prose (``content24/appendices/
rules-glossary.yml``, ``system.type: condition``) plus Active-Effect status
links in ``config.mjs`` — there is no structured mechanic upstream. The
``effects`` list below is therefore authored in the translator
(``tools/translators/conditions.py``) from the SRD 5.2 sentences, one typed
row per sentence, and this module only defines the closed vocabulary.

The engine's ``dnd5e_engine.rules.conditions`` registry stays authoritative
for enforcement (campaign design D3); this category mirrors it as data so a
host can render, extend or audit conditions without reading Python.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from dnd5e_srd_data.schema.common import Provenance, ReviewState


class ConditionEffectKind(StrEnum):
    """One mechanical clause of a condition (SRD 5.2 rules glossary)."""

    # Attack rolls
    ADVANTAGE_ATTACKS_AGAINST = "advantage_attacks_against"
    DISADVANTAGE_ATTACKS_AGAINST = "disadvantage_attacks_against"
    ADVANTAGE_OWN_ATTACKS = "advantage_own_attacks"
    DISADVANTAGE_OWN_ATTACKS = "disadvantage_own_attacks"
    DISADVANTAGE_ATTACKS_EXCEPT_GRAPPLER = "disadvantage_attacks_except_grappler"
    AUTO_CRIT_WITHIN_5FT = "auto_crit_within_5ft"
    # Saving throws
    AUTO_FAIL_SAVE = "auto_fail_save"  # carries ``abilities``
    DISADVANTAGE_SAVE = "disadvantage_save"  # carries ``abilities``
    # Ability checks / initiative
    DISADVANTAGE_ABILITY_CHECKS = "disadvantage_ability_checks"
    AUTO_FAIL_SIGHT_CHECKS = "auto_fail_sight_checks"
    AUTO_FAIL_HEARING_CHECKS = "auto_fail_hearing_checks"
    CHARMER_SOCIAL_ADVANTAGE = "charmer_social_advantage"
    ADVANTAGE_INITIATIVE = "advantage_initiative"
    DISADVANTAGE_INITIATIVE = "disadvantage_initiative"
    # Action economy / concentration
    CANNOT_TAKE_ACTIONS = "cannot_take_actions"
    BREAKS_CONCENTRATION = "breaks_concentration"
    CANNOT_SPEAK = "cannot_speak"
    CANT_ATTACK_CHARMER = "cant_attack_charmer"
    DROPS_HELD_ITEMS = "drops_held_items"
    # Movement
    SPEED_ZERO = "speed_zero"
    CANT_MOVE_TOWARD_FEAR_SOURCE = "cant_move_toward_fear_source"
    RESTRICTED_MOVEMENT_CRAWL = "restricted_movement_crawl"
    MOVABLE_BY_GRAPPLER = "movable_by_grappler"
    # Damage / immunity / visibility
    RESIST_ALL_DAMAGE = "resist_all_damage"
    IMMUNE_TO_CONDITION = "immune_to_condition"  # ``qualifier`` names the condition slug
    UNSEEN = "unseen"
    # Exhaustion (level-scaled; ``value`` is the per-level multiplier / the level)
    D20_TEST_PENALTY_PER_LEVEL = "d20_test_penalty_per_level"
    SPEED_PENALTY_PER_LEVEL = "speed_penalty_per_level"
    DEATH_AT_LEVEL = "death_at_level"


class ConditionEffect(BaseModel, frozen=True):
    """One typed clause. ``abilities`` (lower-case codes) scopes the save
    kinds; ``value`` carries a number the kind needs (feet, level, per-level
    multiplier); ``qualifier`` is the SRD clause that scopes when the effect
    applies (rendering / host-side reasoning only)."""

    kind: ConditionEffectKind
    abilities: list[str] = Field(default_factory=list)
    value: int | None = None
    qualifier: str = ""


class Condition(BaseModel):
    slug: str
    name: str
    description: str
    effects: list[ConditionEffect] = Field(default_factory=list)
    implies: list[str] = Field(default_factory=list)
    """Sibling condition slugs this condition includes (SRD: "You have the
    Incapacitated condition")."""
    provenance: Provenance
    review: ReviewState
