"""Combat utility helpers — initiative sorting, death save state, health descriptors.

Zero DB imports. All functions are pure or use only dnd5e_engine.rules.* imports.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any

from dnd5e_engine.rules.combat import initiative_roll
from dnd5e_engine.rules.dice import ability_modifier
from dnd5e_engine.types.combat import CombatNPC

# ---------------------------------------------------------------------------
# JSON list parser (shared with template stat extraction)
# ---------------------------------------------------------------------------


def _parse_json_list(value: Any) -> list[str]:
    """Parse a value that may be a native list or a JSON string into list[str]."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (ValueError, TypeError):
            return []
    return []


# ---------------------------------------------------------------------------
# Template stat extraction (MonsterTemplate dict → flat combat-stats dict)
# ---------------------------------------------------------------------------


def extract_template_combat_stats(template: dict[str, Any]) -> dict[str, Any]:
    """Project a MonsterTemplate node's properties into a flat combat-stats dict.

    Pure: no DB, no async. Used by both the Monster spawn loop and the NPC
    materialization path in session.combat. Returns keys: ac, hp, xp_value,
    challenge_rating, attack_bonus, damage_dice, damage_type, has_ranged_attack,
    dexterity, strength, constitution, wisdom, intelligence, charisma,
    damage_resistances, damage_immunities. Defaults are SRD-minimum values
    when a field is absent.
    """
    # Deserialize ability_scores if stored as JSON string
    ability_scores = template.get("ability_scores", {})
    if isinstance(ability_scores, str):
        try:
            ability_scores = json.loads(ability_scores)
        except (ValueError, TypeError):
            ability_scores = {}

    dex_score = ability_scores.get("dexterity", ability_scores.get("dex", 10))
    str_score = ability_scores.get("strength", ability_scores.get("str", 10))

    # Deserialize actions
    actions = template.get("actions", [])
    if isinstance(actions, str):
        try:
            actions = json.loads(actions)
        except (ValueError, TypeError):
            actions = []

    # Default combat stats
    ac = int(template.get("armor_class", 10))
    hp = int(template.get("hit_points", 1))
    xp_value = int(template.get("xp", 0))
    cr = float(template.get("challenge_rating", 0.0))

    # Infer attack_bonus from CR and STR modifier
    str_mod = ability_modifier(str_score)
    prof_bonus = max(2, int(cr // 4) + 2)  # simple CR-based proficiency
    attack_bonus = str_mod + prof_bonus

    damage_dice = "1d6"
    damage_type = "bludgeoning"
    has_ranged_attack = False

    # Try to extract from first attack action
    for action in actions:
        if not isinstance(action, dict):
            continue
        damage_info = action.get("damage", [])
        if isinstance(damage_info, str):
            try:
                damage_info = json.loads(damage_info)
            except (ValueError, TypeError):
                damage_info = []
        if isinstance(damage_info, list) and damage_info:
            first_dmg = damage_info[0] if isinstance(damage_info[0], dict) else {}
            dice_str = first_dmg.get("damage_dice", "1d6")
            dtype = first_dmg.get("damage_type", {})
            if isinstance(dtype, dict):
                dtype = dtype.get("name", "bludgeoning")
            if dice_str:
                damage_dice = dice_str
            if dtype:
                damage_type = str(dtype).lower()

        # Prefer the action's stated attack_bonus when present (SRD-seeded
        # monsters carry it on each action — see srd_seeder.py:1248). Falling
        # back to the STR-mod + proficiency formula above misses dex-finesse
        # / nimble attackers (e.g. the SRD Goblin's +4 scimitar resolves to
        # +1 under the formula because STR=8). Only override on a sane int.
        action_atk = action.get("attack_bonus")
        if isinstance(action_atk, int):
            attack_bonus = action_atk

        # Check for ranged attack
        attack_type = action.get("attack_type", "")
        if "ranged" in str(attack_type).lower():
            has_ranged_attack = True
        break  # Only use first action

    return {
        "ac": ac,
        "hp": hp,
        "xp_value": xp_value,
        "challenge_rating": cr,
        "attack_bonus": attack_bonus,
        "damage_dice": damage_dice,
        "damage_type": damage_type,
        "has_ranged_attack": has_ranged_attack,
        "dexterity": dex_score,
        "strength": ability_scores.get("strength", ability_scores.get("str", 10)),
        "constitution": ability_scores.get("constitution", ability_scores.get("con", 10)),
        "wisdom": ability_scores.get("wisdom", ability_scores.get("wis", 10)),
        "intelligence": ability_scores.get("intelligence", ability_scores.get("int", 10)),
        "charisma": ability_scores.get("charisma", ability_scores.get("cha", 10)),
        "damage_resistances": _parse_json_list(template.get("damage_resistances", [])),
        "damage_immunities": _parse_json_list(template.get("damage_immunities", [])),
    }


# ---------------------------------------------------------------------------
# Health descriptor
# ---------------------------------------------------------------------------


def health_descriptor(hp_current: int, hp_max: int) -> str:
    """Map HP ratio to a human-readable health label.

    Thresholds:
    - >= 0.5 : Healthy
    - >= 0.25: Bloodied
    - > 0    : Near death
    - == 0   : Dead (also handles max_hp == 0)
    """
    if hp_max <= 0 or hp_current <= 0:
        return "Dead"
    ratio = hp_current / hp_max
    if ratio >= 0.5:
        return "Healthy"
    if ratio >= 0.25:
        return "Bloodied"
    return "Near death"


# ---------------------------------------------------------------------------
# Initiative sorting
# ---------------------------------------------------------------------------


def roll_and_sort_initiative(combatants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll initiative for every combatant and sort descending.

    Each input dict must have: entity_id, name, dexterity, entity_type.
    Returns a new list of dicts with added fields: `initiative` (int), `dex_modifier` (int).

    Tie-breaking order: initiative desc -> dex_modifier desc -> random float (stable per call).
    """
    result: list[dict[str, Any]] = []
    for combatant in combatants:
        dex = combatant.get("dexterity", 10)
        dex_mod = ability_modifier(dex)
        roll_result = initiative_roll(dex)
        entry = dict(combatant)
        entry["initiative"] = roll_result.total
        entry["dex_modifier"] = dex_mod
        entry["_tiebreak"] = random.random()
        result.append(entry)

    result.sort(key=lambda e: (e["initiative"], e["dex_modifier"], e["_tiebreak"]), reverse=True)

    # Remove internal tiebreak field before returning
    for entry in result:
        entry.pop("_tiebreak", None)

    return result


# ---------------------------------------------------------------------------
# Death save state machine
# ---------------------------------------------------------------------------


@dataclass
class DeathSaveState:
    """Mutable state machine for D&D 5e death saving throws.

    Designed for Redis serialization via to_dict / from_dict.
    """

    successes: int = 0
    failures: int = 0
    is_stable: bool = False

    # ------------------------------------------------------------------
    # Core state transitions
    # ------------------------------------------------------------------

    def apply_save(self, success: bool, is_critical: bool) -> str:
        """Apply a death saving throw result.

        Returns one of: "critical_success" | "stabilized" | "dead" | "ongoing".

        Rules:
        - Nat 20 (success=True, is_critical=True): regain 1 HP -> "critical_success"
        - Nat 1  (success=False, is_critical=True): 2 failures
        - Normal success: 1 success; 3 successes -> "stabilized"
        - Normal failure: 1 failure; 3 failures  -> "dead"
        """
        # Nat 20 takes priority — regain 1 HP, no counter update needed
        if success and is_critical:
            return "critical_success"

        if success:
            self.successes += 1
        elif is_critical:
            # Nat 1 counts as 2 failures
            self.failures += 2
        else:
            self.failures += 1

        return self._check_outcome()

    def apply_damage_while_unconscious(self, is_melee_within_5ft: bool) -> str:
        """Apply death save failures from damage while unconscious.

        D&D 5e RAW: taking any damage while at 0 HP is a death save failure.
        Melee attack within 5 ft = auto-crit = 2 failures. Otherwise 1 failure.

        Returns "dead" if 3+ failures reached, else "ongoing".
        """
        self.failures += 2 if is_melee_within_5ft else 1
        return self._check_outcome()

    def reset(self) -> None:
        """Reset all counters (called when character regains HP via nat 20)."""
        self.successes = 0
        self.failures = 0
        self.is_stable = False

    # ------------------------------------------------------------------
    # Serialization (for Redis)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "successes": self.successes,
            "failures": self.failures,
            "is_stable": self.is_stable,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeathSaveState:
        return cls(
            successes=d.get("successes", 0),
            failures=d.get("failures", 0),
            is_stable=d.get("is_stable", False),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_outcome(self) -> str:
        if self.failures >= 3:
            return "dead"
        if self.successes >= 3:
            self.is_stable = True
            return "stabilized"
        return "ongoing"


def build_combatant_from_npc(
    npc_props: dict[str, Any],
    template_props: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project an NPC + its STATTED_AS MonsterTemplate into a Combatant-shaped dict.

    Pure (no DB, no async). Caller is responsible for fetching ``npc_props``,
    ``template_props``, and the parsed ``combat_overrides`` JSON from the
    graph. Output is consumed by ``roll_and_sort_initiative`` followed by
    ``Combatant`` construction by the host orchestrator.

    Layering (per epic npc-combat-readiness spec):
    - ``hp_max`` = ``overrides.hp_max_override`` when not None, else ``template.hit_points``.
    - ``hp_current`` = ``hp_max`` (NPCs always start combat at full HP — combat
      HP is ephemeral per piece 1's removal of persisted ``hp_current``).
    - ``behavior_profile`` = ``overrides.behavior_profile`` when present, else
      ``"DEFENSIVE"`` (NPCBase / NPCCombatOverrides default).
    - ``ac``, ``attack_bonus``, ``damage_dice``, ``damage_type``, ``has_ranged_attack``,
      ``dexterity`` and the rest of the ability_scores: from the template via
      ``extract_template_combat_stats``.

    Args:
        npc_props: NPC node properties — must carry ``id`` and ``name``.
            Other NPC properties (``description``, ``backstory``, etc.) are
            ignored at the combat layer.
        template_props: MonsterTemplate node properties as returned by
            ``get_node_by_id(reader, "MonsterTemplate", ...)``. Same shape
            ``extract_template_combat_stats`` consumes.
        overrides: Parsed ``combat_overrides`` JSON dict, e.g.
            ``{"hp_max_override": 42, "behavior_profile": "DEFENSIVE"}``. May
            be ``None`` (legacy graph state) — defaults apply.

    Returns:
        Combatant-shaped dict with keys: entity_id, entity_type ("NPC"),
        name, hp_current, hp_max, ac, attack_bonus, damage_dice, damage_type,
        has_ranged_attack, dexterity, strength, constitution, wisdom,
        intelligence, charisma, behavior_profile. Does NOT include ``initiative``
        — caller must run ``roll_and_sort_initiative`` afterward.
    """
    stats = extract_template_combat_stats(template_props)

    # hp_max layering: explicit override wins; otherwise template hit_points.
    hp_max_override = (overrides or {}).get("hp_max_override")
    hp_max = int(hp_max_override) if hp_max_override is not None else int(stats.get("hp", 1))

    # behavior_profile layering: explicit override wins; otherwise default.
    behavior_profile = (overrides or {}).get("behavior_profile") or "DEFENSIVE"

    return {
        "entity_id": str(npc_props["id"]),
        "entity_type": "NPC",
        "name": str(npc_props.get("name", "")),
        "hp_current": hp_max,
        "hp_max": hp_max,
        "ac": int(stats.get("ac", 10)),
        "attack_bonus": int(stats.get("attack_bonus", 0)),
        "damage_dice": str(stats.get("damage_dice", "1d4")),
        "damage_type": str(stats.get("damage_type", "bludgeoning")),
        "has_ranged_attack": bool(stats.get("has_ranged_attack", False)),
        "dexterity": int(stats.get("dexterity", 10)),
        "strength": int(stats.get("strength", 10)),
        "constitution": int(stats.get("constitution", 10)),
        "wisdom": int(stats.get("wisdom", 10)),
        "intelligence": int(stats.get("intelligence", 10)),
        "charisma": int(stats.get("charisma", 10)),
        "behavior_profile": str(behavior_profile),
    }


def build_combat_npc_from_template(
    npc_props: dict[str, Any],
    template_props: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> CombatNPC:
    """Pure projection from (NPC node props + MonsterTemplate node props +
    optional combat_overrides) → CombatNPC sidecar record. Parallel to
    build_combatant_from_npc but populates the richer save/resistance/
    ability-score fields. hp_max_override in overrides wins over template
    hit_points; behavior_profile in overrides wins over the seeded
    template behavior."""
    stats = extract_template_combat_stats(template_props)
    overrides = overrides or {}
    # Use `is not None` (not `or`) so an explicit zero override survives —
    # `0 or stats["hp"]` would silently fall back to template HP and let the
    # sidecar disagree with build_combatant_from_npc's initiative entry
    # (codex review r2 P3).
    hp_max_override = overrides.get("hp_max_override")
    hp_max = int(hp_max_override) if hp_max_override is not None else int(stats["hp"])
    return CombatNPC(
        npc_id=npc_props["id"],
        template_id=template_props["id"],
        name=npc_props.get("name", "NPC"),
        hp_current=hp_max,
        hp_max=hp_max,
        ac=stats["ac"],
        attack_bonus=stats["attack_bonus"],
        damage_dice=stats["damage_dice"],
        damage_type=stats["damage_type"],
        has_ranged_attack=stats["has_ranged_attack"],
        dexterity=stats["dexterity"],
        strength=stats["strength"],
        constitution=stats["constitution"],
        wisdom=stats["wisdom"],
        intelligence=stats["intelligence"],
        charisma=stats["charisma"],
        behavior_profile=overrides.get("behavior_profile")
        or stats.get("behavior_profile", "DEFENSIVE"),
        damage_resistances=list(stats.get("damage_resistances") or []),
        damage_immunities=list(stats.get("damage_immunities") or []),
        is_alive=True,
    )


__all__ = [
    "DeathSaveState",
    "build_combat_npc_from_template",
    "build_combatant_from_npc",
    "extract_template_combat_stats",
    "health_descriptor",
    "roll_and_sort_initiative",
]
