from dnd5e_engine.activities.actor_stats import check_modifier, proficiency_bonus_of, save_modifier
from dnd5e_engine.types.combat import Combatant


def _pc(**kw):
    base = dict(
        entity_id="char:a",
        entity_type="Character",
        name="A",
        initiative=10,
        hp_current=10,
        hp_max=10,
        character_level=5,
    )
    return Combatant(**{**base, **kw})


def test_save_modifier_uses_ability_and_proficiency():
    c = _pc(constitution=16, save_proficiencies=["con"])
    m = save_modifier(c, "con")
    assert (m.ability_mod, m.proficiency, m.total) == (3, 3, 6)  # L5 → PB 3


def test_save_modifier_without_proficiency_is_ability_only():
    assert save_modifier(_pc(wisdom=8), "wis").total == -1


def test_check_modifier_expertise_doubles_proficiency():
    c = _pc(dexterity=14, skill_proficiencies=["stealth"], skill_expertise=["stealth"])
    m = check_modifier(c, "dex", "stealth")
    assert m.expertise
    assert m.total == 2 + 6


def test_monster_proficiency_uses_override_not_level():
    m = Combatant(
        entity_id="mon:x",
        entity_type="Monster",
        name="X",
        initiative=1,
        hp_current=5,
        hp_max=5,
        proficiency_bonus_override=4,
    )
    assert proficiency_bonus_of(m) == 4


def test_defaults_reproduce_legacy_dex_only_projection():
    c = _pc(dexterity=18)
    assert save_modifier(c, "dex").total == 4
    assert save_modifier(c, "str").total == 0
