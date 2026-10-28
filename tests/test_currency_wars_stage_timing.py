"""Diagnostics at the agreed shopping boundary; no game or OS input."""
import json
from types import SimpleNamespace

import pytest
from loguru import logger

from tests.test_currency_wars_shop_navigation_perf import navigation  # noqa: F401
from SRACore.operators import ioperator
from SRACore.operators.operator import Operator
from SRACore.util.errors import ThreadStoppedError
from tests.test_currency_wars_slow_preparation import replay  # noqa: F401
from extensions.cw_plus.unicode_templates import UnicodeTemplateOperator


def timing_records(messages):
    return [json.loads(message.split("CW_TIMING ", 1)[1])
            for message in messages if message.startswith("CW_TIMING ")]


@pytest.mark.parametrize("wait_mode", ["operator", "interruptible"])
def test_shopping_reports_bounded_exclusive_capture_wait_cpu_ocr_and_navigation(navigation, monkeypatch, wait_mode, tmp_path):
    import cv2

    clock, operator = navigation.clock, navigation.operator
    # External time, capture and OCR boundaries only; engine logic stays real.
    monkeypatch.setattr(ioperator, "time", SimpleNamespace(sleep=clock.advance))
    original_sleep = operator.sleep
    original_capture = operator.screenshot
    original_ocr = operator.ocr_engine
    original_match = cv2.matchTemplate
    original_click = operator.click_box
    interruptible = UnicodeTemplateOperator(operator)
    monkeypatch.setattr(operator.stop_event, "wait", clock.advance)

    def sleep(seconds):
        operator.waits.append(seconds)
        if wait_mode == "interruptible":
            interruptible.sleep(seconds)
        else:
            ioperator.IOperator.sleep(seconds)

    def screenshot(**kwargs):
        # Exercise the actual operator capture/wait envelope, replacing only
        # window discovery and capture bytes. No Win32 or screen IO occurs.
        return Operator.screenshot(operator, **kwargs)

    def ocr(image, **kwargs):
        clock.advance(.125)
        return original_ocr(image, **kwargs)

    def match(*args, **kwargs):
        clock.advance(.002)
        return original_match(*args, **kwargs)

    def click(*args, **kwargs):
        clock.advance(.03)
        return original_click(*args, **kwargs)

    monkeypatch.setattr(operator, "sleep", sleep)
    monkeypatch.setattr(operator, "get_win_region", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(operator, "_screenshot", lambda *args: original_capture(), raising=False)
    monkeypatch.setattr(operator, "_hwnd", 0, raising=False)
    monkeypatch.setattr(operator, "screenshot_background", False, raising=False)
    monkeypatch.setattr(operator, "screenshot", screenshot)
    monkeypatch.setattr(operator, "ocr_engine", ocr)
    monkeypatch.setattr(cv2, "matchTemplate", match)
    monkeypatch.setattr(operator, "click_box", click)
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]))
    try:
        result = navigation.task.shopping()
    finally:
        logger.remove(sink)
        operator.sleep = original_sleep

    assert result.reason == "coin_reserve"
    assert operator.toggle_events == ["close"]
    records = timing_records(messages)
    assert len(records) == 1
    record = records[0]
    assert record["scope"] == "shopping"
    assert record["capture_source"] == "injected_operator"
    assert record["accounting"] == "exclusive_wall_and_process"
    stages = record["stages"]
    assert set(stages) == {"capture", "wait", "cpu_pages", "cpu_geometry", "ocr",
                           "transition", "recovery", "other"}
    assert stages["capture"]["wall_s"] == pytest.approx(.05 * operator.captures)
    assert stages["wait"]["wall_s"] == pytest.approx(sum(operator.waits))
    for name in ("cpu_pages", "ocr", "transition"):
        assert stages[name]["wall_s"] > 0
    assert sum(stage["wall_s"] for stage in stages.values()) <= record["wall_s"] + 1e-5
    assert sum(stage["process_s"] for stage in stages.values()) <= record["process_s"] + 1e-5
    assert len(json.dumps(record)) < 2048
    (tmp_path / "timing.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def test_shopping_recovery_is_one_exclusive_record_and_never_confirms_unknown_inventory(replay, tmp_path):
    replay.task._deferred_purchase_cycle = {"receipts": {"花火": 1}, "before": {"花火": 0}}
    replay.operator.unknown.add(("in_hand", 6))
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]))
    try:
        result = replay.task.shopping()
    finally:
        logger.remove(sink)
    assert result.reason == "purchase_recheck_unknown"
    assert replay.operator.inputs == []
    records = timing_records(messages)
    assert len(records) == 1
    record = records[0]
    assert record["stages"]["recovery"]["wall_s"] > 0
    assert sum(stage["wall_s"] for stage in record["stages"].values()) <= record["wall_s"] + 1e-5
    (tmp_path / "timing.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def test_shopping_stop_propagates_and_the_next_call_gets_a_new_record(navigation):
    operator, task = navigation.operator, navigation.task
    operator.stop_on_capture = 2
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]))
    try:
        with pytest.raises(ThreadStoppedError):
            task.shopping()
        assert operator.toggle_events == []
        operator.stop_event.clear()
        operator.stop_on_capture = None
        result = task.shopping()
    finally:
        logger.remove(sink)
    assert result.reason == "coin_reserve"
    records = timing_records(messages)
    assert len(records) == 2
    assert [record["outcome"] for record in records] == ["raised", "returned"]
    assert all(len(json.dumps(record)) < 2048 for record in records)
