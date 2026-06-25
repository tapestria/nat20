# API reference

API reference rendered from source docstrings via mkdocstrings, covering the
public API surface (`dnd5e_engine.__all__`). Every symbol below is exported from
the top-level `dnd5e_engine` package.

## Combat loop

::: dnd5e_engine.orchestrator
    options:
      members_order: source
      members:
        - start_combat
        - submit_player_intent
        - advance_monster_turn
        - end_combat
        - narration_events
        - get_actor_active_effects
        - PlayerIntent
        - CombatHandle

## Results and outcome

::: dnd5e_engine.results
    options:
      members_order: source

::: dnd5e_engine.outcome
    options:
      members_order: source
      members:
        - CombatOutcome
        - DeathRecord
        - LootDrop

## Checks

::: dnd5e_engine.check
    options:
      members_order: source
      members:
        - resolve_check
        - CheckSpec
        - CheckResult
        - CheckKind

## Scene and grid specs

::: dnd5e_engine.specs
    options:
      members_order: source

::: dnd5e_engine.spatial
    options:
      members_order: source
      members:
        - cell_id
        - parse_cell

## Character building

::: dnd5e_engine.build_spec
    options:
      members_order: source
      members:
        - make_build_spec
        - CharacterBuildSpec
        - AbilityScores
        - CombatInstance

::: dnd5e_engine.build_party
    options:
      members_order: source
      members:
        - build_party_member

## Effects

::: dnd5e_engine.types.effects
    options:
      members_order: source
      members:
        - ActiveEffect
        - ActiveEffectChange
        - ActiveEffectDuration

## Events and intent types

::: dnd5e_engine.events
    options:
      members_order: source
      members:
        - CombatEvent
        - IntentType

::: dnd5e_engine.types.intent
    options:
      members_order: source
      members:
        - ActionType
