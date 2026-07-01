import importlib

import dnd5e_engine

TOP_LEVEL = {
    "AbilityScores",
    "ActionType",
    "ActiveEffect",
    "ActiveEffectChange",
    "ActiveEffectDuration",
    "CharacterBuildSpec",
    "CheckKind",
    "CheckResult",
    "CheckSpec",
    "CombatEvent",
    "CombatHandle",
    "CombatInstance",
    "CombatOutcome",
    "DeathRecord",
    "EncounterMemberSpec",
    "EndCombatResult",
    "GridScene",
    "IntentType",
    "LiveCombatView",
    "LootDrop",
    "PartyMemberSpec",
    "PlayerIntent",
    "SceneTopology",
    "StartCombatResult",
    "ZoneEdge",
    "advance_monster_turn",
    "build_party_member",
    "cell_id",
    "end_combat",
    "get_actor_active_effects",
    "get_live",
    "make_build_spec",
    "narration_events",
    "parse_cell",
    "resolve_check",
    "roll_dice_str",
    "start_combat",
    "submit_player_intent",
}

PUBLIC_MODULES = [
    "dnd5e_engine.rules.combat",
    "dnd5e_engine.rules.conditions",
    "dnd5e_engine.rules.dice",
    "dnd5e_engine.rules.equipment",
    "dnd5e_engine.rules.gambits",
    "dnd5e_engine.rules.resolution",
    "dnd5e_engine.rules.skills",
    "dnd5e_engine.rules.spells",
    "dnd5e_engine.rules.combat_data",
    "dnd5e_engine.rules.combat_helpers",
    "dnd5e_engine.events",
    "dnd5e_engine.event_dicts",
    "dnd5e_engine.death_saves",
    "dnd5e_engine.outcome",
    "dnd5e_engine.dispatch",
    "dnd5e_engine.specs",
    "dnd5e_engine.spatial",
    "dnd5e_engine.lib_loader",
    "dnd5e_engine.check",
    "dnd5e_engine.build_spec",
    "dnd5e_engine.build_party",
    "dnd5e_engine.results",
    "dnd5e_engine.types.intent",
    "dnd5e_engine.types.combat",
    "dnd5e_engine.types.conditions",
    "dnd5e_engine.types.dice",
    "dnd5e_engine.types.effects",
    "dnd5e_engine.testing",
]


def test_top_level_surface_is_exact():
    assert set(dnd5e_engine.__all__) == TOP_LEVEL


def test_every_public_module_declares_all():
    missing = [
        m for m in PUBLIC_MODULES if not getattr(importlib.import_module(m), "__all__", None)
    ]
    assert missing == [], f"modules without __all__: {missing}"


def test_all_names_are_importable():
    for m in PUBLIC_MODULES:
        mod = importlib.import_module(m)
        for name in mod.__all__:
            assert hasattr(mod, name), f"{m}.{name} missing"
