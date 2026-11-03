# Combat sides, a host-chosen foe target, and knocking out a creature — design spec

**Date:** 2026-11-02
**Status:** proposed design, pre-implementation
**Target release:** `dnd5e-engine` 0.8.0 (lockstep with `dnd5e-srd-data` and
`nat20-bridge` 0.8.0); every change below is additive to the 0.7.0 API.
**Location rationale:** lives in `docs/dev/` alongside the other developer design
notes, outside the MkDocs nav like the demo web app design.

## Purpose

Three gaps a host meets as soon as its fights stop being "the party versus the
monsters":

1. **Sides.** A host may want creatures that are not player characters to fight
   *with* the party — an escort, a hired sword, a rescued prisoner — statted from a
   monster template and driven by the engine's own AI or by the host, and dying as
   any monster dies. Today the encounter list is hostile by construction.
2. **A host-chosen foe target.** On a monster's turn the engine always attacks the
   lowest-HP enemy. A host that decides whom a foe strikes — by a rule of its own,
   by a narrator's judgment, by a player's taunt — needs to hand that choice to the
   engine, and the engine must refuse an illegal choice rather than quietly
   substitute its own.
3. **Knocking out a creature.** SRD 5.2 lets the attacker of a melee attack that
   would drop a creature to 0 Hit Points leave it at 1 Hit Point and Unconscious
   instead. The engine has no such choice: every non-character at 0 Hit Points
   dies.

The design keeps the engine host-agnostic: a side is a side, a target is an id,
a knock-out is a flag on the intent. Nothing here knows what a host does with a
knocked-out creature or an ally afterwards.

## SRD ground truth

- **Knocking Out a Creature** (SRD 5.2, Rules Glossary; in the Foundry SRD source
  packs, `content24/chapter-1/damage-and-healing.yml`): *"When you would reduce a
  creature to 0 Hit Points with a melee attack, you can instead reduce the creature
  to 1 Hit Point. The creature then has the Unconscious condition and starts a
  Short Rest. The creature remains Unconscious until it regains any Hit Points or
  until someone uses an action to administer first aid to it, which requires a
  successful DC 10 Wisdom (Medicine) check."*
- **Unconscious** (SRD 5.2 conditions): Incapacitated, Prone, Speed 0, attack rolls
  against the creature have Advantage, and a hit from within 5 feet is a Critical
  Hit. "When this condition ends, you remain Prone." The engine already enforces
  all of these for the Unconscious a dying character gains
  (`rules/conditions.py:476-487`).
- **Monster death** (SRD 5.2): a monster dies the instant it drops to 0 Hit
  Points. The engine applies this to every non-character
  (`orchestrator.py:5237-5248`).
