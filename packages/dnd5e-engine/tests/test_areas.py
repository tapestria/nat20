"""Areas of effect: the pure helpers in ``dnd5e_engine.areas``.

SRD 5.2 §Areas of Effect: a Sphere's or a Cylinder's point of origin is in its
area, a Cone's, a Cube's, an Emanation's and a Line's "isn't included in the
area of effect unless its creator decides otherwise"; "To block a line, an
obstruction must provide Total Cover". Stat blocks name "which creatures make
the save" ("each creature in a 60-foot Cone", "each enemy in a 20-foot-radius
Sphere"); spells name "each creature of your choice" and "up to six creatures".
"""

from __future__ import annotations

import typing

import pytest
from dnd5e_srd_data.schema.common import (
    AttackActivity,
    DamageActivity,
    HealActivity,
    SaveActivity,
    TargetAffectsBlock,
    TargetBlock,
    TargetTemplateBlock,
    UtilityActivity,
)
from pydantic import TypeAdapter, ValidationError

from dnd5e_engine import events as events_module
from dnd5e_engine.areas import (
    AreaTemplate,
    area_activity,
    area_cells,
    area_template,
    creature_count,
    has_line_of_effect,
    is_choice,
    is_harmful,
    select_affected,
)
from dnd5e_engine.events import ALL_COMBAT_EVENT_TYPES, AreaShape, AreaTargeted, CombatEvent
from dnd5e_engine.spatial import GridTopology, cell_id
from dnd5e_engine.specs import GridScene


def _target(
    shape: str = "",
    size: str = "",
    *,
    affects: str = "creature",
    count: str = "",
    choice: bool = False,
) -> TargetBlock:
    return TargetBlock(
        template=TargetTemplateBlock(type=shape, size=size),
        affects=TargetAffectsBlock(type=affects, count=count, choice=choice),
    )


def _save(shape: str = "", size: str = "", **affects: object) -> SaveActivity:
    return SaveActivity(target=_target(shape, size, **affects))


# ── which activity is an area ────────────────────────────────────────────────


def test_the_first_templated_save_damage_or_heal_activity_is_the_area() -> None:
    plain = _save()
    sphere = _save("sphere", "20")
    assert area_activity([plain, sphere]) is sphere
    heal = HealActivity(target=_target("sphere", "30"))
    damage = DamageActivity(target=_target("square", "5"))
    assert area_activity([heal]) is heal
    assert area_activity([damage]) is damage


def test_an_attack_or_utility_activity_is_never_an_area() -> None:
    # The Torch's attack carries its light radius; Holy Aura's utility its aura.
    torch = AttackActivity(target=_target("radius", "40"))
    aura = UtilityActivity(target=_target("radius", "30", choice=True))
    assert area_activity([torch, aura]) is None
    assert area_activity([]) is None


@pytest.mark.parametrize(
    ("foundry", "expected"),
    [
        ("sphere", ("sphere", "sphere", "target", True)),
        ("circle", ("sphere", "sphere", "target", True)),
        ("cylinder", ("cylinder", "cylinder", "target", True)),
        ("radius", ("emanation", "sphere", "actor", False)),
        ("cube", ("cube", "cube", "actor", False)),
        ("square", ("cube", "cube", "actor", False)),
        ("cone", ("cone", "cone", "actor", False)),
        ("line", ("line", "line", "actor", False)),
    ],
)
def test_foundry_template_types_map_to_srd_shapes(
    foundry: str, expected: tuple[str, str, str, bool]
) -> None:
    template = area_template(_save(foundry, "15"))
    assert template is not None
    assert (template.shape, template.grid_shape, template.anchor, template.includes_origin) == (
        expected
    )
    assert template.size_ft == 15
    assert template.directional is (expected[1] in ("cone", "cube", "line"))


@pytest.mark.parametrize(
    ("shape", "size"),
    [("wall", "60"), ("sphere", "@item.level * 5"), ("sphere", "0"), ("hex", "5")],
)
def test_a_template_the_grid_cannot_place_maps_to_none(shape: str, size: str) -> None:
    assert area_template(_save(shape, size)) is None


# ── "up to N creatures" and "of your choice" ────────────────────────────────


@pytest.mark.parametrize(
    ("affects", "count", "expected"),
    [
        ("creature", "1", 1),
        ("", "6", 6),
        ("creatureOrObject", "1", 1),
        ("enemy", "2", 2),
        ("creature", "", None),
        ("creature", "0", None),
        ("creature", "2 + @item.level", None),
        ("space", "1", None),
        ("object", "1", None),
        ("self", "1", None),
    ],
)
def test_creature_count_reads_a_whole_number_of_creatures(
    affects: str, count: str, expected: int | None
) -> None:
    assert creature_count(_save("sphere", "10", affects=affects, count=count)) == expected


def test_choice_and_harm_come_from_the_activities() -> None:
    assert is_choice(_save("sphere", "5", choice=True))
    assert not is_choice(_save("sphere", "20"))
    assert is_harmful([_save("sphere", "20")])
    assert is_harmful([DamageActivity(target=_target("square", "5"))])
    assert not is_harmful([HealActivity(target=_target("sphere", "30"))])


# ── where the area lies ──────────────────────────────────────────────────────


def _template(grid_shape: str, size_ft: int, *, includes_origin: bool) -> AreaTemplate:
    shape = {"sphere": "sphere", "cone": "cone", "line": "line", "cube": "cube"}[grid_shape]
    return AreaTemplate(shape, grid_shape, size_ft, "actor", includes_origin)


