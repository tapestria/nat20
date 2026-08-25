# API reference

Rendered from source docstrings, covering the public API surface
(`dnd5e_engine.__all__`). Every symbol below is exported from the top-level
`dnd5e_engine` package, and that list is pinned by
`tests/test_public_api_surface.py` — nothing here can change without the test
changing with it.

For what the engine actually resolves behind these signatures, see the
[capability matrix](capabilities.md).

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

## Content loading

The engine ships no rules data. It reads typed content through a process-wide
`AssetLoader`, which defaults to the bundled SRD 5.2 corpus. Install your own to
drive the engine from a different corpus.

::: dnd5e_engine.lib_loader
    options:
      members_order: source
      members:
        - get_lib_loader
        - configure_lib_loader

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
        - GridTopology
        - SpatialTopology

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

## Live combat view

::: dnd5e_engine.views
    options:
      members_order: source
      members:
        - LiveCombatView

## Rest & recovery

::: dnd5e_engine.rest
    options:
      members_order: source
      members:
        - resolve_short_rest
        - resolve_long_rest
        - recover_feature_uses
        - recover_item_uses
        - HitDicePool
        - RestOutcome
        - RecoveryPeriod

## Effects

::: dnd5e_engine.types.effects
    options:
      members_order: source
      members:
        - ActiveEffect
        - ActiveEffectChange
        - ActiveEffectDuration

## Dice

::: dnd5e_engine.rules.effects
    options:
      members_order: source
      members:
        - roll_dice_str

## Events and intent types

::: dnd5e_engine.events
    options:
      members_order: source
      members:
        - CombatEvent
        - IntentType