- **Allies** (SRD 5.2 Summon Dragon, already modelled): "The creature is an ally
  to you and your allies." The engine's notion of a side — `_side_of`,
  `_allied_ids`, `_is_enemy` (`orchestrator.py:1064-1095`) — is what every ally
  rule reads (Help, Pack Tactics, Sneak Attack's adjacent ally, area aim).

## Current behavior

All paths below are in `packages/dnd5e-engine/src/dnd5e_engine/`.

### Sides

- `start_combat` seats two sets: `party_ids` from the `PartyMemberSpec` list and
  `encounter_ids` from the `EncounterMemberSpec` list (`orchestrator.py:7914-7915`;
  `_LiveCombat` at `orchestrator.py:3159-3160`). `EncounterMemberSpec`
  (`specs.py:231`) is documented as "One hostile (monster or NPC) entering combat"
  and carries `entity_type: Literal["Monster", "NPC"]`.
- Allegiance is derived from those sets: `_side_of` returns the set an id belongs
  to, a summon inheriting its owner's (`orchestrator.py:1064-1077`); `_is_enemy`
  is "different side" (`:1090-1095`). The monster target pool is every living
  enemy minus a charmer (`_select_monster_targets`, `:2615-2631`).
- Some readers treat `party_ids` as "the characters" rather than "the party's
  side": the 0-HP fold sends a `party_ids` member down the character path
  (Unconscious and death saves) and everyone else to a `Death`
  (`:5237-5248`); a 0-HP hydrated `party_ids` member is folded Unconscious at
  start (`:7981-7982`); `_derive_ended_reason` reads both sets (`:13360-13382`);
  `_project_outcome` reports residual HP for `party_ids` and divides XP among
  surviving `party_ids` (`:13401-13416`); legendary actions and resistances are
  reserved to `encounter_ids` (`:2924`, `:3582`).
- `advance_monster_turn` refuses a `Character` actor and otherwise runs the AI
  for whoever is current (`:13108-13113`); `submit_player_intent` accepts any
  actor in the initiative order on its own turn (`_validate_intent_preconditions`,
  `:9093-9133`) — that is how a summon is commanded today.
- `LiveCombatView` exposes `party_ids` and `encounter_ids` (`views.py:89-90`).

### Foe targeting

- `advance_monster_turn(handle, *, legendary=False, actor_id=None)`
  (`orchestrator.py:13051`). On a normal turn it builds `enemies =
  _select_monster_targets(live, current)` and takes `chosen_target =
  _lowest_hp_target(enemies)` — lowest current HP, first in initiative order on a
  tie (`:13154-13158`, `:2634-2637`). `chosen_target` then drives the closing
  walk, `IntentSubmitted.target_id`, a stat-block cast and the attack parts
  (`:13184-13350`). An action that places an area is aimed independently, where it
  affects the most enemies minus allies (`_resolve_monster_parts`, `:2446-2475`).
- A legendary action takes the same lowest-HP pick (`_take_legendary_action`,
  `:3106`).
- A summon's uncommanded turn never reaches targeting: it Dodges (`:13124-13126`).
- Every seam refusal is a typed `IntentRejectedError(reason, detail)` with a
  closed `RejectionReason` literal (`:426-445`); the bridge maps it to a 409
  (`packages/nat20-bridge/src/nat20_bridge/routes_combat.py:239-247`).

### Dropping to 0 Hit Points

- `_emit_apply_damage` folds every `DamageApplied` (`orchestrator.py:5115`): temp
  HP, the new tracked HP, Undead Fortitude's "1 Hit Point instead"
  (`:5143-5147`), concentration, then at `new_hp <= 0`: a summon leaves
  (`:5232-5236`), a `party_ids` member takes the character path
  (`_apply_zero_hp_to_character`, `:5251-5311`: massive damage, else
  `Unconscious` + `ConditionApplied("unconscious")` and death saves on later
  damage), anyone else gets `Death(reason="damage")` (`:5237-5248`).
- `DamageApplied` carries `target_id`, `amount`, `damage_type`, `is_overkill`,
  `source_id`, `is_crit` (`events.py:316-329`); it is emitted by
  `activities/apply.py:185-193` from `apply_damage(target, rolled_by_type, ctx,
  *, magical, source_id, is_crit)` (`apply.py:85`), which `resolve_attack` calls
  on a hit (`activities/attack.py:1095-1102`). The resolver knows whether the
  swing is a melee attack: `activity.attack.type.value` is `"melee"` or
  `"ranged"` (`attack.py:731`), and `_attack_is_effectively_ranged(weapon,
  distance_ft)` (`attack.py:757`) tells a thrown melee weapon beyond reach from an
  ordinary swing.
- Healing wakes only the 0 → positive transition, clearing death saves and
  Unconscious and leaving the creature Prone (`_emit_apply_healing`,
  `:5314-5357`).
- The combat ends with `victory` when every `encounter_ids` member is dead,
  `defeat_tpk` when every `party_ids` member is, `flee` when every living foe has
  fled, else `forced` (`:13360-13382`). `CombatOutcome` reports `deaths`
  (`DeathRecord`, `outcome.py:33-40`), residual HP and XP (`outcome.py:60-80`).

## Design

### 1. Sides

**Shape.** One new field on `EncounterMemberSpec`:

```python
# specs.py
Side = Literal["party", "encounter"]

class EncounterMemberSpec(BaseModel):
    ...
    # The side this creature fights on. ``"encounter"`` (the default) is a
    # hostile; ``"party"`` fights with the characters: every ally rule and the
    # monster AI read it as one of theirs, and it dies at 0 Hit Points as any
    # monster does.
    side: Side = "encounter"
```

`Side` joins `specs.__all__` next to `LightLevel`; it is not a top-level export
(a host writes the literal).

**Semantics.**

- `start_combat` seats a `side="party"` encounter member in `party_ids` and
  everyone else in `encounter_ids` (`orchestrator.py:7914-7915`). The initiative
  roll order (party specs, then encounter specs in list order) is unchanged, so
  every existing seeded combat draws the same dice. The existing "encounter must
  be non-empty" check becomes "at least one encounter member fights on the
  encounter side" (`ValueError`, same message family as `:7847-7850`); `party`
  must still be non-empty.
- The two sets stay the sides. `_side_of`, `_allied_ids`, `_is_enemy`, the help
  grants, Pack Tactics, Sneak Attack's adjacent ally, the monster area aim and the
  opportunity-attack reactor filter (`:12812-12820`) all follow without change.
  A foe's target pool is "every living enemy", so a party-side ally is a legal
  foe target and, being a monster, is the lowest-HP pick when its HP is lowest.
- An ally's turn is driven exactly like a foe's: `advance_monster_turn` runs the
  AI for it, and its target pool is the encounter side (the `_is_enemy` filter
  does this already). A host that wants the ally to do nothing, or to act on its
  own decision, submits its intents through `submit_player_intent(handle,
  ally_id, intent)` as it commands a summon — `pass`, `move`, `attack` with
  `stat_block_action_id`. The flee gate applies to an ally with its
  `behavior_profile` as it does to a foe.
- **Readers that mean "a character" switch to `entity_type == "Character"`**, the
  test every other character-only rule already uses (`_maybe_roll_death_save`,
  `:5536`; `_target_kind_for`, `:5579`):
  - the 0-HP fold (`:5237`): a `Character` takes the character path; every other
    creature, allies included, gets `Death(reason="damage")` — an ally dies as a
    foe does, with a `DeathRecord` whose `target_kind` is `"npc"` or
    `"monster"` and whose `killer_id` is the current actor;
  - the 0-HP-at-start fold (`:7981`): only a `Character` is seated Unconscious;
  - XP (`:13416`): divided among surviving `Character`s only. The `xp_value` of a
    dead ally is never awarded (it is not in `encounter_ids`).
  - Residual HP (`:13401`) keeps reading `party_ids`: an ally's HP at combat end
    is the host's to persist, like a character's.
- `_derive_ended_reason` keeps reading the sides: `victory` once every
  encounter-side creature is out of the fight; `defeat_tpk` once every party-side
  creature is — a standing ally keeps the fight open, which is what "side" means.
  "Out of the fight" is dead or knocked out (see §3).
- Legendary actions and Legendary Resistance stay encounter-only (`:2924`,
  `:3582`): a legendary ally is a recorded gap (BACKLOG.md), not a feature.
- `LiveCombatView` needs no new field: `party_ids` lists the ally, and
  `Combatant.entity_type` tells it from a character. `Side` is a start-time
  input; the engine never re-sides a creature.

**Not in scope.** A third side, or a creature hostile to everyone. The two sets
are the engine's only allegiance model, and nothing a host has asked for needs
more; `Side` is a closed literal so a third value is an additive change later.

### 2. A host-chosen foe target

**Shape.** One new keyword on `advance_monster_turn`:

```python
async def advance_monster_turn(
    handle: CombatHandle,
    *,
    legendary: bool = False,
    actor_id: str | None = None,
    target_id: str | None = None,
) -> None:
```

`target_id` names the creature the acting monster attacks this turn, or targets
with its stat-block cast. `None` (the default) keeps the lowest-HP pick.

**Legality.** A `target_id` is legal iff it is in the actor's own target pool,
`_select_monster_targets(live, current)` (`orchestrator.py:2615-2631`): in the
initiative order, an enemy of the actor (a party-side creature or a summon that
side owns, for a foe), alive with more than 0 Hit Points, not knocked out (§3),
and not the actor's charmer. There is no separate reach or sight test: the pool
has none today, and the AI walks toward its target and Dashes when it must
(`:13184-13250`); a target it cannot reach this turn costs the monster its
attack, exactly as the lowest-HP target does now, and the turn records a `pass`
or a `dash`. A `target_id` the pool does not contain raises

```python
IntentRejectedError("target_invalid", f"target_id={target_id!r} is not a legal target for {actor!r}")
```

**No fallback, no side effects on refusal.** The check runs before
`_run_monster_turn_start` (`:13118`), so a refused call rolls no recharge, draws
no die, emits no event and leaves the turn where it was: the host corrects its
choice and calls again. This mirrors how `submit_player_intent` refuses before
spending anything.

**When the monster cannot act.** A dead, fleeing or Incapacitated actor still
validates `target_id` (it is cheap and keeps the contract one sentence), then
takes the same `pass` path as today. A **summon**'s turn refuses any `target_id`
with `target_invalid`: uncommanded it Dodges and never attacks; a host that wants
it to attack commands it through `submit_player_intent`.

**Legendary actions.** `legendary=True` honours `target_id` the same way:
`_take_legendary_action` (`:3076`) takes the validated creature in place of its
lowest-HP pick (`:3106`), under the same pool test; `actor_id` picks the monster
as before. With no legal target the existing `no_legendary_action` refusal stands.

**Areas.** The override chooses the creature a single-target attack or cast is
made against. An action that places an area keeps the engine's aim — the
placement affecting the most enemies minus allies (`_resolve_monster_parts`,
`:2446-2475`) — whether or not that area covers `target_id`. Aiming an area is
a different choice from picking a creature, and no host has asked for it.

**Events.** Nothing new: `IntentSubmitted.target_id` and `AttackRolled.target_id`
already name the creature chosen, and a host that chose it knows it did.

### 3. Knocking out a creature

**Shape.** One new field on `PlayerIntent`, consumed by `attack` only:

```python
class PlayerIntent(BaseModel):
    ...
    # SRD 5.2 Knocking Out a Creature: "When you would reduce a creature to 0
    # Hit Points with a melee attack, you can instead reduce the creature to 1
    # Hit Point. The creature then has the Unconscious condition." The
    # attacker's choice for THIS attack: every melee hit it lands this intent
    # pulls the blow. Refused with ``IntentRejectedError("knock_out_not_melee")``
    # before anything is spent when the attack is not a melee attack: a ranged
    # weapon, or a Thrown melee weapon at a target beyond its reach. Ignored by
    # other intent types.
    knock_out: bool = False
```

`RejectionReason` gains `"knock_out_not_melee"`.

**Threading.** The flag rides the same channel as `is_opportunity_attack`:

- `ActivityResolutionContext.knock_out: bool = False` (`activities/context.py`),
  set by the orchestrator's attack site from the intent; opportunity attacks,
  readied attacks and monster turns leave it `False`.
- `apply_damage(..., knock_out: bool = False)` (`activities/apply.py:85`) stamps
  it on every `DamageApplied` it emits; `resolve_attack` passes
  `knock_out=ctx.knock_out and <this swing is a melee attack>`
  (`activities/attack.py:1095`), where a melee attack is
  `activity.attack.type.value == "melee"` and not
  `_attack_is_effectively_ranged(weapon, distance)`. Sneak Attack dice, Savage
  Attacker, a Cleave follow-up and a weapon's damage riders are part of the same
  hit and carry the flag; a save-based rider is not an attack and does not.
- The intent-time refusal uses the same predicate on the weapon the intent
  resolves and the distance the orchestrator already computes for the context,
  so the flag never silently kills: a swing that cannot be a melee attack is
  refused, a swing that can is pulled.

```python
class DamageApplied(BaseModel):
    ...
    # SRD 5.2 Knocking Out a Creature: the attacker chose to pull this blow.
    # Only a melee attack's damage carries it; the fold leaves a creature it
    # would have dropped at 1 Hit Point, Unconscious, instead of dead.
    knock_out: bool = False
```

**The fold** (`_emit_apply_damage`, `orchestrator.py:5232`): when `new_hp <= 0`,
the target is not dead and not a summon, and `event.knock_out` is true:

1. tracked HP and `hp_current` become 1 — the SRD's "instead";
2. `KnockedOut(target_id, attacker_id=live.current_actor_id)` is emitted, then
   `ConditionApplied(target_id, "unconscious")` through
   `_fold_condition_onto_combatant`, so every Unconscious rule applies at once:
   Incapacitated (its turn can only `pass`, `move` fails with `speed_zero`), Prone,
   Advantage against it and the auto-crit within 5 feet;
3. the id joins `live.knocked_out_ids`;
4. no `Death`, no `Unconscious` marker (that event means "dying" to a host), no
   death saves: the creature is at 1 Hit Point, not 0. A `Character` is knocked
   out the same way — the character path (`:5237`) is skipped — so a party-side
   creature pulled down by an ally is captured, not dying.

A summon is never knocked out: it "disappears when it drops to 0 Hit Points",
and keeps doing so (`:5232-5236`).

```python
# events.py
class KnockedOut(BaseModel):
    """SRD 5.2 Knocking Out a Creature: a melee attack that would have reduced
    ``target_id`` to 0 Hit Points left it at 1, Unconscious. Emitted after the
    ``DamageApplied`` that did it and before the ``ConditionApplied``."""

    type: Literal["knocked_out"] = "knocked_out"
    target_id: str
    attacker_id: str | None  # the current actor; ``None`` only outside a turn
```

`KnockedOut` joins the `CombatEvent` union and `ALL_COMBAT_EVENT_TYPES`
(`events.py:745-800`). Like the roster events it stays in `dnd5e_engine.events`,
not the top-level `__all__`.

**While knocked out.**

- The creature is **out of the fight**: `_select_monster_targets` excludes
  `knocked_out_ids` as it excludes 0-HP creatures, so no foe picks it and no host
  may name it as a target (§2); `_derive_ended_reason` counts it with the dead on
  its side (§1). A fight whose every foe is knocked out ends in `victory`.
- Its own turn comes round: a monster takes the Incapacitated `pass`
  (`:13135-13141`); a character's host submits `pass`. Regeneration at a
  monster's turn start (`_run_monster_turn_start`) heals it, and so wakes it,
  which is the SRD's "regains any Hit Points".
- **Waking.** `_emit_apply_healing` (`:5314`): any `HealingApplied` with
  `amount > 0` on a creature in `knocked_out_ids` removes it from the set and
  ends Unconscious the way a revive does — `ConditionRemoved("unconscious")`,
  then Prone if not already Prone (`:5341-5357`). The 0 → positive branch is
  untouched.
- **Damage while knocked out.** The creature is at 1 Hit Point: a hit (an auto-crit
  from within 5 feet) takes it to 0 and leaves `knocked_out_ids` — a monster
  dies, a character starts dying — through the existing branches with nothing
  special. A second pulled blow knocks it out again.
- **First aid** (DC 10 Wisdom (Medicine) as an action) is not modelled in this
  release: no intent spends an action on it, and a host adjudicates it after the
  fight, as the Short Rest the rule starts. Recorded in BACKLOG.md.

**At combat end.**

```python
# outcome.py
class KnockOutRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    target_kind: Literal["character", "npc", "monster"]
    attacker_id: str | None


class CombatOutcome(BaseModel):
    ...
    # Creatures still Unconscious from a knock-out when the combat ended, in
    # the order they were knocked out. A creature that woke or died is not here.
    knock_outs: list[KnockOutRecord] = Field(default_factory=list)
```

`residual_hp` reports its 1 Hit Point as for any party-side creature; a
knocked-out foe's HP is ephemeral, as every foe's is. `LiveCombatView` gains
`knocked_out_ids: set[str]` beside `dead_ids` (`views.py:91`). `KnockOutRecord`
is a top-level export beside `DeathRecord`.

**Not in scope.** A knock-out from a melee *spell* attack (`cast_spell` ignores
the flag; Shocking Grasp kills), and a foe's or an ally's choice to pull a blow
on `advance_monster_turn`. Both are additive later; neither has a consumer.

## Validation summary

| Input | Check | Refusal |
|---|---|---|
| `EncounterMemberSpec.side` | a `Side` literal | pydantic `ValidationError` |
| `start_combat` sides | at least one `side="encounter"` member | `ValueError` |
| `advance_monster_turn(target_id=)` | in `_select_monster_targets(live, actor)` | `IntentRejectedError("target_invalid")`, nothing spent |
| `advance_monster_turn(target_id=)` on a summon's turn | never legal | `IntentRejectedError("target_invalid")` |
| `advance_monster_turn(target_id=)` on a character's turn | existing check first | `IntentRejectedError("not_actor_turn")` |
| `PlayerIntent.knock_out` on `attack` | the swing is a melee attack | `IntentRejectedError("knock_out_not_melee")`, nothing spent |
| `PlayerIntent.knock_out` on any other intent | ignored | — |

Nothing here catches an exception: every refusal is a typed raise before state
changes, and the folds stay non-throwing as they are today.

## Backward compatibility and versioning

Every change is additive with a default that reproduces 0.7.0 byte for byte:
`side="encounter"`, `target_id=None`, `knock_out=False`,
`DamageApplied.knock_out=False`, empty `knock_outs` and `knocked_out_ids`. The
seeded draw order is untouched (no new roll, and a refused call draws nothing),
so `tests/test_determinism_contract.py` and every seeded pin hold.

Three things a host may notice, each listed in the changelog and a short
`docs/migration/v0.7-to-v0.8.md` after the pattern of the previous minors:

1. **`KnockedOut`** is a new member of the closed `CombatEvent` union: a host
   that matches events exhaustively needs a branch, as it did for
   `AreaTargeted` in 0.7.0.
2. **`RejectionReason`** gains `"knock_out_not_melee"`.
3. **`DeathRecord.target_kind`** can now be `"npc"` or `"monster"` for a
   creature a host seated on the party side — only when the host used `side`.

The release is 0.8.0 of all three packages in lockstep, as every release so far
(`release.yml`: data, then engine, then bridge), with the engine's floor raised to
`dnd5e-srd-data>=0.8.0` and the bridge's to both. The dataset itself does not
change.

## Tests

Conventions: flat `packages/dnd5e-engine/tests/test_<topic>.py` modules of
seeded `start_combat` + scripted intents + `event_log` assertions through the
`_get_live` seam, with small spec-builder helpers (`tests/c21_support.py`:
`pc`, `foe`, `start`, `act`, `monster_turn`, `events`); one end-to-end scenario
module under `tests/e2e/` on the harness; the public-surface and
capability-matrix guards updated in the same change; bridge tests under
`packages/nat20-bridge/tests/`. Every new module gets a module docstring quoting
the SRD rule it pins.

**`tests/test_combat_sides.py`**

- a `side="party"` NPC is in `party_ids`, not `encounter_ids`; `_is_enemy`
  pairs it against every foe and with every character and party summon;
- a foe's lowest-HP pick is the ally when its HP is lowest (`IntentSubmitted`
  and `AttackRolled` name it);
