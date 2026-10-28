"""Preparation replay: real engine decisions with recorded perception, no OS input."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image

RUNTIME_ROOT = Path(os.environ.get("SRA_CW_RUNTIME_ROOT", Path(__file__).resolve().parents[1]))
if os.environ.get("SRA_CW_RUNTIME_ROOT"):
    sys.path.insert(0, str(RUNTIME_ROOT))

from SRACore.operators.model import Box
from SRACore.util.errors import ThreadStoppedError
from extensions.cw_plus.characters import Characters
from extensions.cw_plus.layout import LayoutObservation
from extensions.cw_plus.logic import SlotObservation, SlotState
from extensions.cw_plus.preparation import Readiness
from extensions.cw_plus.unicode_templates import load_template

engine = importlib.import_module("extensions.cw_plus.CurrencyWars")


class ReplayClock:
    def __init__(self):
        self.value = 1000.0

    def monotonic(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ReplayOperator:
    def __init__(self, clock):
        self.clock = clock
        self.settings = SimpleNamespace()
        self.window_context = SimpleNamespace(width=1920, height=1080)
        self.stop_event = Event()
        self.tm_confidence = 0.9999
        self.selected = None
        self.points = {}
        self.scene = {}
        self.inputs = []
        self.slot_clicks = []
        self.unknown = set()
        self.missing_stars = set()
        self.frame = Image.new("RGB", (1920, 1080), (15, 25, 35))
        self.frame.paste(load_template(engine.CWIMG.PREPARATION_STAGE).convert("RGB"), (20, 20))

    def screenshot(self):
        return self.frame.copy()

    def sleep(self, seconds):
        self.clock.advance(seconds)

    def click_point(self, x, y, *, after_sleep=0, **kwargs):
        self.selected = self.points.get((x, y))
        if self.selected is not None:
            self.slot_clicks.append(self.selected)
        self.clock.advance(after_sleep)
        return True

    def move_to(self, *args, **kwargs):
        return True

    def locate(self, *args, **kwargs):
        return None

    def locate_all(self, template, **kwargs):
        if self.selected in self.missing_stars:
            return []
        _, stars = self.scene.get(self.selected, (None, 0))
        return [Box(10 + 15 * i, 10, 5, 5) for i in range(stars)]

    def currency_wars_slot_is_empty(self, area, index):
        return self.scene.get((area, index), (None, 0))[0] is None

    def press_key(self, key, **kwargs):
        self.inputs.append(("key", key))
        raise AssertionError("Replay must not buy, sell or start battle")

    def mouse_down(self, *args, **kwargs):
        self.inputs.append(("drag", args))
        raise AssertionError("No movement is needed for this recorded roster")


class ReplayVision:
    def __init__(self, operator, *args, **kwargs):
        self.operator = operator
        self.last_sample_reason = "replay"
        self.last_empty_slot_reasons = {}
        self.last_layout_diagnostics = {}
        self.layout_reads = 0

    def operator_ocr(self, **kwargs):
        self.operator.clock.advance(3)
        key = self.operator.selected
        name, _ = self.operator.scene.get(key, (None, 0))
        if key in self.operator.unknown or name is None:
            return []
        return [([[0, 0], [180, 0], [180, 40], [0, 40]], name, 0.999)]

    def _engine_ocr(self, *args, **kwargs):
        return []

    def _terminal_template_point(self, *args):
        return None

    def read_combat_screen(self, frame):
        return SimpleNamespace(state="preparation")

    def read_backend_layout(self, previous_positions, **kwargs):
        self.layout_reads += 1
        # The user's log contains roughly 50 s of field work plus 20 s of bench work.
        self.operator.clock.advance(40)
        if getattr(self, "stop_during_layout", False):
            self.operator.stop_event.set()
        return LayoutObservation(True, tuple(previous_positions), reason="replay_layout",
            geometry_valid=True, ordinary_count_confirmed=True,
            ordinary_slots=tuple(range(6)), ordinary_count=6)

    def read_empty_slots(self, area, positions):
        self.operator.clock.advance(2)
        indices = positions.keys() if isinstance(positions, dict) else range(len(positions))
        return {i: self.operator.currency_wars_slot_is_empty(area, i) for i in indices}

    def read_locked_bench_slots(self, positions):
        return set()

    def slot_is_empty(self, area, index, point):
        return self.operator.currency_wars_slot_is_empty(area, index)

    def read_population(self, **kwargs):
        return SimpleNamespace(current=3, capacity=3, evidence="two_population_frames")

    def capture_sample(self, *args, **kwargs):
        return None

    def capture_layout_failure(self, *args, **kwargs):
        return None


@pytest.fixture
def replay(tmp_path, monkeypatch):
    saved = [(character, vars(character).copy())
             for character in {id(c): c for c in Characters.characters.values()}.values()]
    clock = ReplayClock()
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(engine, "CurrencyWarsVision", ReplayVision)
    operator = ReplayOperator(clock)
    task = engine.CurrencyWars(operator, 1, data_dir=tmp_path / "runtime")
    config = {
        "on_field": {"丹恒·饮月": 1},
        "off_field": {"三月七": 1, "千冶·刃": 1},
        "formation": {"stages": [{"name": "recorded_roster", "min_capacity": 0,
            "on_field": ["丹恒·饮月"], "off_field": ["三月七", "千冶·刃"]}]},
    }
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    task.load_strategy(str(path))
    operator.scene = {
        ("on_field", 0): ("丹恒·饮月", 1),
        ("off_field", 0): ("三月七", 1),
        ("off_field", 1): ("千冶·刃", 1),
        ("in_hand", 0): ("藿藿", 1), ("in_hand", 1): ("千冶·刃", 1),
        ("in_hand", 2): ("万敌", 1), ("in_hand", 3): ("万敌", 1),
        ("in_hand", 4): ("不死途", 1), ("in_hand", 5): ("三月七", 1),
        ("in_hand", 6): ("花火", 1),
    }
    # Fixture input: the roster and pending purchase at the entry to preparation.
    for area, observations in task._observations.items():
        for index in range(len(observations)):
            operator.points[getattr(task, area + "_area")[index]] = (area, index)
            name, stars = operator.scene.get((area, index), (None, 0))
            observation = SlotObservation(index, SlotState.KNOWN if name else SlotState.EMPTY,
                Characters.get_character(name) if name else None, bool(name),
                "name_match" if name else "empty_detector",
                stars=None if name == "花火" else stars if name else None)
            observations[index] = observation
            getattr(task, area + "_character")[index] = observation.character
            task._slot_evidence[(area, index)] = (observation, 900.0)
    task._slot_evidence.pop(("in_hand", 6))
    task._dirty_slots.add(("in_hand", 6))
    task._layout_valid = task._backend_identity_confirmed = True
    task._backend_ordinary_slots = tuple(range(6))
    task._confirmed_layout_positions = tuple(task.off_field_area)
    task._bench_dirty = False
    task._placement_pending = False
    task._bench_observed_at = task._field_observed_at = 900.0
    task._purchase_pending_names = {"花火"}
    # A conflicting transaction baseline requires a real complete observation pass.
    task._purchase_scan_baseline = (None, {})
    try:
        yield SimpleNamespace(task=task, operator=operator, clock=clock)
    finally:
        for character, attributes in saved:
            vars(character).update(attributes)


def test_complete_slow_purchase_scan_allows_preparation_without_retry_loop(replay):
    assert Path(engine.__file__).resolve() == (
        RUNTIME_ROOT / "extensions/cw_plus/CurrencyWars.py").resolve()
    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert 60 < replay.clock.value - 1000 < 120
    assert replay.operator.inputs == []


@pytest.mark.parametrize(("failure", "slot"), [
    ("unknown", ("on_field", 0)),
    ("missing_stars", ("off_field", 0)),
    ("unknown", ("in_hand", 6)),
    ("missing_stars", ("in_hand", 6)),
])
def test_slow_scan_cannot_authorize_preparation_with_missing_evidence(replay, failure, slot):
    getattr(replay.operator, failure).add(slot)

    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert replay.operator.inputs == []


def test_unconfirmed_transaction_remains_blocked_without_scanning_or_input(replay):
    replay.task._reward_fast_page_ledger = {"pending": {"name": "花火"}}
    # This is an already active preparation, not permission to reset the pending ledger.
    replay.task._preparation_deadline = replay.clock.value + 300

    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED
    assert result.reason == "purchase_transaction_unconfirmed"
    assert replay.clock.value == 1000
    assert replay.operator.inputs == []


def test_stop_during_slow_scan_is_not_swallowed_by_recovery(replay):
    replay.task._vision.stop_during_layout = True

    with pytest.raises(ThreadStoppedError):
        replay.task.prepare_for_battle()

    assert replay.operator.inputs == []


def seed_empty_field_baseline(replay, evidence="zero_population"):
    task, operator, clock = replay.task, replay.operator, replay.clock
    # Population 0/N established these empty slots before the three deployments.
    # Their visual classifier is ambiguous on the real frame; missing OCR is not emptiness.
    for area, slots in task._observations.items():
        for index, obs in enumerate(slots):
            if area != "in_hand" and obs.state == SlotState.EMPTY:
                slots[index] = SlotObservation(index, SlotState.EMPTY, occupied=False,
                                               evidence=evidence)
                task._slot_evidence.pop((area, index), None)
            elif (area, index) in task._slot_evidence:
                task._slot_evidence[area, index] = (obs, clock.value)
    original_empty = operator.currency_wars_slot_is_empty
    operator.currency_wars_slot_is_empty = lambda area, index: (
        None if area != "in_hand" and original_empty(area, index) else original_empty(area, index))
    task._purchase_scan_baseline = (task._layout_revision,
        {area: list(slots) for area, slots in task._observations.items()})
    # The empty-field baseline is older than the 60 s OCR refresh interval.
    clock.advance(65)


@pytest.mark.parametrize("evidence", ["zero_population", "new_game_empty"])
def test_purchase_preserves_untouched_zero_population_empty_slots(replay, evidence):
    """23:18 replay: one bought character must not erase the proven empty field."""
    seed_empty_field_baseline(replay, evidence)
    task, operator = replay.task, replay.operator

    result = task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert not [slot for slot in operator.slot_clicks
                if slot[0] != "in_hand" and slot not in operator.scene]
    assert task._vision.layout_reads == 0
    assert operator.inputs == []


def test_full_purchase_recovery_uses_fresh_batch_empty_evidence_without_clicking_empty_bench(replay):
    """Even a required full recovery must use the empty cells just seen on two frames."""
    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert not [slot for slot in replay.operator.slot_clicks
                if slot[0] == "in_hand" and slot not in replay.operator.scene]
    assert replay.operator.inputs == []


def test_empty_baseline_does_not_authorize_a_dirty_move_destination(replay):
    seed_empty_field_baseline(replay)
    replay.task._dirty_slots.add(("on_field", 2))

    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert ("on_field", 2) in replay.operator.slot_clicks
    assert replay.operator.inputs == []


def test_dirty_empty_destination_requires_real_evidence_even_without_a_purchase(replay):
    seed_empty_field_baseline(replay)
    replay.task._purchase_pending_names.clear()
    replay.task._purchase_scan_baseline = None
    replay.task._dirty_slots.add(("on_field", 2))

    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert replay.operator.inputs == []