def test_a_sphere_keeps_its_origin_and_an_emanation_drops_it() -> None:
    grid = GridTopology(GridScene(width=5, height=5))
    origin = cell_id(2, 2)
    sphere = area_cells(grid, _template("sphere", 5, includes_origin=True), origin, None)
    emanation = area_cells(grid, _template("sphere", 5, includes_origin=False), origin, None)
    assert origin in sphere
    assert len(sphere) == 9
    assert origin not in emanation
    assert emanation == sphere - {origin}


def test_a_cone_widens_along_its_direction_without_its_origin() -> None:
    grid = GridTopology(GridScene(width=6, height=6))
    cone = area_cells(grid, _template("cone", 10, includes_origin=False), cell_id(0, 2), (1, 0))
    assert cell_id(0, 2) not in cone
    assert {cell_id(1, 2), cell_id(2, 2), cell_id(2, 1), cell_id(2, 3)} <= cone


def test_a_wall_cuts_the_area_but_a_creature_never_does() -> None:
    walled = GridTopology(
        GridScene(width=7, height=1, wall_segments=[{"x1": 4, "y1": 0, "x2": 4, "y2": 1}])
    )
    line = area_cells(walled, _template("line", 30, includes_origin=False), cell_id(0, 0), (1, 0))
    assert line == {cell_id(1, 0), cell_id(2, 0), cell_id(3, 0)}
    assert has_line_of_effect(walled, cell_id(1, 0), cell_id(1, 0))
    assert not has_line_of_effect(walled, cell_id(3, 0), cell_id(4, 0))


# ── whom the area affects ────────────────────────────────────────────────────

_ENEMIES = {"mon:a", "mon:b"}
_ALLIES = {"char:me", "char:ally"}


def _select(in_area: list[str], **kwargs: object):
    base: dict[str, object] = {
        "affects_type": "creature",
        "choice": False,
        "count": None,
        "harmful": True,
        "excluded_ids": None,
        "is_enemy": lambda i: i in _ENEMIES,
        "is_ally": lambda i: i in _ALLIES,
    }
    return select_affected(in_area, **(base | kwargs))


IN_AREA = ["char:me", "mon:a", "char:ally", "mon:b"]


def test_an_area_with_no_choice_affects_everyone_in_it() -> None:
    selection = _select(IN_AREA)
    assert selection.affected_ids == tuple(IN_AREA)
    assert selection.spared_ids == ()


def test_each_enemy_and_each_ally_keep_only_that_side() -> None:
    assert _select(IN_AREA, affects_type="enemy").affected_ids == ("mon:a", "mon:b")
    assert _select(IN_AREA, affects_type="ally").affected_ids == ("char:me", "char:ally")


def test_a_harmful_choice_area_spares_the_actors_side_by_default() -> None:
    selection = _select(IN_AREA, choice=True)
    assert selection.affected_ids == ("mon:a", "mon:b")
    assert selection.spared_ids == ("char:me", "char:ally")


def test_a_helpful_choice_area_keeps_the_actor_and_its_allies() -> None:
    selection = _select(IN_AREA, choice=True, harmful=False)
    assert selection.affected_ids == ("char:me", "char:ally")
    assert selection.spared_ids == ("mon:a", "mon:b")


def test_an_empty_exclusion_list_opts_everyone_in() -> None:
    assert _select(IN_AREA, choice=True, excluded_ids=()).affected_ids == tuple(IN_AREA)


def test_an_exclusion_list_replaces_the_default() -> None:
    selection = _select(IN_AREA, choice=True, excluded_ids=("char:ally", "mon:elsewhere"))
    assert selection.affected_ids == ("char:me", "mon:a", "mon:b")
    assert selection.spared_ids == ("char:ally",)


def test_a_count_keeps_the_first_n_of_the_default() -> None:
    selection = _select(IN_AREA, count=1)
    assert selection.affected_ids == ("mon:a",)
    assert selection.spared_ids == ("char:me", "char:ally", "mon:b")


# ── the AreaTargeted event ───────────────────────────────────────────────────


def test_area_targeted_is_a_registered_discriminated_event() -> None:
    event = AreaTargeted(
        actor_id="char:wiz",
        source_id="sleep",
        shape="sphere",
        size_ft=5,
        origin=cell_id(5, 5),
        direction=None,
        affected_ids=["mon:g1", "mon:g2"],
        excluded_ids=["char:wiz"],
    )
    assert event.type == "area_targeted"
    assert AreaTargeted in ALL_COMBAT_EVENT_TYPES
    assert {"AreaTargeted", "AreaShape"} <= set(events_module.__all__)
    for dumped in (event.model_dump(), event.model_dump(mode="json")):
        round_tripped = TypeAdapter(CombatEvent).validate_python(dumped)
        assert isinstance(round_tripped, AreaTargeted)
        assert round_tripped == event


def test_area_targeted_carries_every_field_a_host_draws_with() -> None:
    fields = [
        "actor_id",
        "source_id",
        "shape",
        "size_ft",
        "origin",
        "direction",
        "affected_ids",
        "excluded_ids",
    ]
    assert list(AreaTargeted.model_fields) == ["type", *fields]
    required = [name for name, f in AreaTargeted.model_fields.items() if f.is_required()]
    assert required == fields


def test_area_shapes_are_the_six_srd_shapes() -> None:
    assert typing.get_args(AreaShape) == ("cone", "cube", "cylinder", "emanation", "line", "sphere")
    with pytest.raises(ValidationError):
        AreaTargeted(
            actor_id="char:wiz",
            source_id="wall-of-fire",
            shape="wall",
            size_ft=60,
            origin=cell_id(0, 0),
            direction=None,
            affected_ids=[],
            excluded_ids=[],
        )