- `advance_monster_turn` on the ally's turn attacks a foe, closing distance
  first; `submit_player_intent(ally, pass)` is accepted;
- the ally at 0 Hit Points: `Death(reason="damage")`, a `DeathRecord` with
  `target_kind="npc"` and the foe as `killer_id`, no `Unconscious`, no
  `DeathSaveStarted`, no death save on its next turn; `residual_hp` carries the
  ally; XP is divided among surviving characters only;
- `ended_reason`: `victory` with the ally standing and every foe dead;
  `defeat_tpk` only once the ally is dead too; a start with only `side="party"`
  encounter members raises `ValueError`;
- a seeded combat whose specs carry no `side` emits the same event log as before
  (a frozen pin from an existing scenario).

**`tests/test_monster_target_override.py`**

- `target_id` picks the higher-HP character over the lowest-HP one;
  `IntentSubmitted.target_id` and `AttackRolled.target_id` agree;
- refused with `target_invalid`, and the event log, `live.rng.getstate()`,
  `current_turn_index` and every `MonsterActionUses` entry unchanged: an id not
  in the combat, an ally of the actor, a dead creature, a 0-HP character, a
  knocked-out creature, the actor's charmer, any id on a summon's turn;
- on a character's turn `not_actor_turn` still wins;
- a fleeing or Incapacitated actor validates the id and then records `pass`;
- an out-of-reach `target_id` makes the monster walk or Dash and never
  substitutes a nearer enemy;
