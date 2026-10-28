"""Public preparation must not expand a purchase scan while its own OCR consumes time."""
from dataclasses import replace

from tests.test_currency_wars_slow_preparation import replay
from extensions.cw_plus.preparation import Readiness


def seed_transaction(replay, *, age):
    task, clock = replay.task, replay.clock
    for key, (observation, _) in list(task._slot_evidence.items()):
        task._slot_evidence[key] = (observation, clock.value - age)
    task._purchase_scan_baseline = (task._layout_revision,
        {area: tuple(slots) for area, slots in task._observations.items()})
    # A copy of the fielded character was bought; its observed star count must be re-read.
    task._observations["on_field"][0] = replace(task._observations["on_field"][0], stars=None)
    task._slot_evidence.pop(("on_field", 0), None)
    task._purchase_pending_names.add("丹恒·饮月")


def test_purchase_scan_does_not_age_unaffected_slots_into_its_own_read_plan(replay, record_property):
    seed_transaction(replay, age=55.5)
    started = replay.clock.value

    result = replay.task.prepare_for_battle()

    record_property("virtual_seconds", replay.clock.value - started)
    record_property("field_panel_clicks", sum(slot[0] != "in_hand" for slot in replay.operator.slot_clicks))
    assert result.state == Readiness.READY, result
    assert [slot for slot in replay.operator.slot_clicks if slot[0] != "in_hand"] == [("on_field", 0)]
    assert replay.operator.inputs == []


def test_expired_purchase_scan_checks_empty_field_slots_as_a_batch_without_opening_panels(replay, record_property):
    seed_transaction(replay, age=61)
    started = replay.clock.value

    result = replay.task.prepare_for_battle()

    record_property("virtual_seconds", replay.clock.value - started)
    record_property("field_panel_clicks", sum(slot[0] != "in_hand" for slot in replay.operator.slot_clicks))
    assert result.state == Readiness.READY, result
    assert [slot for slot in replay.operator.slot_clicks if slot[0] != "in_hand"] == [
        ("on_field", 0), ("off_field", 0), ("off_field", 1)]
    assert replay.operator.inputs == []


def test_already_expired_unaffected_character_cannot_be_reused_without_reading_identity(replay):
    seed_transaction(replay, age=61)
    replay.operator.unknown.add(("off_field", 0))

    result = replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert ("off_field", 0) in replay.operator.slot_clicks
    assert replay.operator.inputs == []
