"""Public preparation replay: fewer real drags, identical per-area roster."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from SRACore.util.errors import ThreadStoppedError
from extensions.cw_plus.characters import Character, Characters, Positioning
from extensions.cw_plus.logic import SlotObservation, SlotState
from extensions.cw_plus.preparation import Readiness
from tests.test_currency_wars_slow_preparation import ReplayClock, ReplayOperator, ReplayVision, engine


class FormationOrderOperator(ReplayOperator):
    def __init__(self, clock):
        super().__init__(clock)
        self.type = "Replay"  # Never select native pointer-release or GUI capture code.
        self.moves = []
        self.scenes = []
        self.capacity = 4
        self.hide_destination_after_drag = False
        self.stop_after_drag = False

    def drag_to(self, source_x, source_y, target_x, target_y, **kwargs):
        source = self.points[source_x, source_y]
        target = self.points[target_x, target_y]
        before_source = self.scene.get(source, (None, 0))
        before_target = self.scene.get(target, (None, 0))
        assert before_source[0] is not None
        self.moves.append((source, target, before_source, before_target))
        self.inputs.append(("drag", source, target))
        self.scene[source], self.scene[target] = before_target, before_source
        assert sum(bool(name) for (area, _), (name, _) in self.scene.items()
                   if area != "in_hand") <= self.capacity
        self.scenes.append(dict(self.scene))
        if self.hide_destination_after_drag:
            self.unknown.add(target)
        if self.stop_after_drag:
            self.stop_event.set()
        return True

    def ocr(self, **kwargs):
        assert kwargs.get("from_x") == .49  # Empty special-event title, not a character panel.
        return []


class FormationOrderVision(ReplayVision):
    def operator_ocr(self, **kwargs):
        # Character panels are recorded perception; the replay contains no event popup.
        if kwargs.get("from_x") == .775:
            return super().operator_ocr(**kwargs)
        return []

    def read_population(self, **kwargs):
        self.operator.clock.advance(.15)
        return SimpleNamespace(current=sum(
            bool(name) for (area, _), (name, _) in self.operator.scene.items() if area != "in_hand"),
            capacity=self.operator.capacity, evidence="two_population_frames")


@pytest.fixture
def formation_order(tmp_path, monkeypatch):
    saved = [(character, vars(character).copy())
             for character in {id(c): c for c in Characters.characters.values()}.values()]
    clock = ReplayClock()
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(engine, "CurrencyWarsVision", FormationOrderVision)
    operator = FormationOrderOperator(clock)
    task = engine.CurrencyWars(operator, 1, data_dir=tmp_path / "runtime")
    task.load_strategy(str(Path(engine.__file__).parent / "strategies/himeko_global_europe_20261026.json"))
    # 10:52:36 in run-105639-analysis/run.log: 3/4, main carry still on the bench.
    operator.scene = {
        ("on_field", 0): ("椒丘", 1), ("on_field", 1): ("阿格莱雅", 1),
        ("off_field", 0): ("刻律德菈", 1),
        ("in_hand", 0): ("姬子·启行", 1), ("in_hand", 1): ("阮·梅", 1),
        ("in_hand", 2): ("阿格莱雅", 1), ("in_hand", 4): ("砂金", 1),
        ("in_hand", 5): ("丹恒·饮月", 1),
    }
    for area, slots in task._observations.items():
        for index in range(len(slots)):
            operator.points[getattr(task, area + "_area")[index]] = (area, index)
            name, stars = operator.scene.get((area, index), (None, 0))
            observation = SlotObservation(index, SlotState.KNOWN if name else SlotState.EMPTY,
                Characters.get_character(name) if name else None, bool(name),
                "name_match" if name else "empty_detector", stars=stars if name else None)
            slots[index] = observation
            getattr(task, area + "_character")[index] = observation.character
            task._slot_evidence[area, index] = (observation, clock.value)
    task._layout_valid = task._backend_identity_confirmed = True
    task._backend_ordinary_slots = tuple(range(6))
    task._confirmed_layout_positions = tuple(task.off_field_area)
    task._bench_dirty = task._placement_pending = False
    task._bench_observed_at = task._field_observed_at = clock.value
    try:
        yield SimpleNamespace(task=task, operator=operator, clock=clock)
    finally:
        for character, attributes in saved:
            vars(character).update(attributes)


def scene_roster(operator):
    return {area: sorted((name, stars) for (place, _), (name, stars) in operator.scene.items()
                        if place == area and name)
            for area in ("on_field", "off_field", "in_hand")}


def test_recorded_carry_deployment_keeps_same_roster_without_roundtrip(formation_order, record_property):
    task, operator, clock = formation_order.task, formation_order.operator, formation_order.clock
    started = clock.value

    result = task.prepare_for_battle()

    record_property("virtual_seconds", clock.value - started)
    record_property("drags", json.dumps(operator.moves, ensure_ascii=False))
    assert result.state == Readiness.DEGRADED, result
    # Literal independently observed final roster from 10:53:11, before March's purchase.
    assert scene_roster(operator) == {
        "on_field": sorted([("姬子·启行", 1), ("丹恒·饮月", 1), ("椒丘", 1)]),
        "off_field": [("刻律德菈", 1)],
        "in_hand": sorted([("阮·梅", 1), ("阿格莱雅", 1), ("阿格莱雅", 1), ("砂金", 1)]),
    }
    assert len(operator.moves) == 2, operator.moves


def test_shortened_route_still_blocks_on_an_unconfirmed_destination(formation_order):
    task, operator = formation_order.task, formation_order.operator
    operator.hide_destination_after_drag = True

    result = task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert len(operator.moves) == 1  # Never replay the unresolved drag or send its planned successor.
    assert operator.moves[0][1] in operator.slot_clicks


def test_stop_after_shortened_drag_propagates_without_the_next_input(formation_order):
    task, operator = formation_order.task, formation_order.operator
    operator.stop_after_drag = True

    with pytest.raises(ThreadStoppedError):
        task.prepare_for_battle()

    assert operator.inputs == [("drag", ("in_hand", 0), ("on_field", 2))]


def test_full_population_does_not_borrow_a_future_xp_slot(formation_order):
    task, operator = formation_order.task, formation_order.operator
    operator.capacity = 3

    result = task.prepare_for_battle()

    assert result.state == Readiness.DEGRADED, result
    assert scene_roster(operator)["on_field"] == sorted([("姬子·启行", 1), ("丹恒·饮月", 1)])
    assert scene_roster(operator)["off_field"] == [("刻律德菈", 1)]
    assert len(operator.moves) == 2


def test_real_survival_provider_remains_fielded_during_carry_deployment(formation_order):
    task, operator = formation_order.task, formation_order.operator
    provider = Characters.get_character("藿藿")
    key = ("on_field", 0)
    observation = replace(task._observations[key[0]][key[1]], character=provider)
    task._observations[key[0]][key[1]] = observation
    task.on_field_character[0] = provider
    task._slot_evidence[key] = (observation, formation_order.clock.value)
    operator.scene[key] = ("藿藿", 1)

    result = task.prepare_for_battle()

    assert result.state == Readiness.DEGRADED, result
    assert all(scene[key] == ("藿藿", 1) for scene in operator.scenes)
    assert scene_roster(operator)["on_field"] == sorted([
        ("藿藿", 1), ("姬子·启行", 1), ("丹恒·饮月", 1)])


def test_confirmed_npc_seat_is_not_treated_as_spare_population(formation_order):
    task, operator = formation_order.task, formation_order.operator
    support = Character("锁定支援单位", 0, Positioning.OffField, is_locked=True, is_npc=True)
    key = ("off_field", 5)
    task._observations["off_field"][5] = SlotObservation(5, SlotState.KNOWN, support, True,
                                                       "two_frame_locked_support")
    task.off_field_character[5] = support
    task._slot_evidence.pop(key)
    task._backend_ordinary_slots = tuple(range(5))
    task._backend_support_slots = {5: support}
    operator.scene[key] = (support.name, 0)

    result = task.prepare_for_battle()

    assert result.state == Readiness.DEGRADED, result
    assert all(scene[key] == (support.name, 0) for scene in operator.scenes)
    assert scene_roster(operator)["on_field"] == sorted([("姬子·启行", 1), ("丹恒·饮月", 1)])
    assert len(operator.moves) == 2