- an area action aims by the engine's count, with `target_id` outside the area;
- `legendary=True, target_id=…` targets the named creature; an illegal id is
  refused before `LegendaryActionUsed`.

**`tests/test_knock_out.py`**

- a melee weapon hit that would drop a foe: `DamageApplied.knock_out`,
  `KnockedOut`, `ConditionApplied("unconscious")`, tracked HP 1, no `Death`,
  the id in `knocked_out_ids`; the same for an Unarmed Strike, for a summon's
  commanded Rend, and for a Thrown dagger within reach;
- refused with `knock_out_not_melee` and nothing spent (no `IntentSubmitted`,
  attacks remaining unchanged): a shortbow, a Thrown dagger beyond reach;
- a non-dropping hit carries `knock_out=True` and changes nothing else;
- Sneak Attack and a Cleave follow-up ride the flag; an opportunity attack during
  the knocked-out creature's ally's move never does;
- a knocked-out foe is out of every foe's target pool and refused as an override;
  with every foe knocked out the combat ends `victory` and `knock_outs` lists
  them in order with the attacker;
- a `HealingApplied` wakes it: `ConditionRemoved("unconscious")`, Prone applied,
  out of `knocked_out_ids`, not in `knock_outs`; a monster's regeneration at turn
  start does the same;
