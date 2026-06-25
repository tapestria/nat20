"""``heal`` kind handler for the Activity resolver.

Foundry ``heal-data.mjs`` stores healing as a single ``DamagePartBlock``
(:class:`HealActivity.healing`), not a list. The ``types`` list carries a
single token: ``"healing"`` for HP restoration, ``"temphp"`` for a temporary
HP buffer — both confirmed against canonical SRD 5.2 data (cure-wounds.json
emits ``"healing"``; false-life.json emits ``"temphp"``). When ``temphp`` is
present we emit :class:`TempHpApplied`, otherwise :class:`HealingApplied`.

MIRRORS, does not import from, ``effects/temphp.py`` for the temp-hp token
distinction. The keep-higher replacement policy lives only on the Avrae-IR
``effects/`` path (which carries an existing-temp-HP lookup); the typed
Activity resolver emits the rolled grant directly, matching how ``apply.py``
emits the rolled magnitude for damage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dnd5e_engine.activities.dice import roll_damage_part
from dnd5e_engine.activities.effects import apply_activity_effects
from dnd5e_engine.activities.formula import resolve_damage_block
from dnd5e_engine.events import HealingApplied, TempHpApplied

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import HealActivity

    from .context import ActivityResolutionContext

# Foundry healing type token for a temporary HP grant (vs "healing" for HP
# restoration). Confirmed as the only temp-hp marker in canonical SRD 5.2 data.
_TEMP_HP_TYPE: Final[str] = "temphp"


def resolve_heal(activity: HealActivity, ctx: ActivityResolutionContext) -> None:
    """Roll ``activity.healing`` once per target and emit a healing event.

    No-op only when the healing block carries nothing to restore: no dice
    (``number``/``denomination``), no ``bonus``, AND no active ``custom.formula``.
    A custom-only block (Heroism's ``custom.formula == "@mod"`` temp-HP grant) is
    NOT empty — its magnitude lives entirely in ``custom.formula``.
    """
    healing = activity.healing
    has_dice = healing.number is not None and healing.denomination is not None
    has_custom = healing.custom.enabled and bool(healing.custom.formula)
    if not has_dice and not healing.bonus and not has_custom:
        return

    # The healing formulas carry Foundry roll-data tokens (Cure Wounds' ``@mod``
    # bonus, Heroism's ``@mod`` custom formula, the flat upcast ``scaling.formula``);
    # resolve them against the caster's spellcasting ability before the dice helper
    # parses them. ``roll_damage_part`` stays ctx-agnostic.
    healing = resolve_damage_block(healing, ctx, ability=ctx.spellcasting_ability)

    is_temp_hp = _TEMP_HP_TYPE in healing.types
    cast_level = ctx.slot_level or ctx.base_spell_level or 0
    for target in ctx.targets:
        amount = roll_damage_part(
            healing,
            ctx.rng,
            slot_level=ctx.slot_level,
            base_level=ctx.base_spell_level,
        )
        if is_temp_hp:
            ctx.event_emitter(TempHpApplied(target_id=target.entity_id, amount=amount))
        else:
            ctx.event_emitter(HealingApplied(target_id=target.entity_id, amount=amount))
        # Heal carries effect riders too (Aid's +max-HP, Heroism's frightened-
        # immunity): apply them PER target AFTER that target's heal event, matching
        # save.py's event-then-rider order. Heal has no save, so save_succeeded=None.
        apply_activity_effects(activity, ctx, target, save_succeeded=None, cast_level=cast_level)
