"""Phase 6 — lock the engine's public export surface."""

from __future__ import annotations


def test_phase6_public_surface():
    import dnd5e_engine

    # Phase 6 additions
    for name in ("ActiveEffect", "ActiveEffectChange", "ActiveEffectDuration"):
        assert hasattr(dnd5e_engine, name), f"missing export: {name}"
        assert name in dnd5e_engine.__all__, f"missing __all__: {name}"

    # Phase 6 deletions — symbols MAY still exist as names on submodules
    # (the import isn't necessarily removed everywhere) but they must NOT
    # be on the package public surface (__all__) anymore.
    for name in ("EffectModifier", "EffectRef", "CarriedCondition"):
        assert name not in dnd5e_engine.__all__, (
            f"{name} should be retired from public surface __all__"
        )


def test_plan4_public_surface_additions():
    import dnd5e_engine

    for name in ("get_live", "LiveCombatView", "roll_dice_str"):
        assert hasattr(dnd5e_engine, name), f"missing export: {name}"
        assert name in dnd5e_engine.__all__, f"missing __all__: {name}"