- a hit from within 5 feet on the knocked-out creature is a Critical Hit and
  kills a monster (`Death(reason="damage")`) or starts a character dying
  (`Unconscious`, then death saves); the id leaves `knocked_out_ids`;
- a character knocked out: no death saves on its turn, `pass` accepted, `attack`
  refused `actor_incapacitated`;
- a summon is never knocked out: it leaves with `CombatantLeft(zero_hp)`;
- `cast_spell` with `knock_out=True` is accepted and kills.

**`tests/e2e/test_c31_sides_targets_knockout.py`** — one scripted fight: two
characters, one ally, three foes; a host-chosen foe target each foe turn; the
last foe knocked out; `end_combat` reports the ally's death, the knock-out, XP for
the characters only, `victory`.

**Guards and parity**

- `tests/test_public_api_surface.py`: `KnockOutRecord` added to `TOP_LEVEL`;
  `KnockedOut` asserted absent from it, as the roster events are.
- `tests/test_capability_matrix.py`: the status-row probes for the new matrix
  rows (knock-out; the targeting row's wording).
- `tests/test_docstrings_are_host_agnostic.py` runs unchanged over the new prose.
- `packages/nat20-bridge/tests/test_c31_sides_targets_knockout.py`: `allies` on
  the start body seats `side="party"` members; `target_id` on the advance body
  reaches the engine and a refusal is a 409 with the reason; `knock_out` in an
  intent body reaches the engine (`_IntentRequest` subclasses `PlayerIntent`);
  `narrate` renders `KnockedOut`.

## Implementation breakdown

Each item is one commit on one branch; items whose files do not overlap can run
in parallel. `make check` at the root is the gate for each, `mkdocs build
--strict` for the docs items.

| Item | Files | Depends on |
|---|---|---|
| **A. Sides** — `Side`, `EncounterMemberSpec.side`, the two `start_combat` seatings and the non-empty check, the three `entity_type == "Character"` switches (`:5237`, `:7981`, `:13416`), `tests/test_combat_sides.py` | `specs.py`, `orchestrator.py` (seating, folds, outcome), new test | — |
| **B. Target override** — the keyword, the pre-turn-start validation, the legendary path, `tests/test_monster_target_override.py` | `orchestrator.py` (`advance_monster_turn`, `_take_legendary_action`), new test | — |
| **C. Knock-out, resolver side** — `ActivityResolutionContext.knock_out`, `apply_damage(knock_out=)`, the melee predicate in `resolve_attack`, `DamageApplied.knock_out`, `KnockedOut` in the union and registry | `activities/context.py`, `activities/apply.py`, `activities/attack.py`, `events.py` | — |
| **D. Knock-out, orchestrator side** — `PlayerIntent.knock_out`, the `knock_out_not_melee` refusal, the context flag at the attack site, the fold, waking, `knocked_out_ids` in `_select_monster_targets` and `_derive_ended_reason`, `LiveCombatView.knocked_out_ids`, `KnockOutRecord` and `CombatOutcome.knock_outs`, `__init__.py`, `tests/test_knock_out.py`, the public-surface guard | `orchestrator.py`, `views.py`, `outcome.py`, `__init__.py`, tests | C; shares `orchestrator.py` with A and B, so lands after them |
| **E. End-to-end scenario** | `tests/e2e/test_c31_sides_targets_knockout.py` | A, B, D |
| **F. Bridge parity** — `allies: list[str] = []` on `_CombatStartRequest` seated through `_build_encounter_specs(side="party")`; an optional `target_id` body on `/v1/combat/{cid}/advance-monster`; a `KnockedOut` formatter in `narrate.py`; tests | `packages/nat20-bridge/src/nat20_bridge/routes_combat.py`, `narrate.py`, tests | A, B, D |
| **G. Docs and closeout** — `docs/concepts/combat.md` (a "Sides" section after "Summoned creatures"; knock-out under the 0-HP rules), `docs/concepts/monsters.md` (the targeting line), `docs/capabilities.md` rows and the matrix probes, `docs/api.md` members, `docs/migration/v0.7-to-v0.8.md`, the three changelogs, BACKLOG.md (first aid; knock-out by spell attack or by a monster; a legendary ally), the lockstep 0.8.0 bump and floors | docs, `CHANGELOG.md` ×3, `BACKLOG.md`, `pyproject.toml` ×3, `uv.lock` | everything |

## Decisions

1. **Knocked-out creatures are excluded from the AI target pool** — not a legal
   foe target, not a legal `target_id`.
2. **An illegal `target_id` has no fallback** — `IntentRejectedError("target_invalid")`,
   nothing spent.
3. **Knock-out for a monster's turn and for a melee spell attack is deferred** —
   recorded in BACKLOG.md.
4. **`CombatOutcome.knock_outs` reports `KnockOutRecord`s, not bare ids.**
5. **The knock-out refusal is its own reason, `knock_out_not_melee`** — not a
   reuse of `target_invalid`.
6. **First aid as an intent is deferred** — recorded in BACKLOG.md.
