"""PERF-002: full public evidence and deterministic resampling budget."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from PIL import Image
import cv2
import pytest

from SRACore.util.errors import ThreadStoppedError
from tests.test_currency_wars_layout_performance import GOLDEN, make_vision
from tests.perf002_projection_controls import make_projection_control

FULL_GOLDEN = json.loads((Path(__file__).parent / "fixtures/layout_performance/perf002_full_golden.json")
                         .read_text(encoding="utf-8"))
PROJECTION_GOLDEN = json.loads((Path(__file__).parent / "fixtures/layout_performance/perf002_projection_golden.json")
                               .read_text(encoding="utf-8"))


def normalized(value):
    return json.loads(json.dumps(value))


def test_recorded_layout_keeps_full_golden_with_fewer_resampled_candidates(tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["recorded"])
    resize = Image.Image.resize
    resizes = 0

    def counted_resize(image, *args, **kwargs):
        nonlocal resizes
        resizes += 1
        return resize(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "resize", counted_resize)
    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    expected = FULL_GOLDEN["cases"]["recorded"]
    assert normalized(dataclasses.asdict(observation)) == expected["result"]
    assert normalized(vision.last_layout_diagnostics) == expected["diagnostics"]
    assert operator.captures == expected["captures"] == 2
    assert resizes <= expected["work"]["resize"] * 0.7


@pytest.mark.parametrize("case", [case for case in FULL_GOLDEN["cases"] if case != "recorded"])
def test_full_recorded_and_changed_frame_evidence_is_unchanged(tmp_path, case):
    vision, operator = make_vision(tmp_path, case.split("__"))

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    expected = FULL_GOLDEN["cases"][case]
    assert normalized(dataclasses.asdict(observation)) == expected["result"]
    assert normalized(vision.last_layout_diagnostics) == expected["diagnostics"]
    assert operator.captures == expected["captures"] == 2


def test_unavailable_local_bound_keeps_original_full_search_evidence(tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["recorded"])

    def unavailable(*args, **kwargs):
        raise cv2.error("offline injected local bound failure")

    monkeypatch.setattr(cv2, "erode", unavailable)
    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    expected = FULL_GOLDEN["cases"]["recorded"]
    assert normalized(dataclasses.asdict(observation)) == expected["result"]
    assert normalized(vision.last_layout_diagnostics) == expected["diagnostics"]
    assert operator.captures == 2


def test_stop_during_local_bound_cannot_be_swallowed_by_fallback(tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["recorded"])

    def stopped(*args, **kwargs):
        raise ThreadStoppedError("停止", "测试停止")

    monkeypatch.setattr(cv2, "erode", stopped)

    with pytest.raises(ThreadStoppedError):
        vision.read_backend_layout(GOLDEN["previous_positions"])
    assert operator.captures == 1


def test_stop_after_second_fresh_capture_cannot_accept_first_frame(tmp_path):
    vision, operator = make_vision(tmp_path, ["reviewed_support_control", "recorded"])

    def stop_check():
        if operator.captures >= 2:
            raise ThreadStoppedError("停止", "测试停止")

    vision.stop_check = stop_check

    with pytest.raises(ThreadStoppedError):
        vision.read_backend_layout(GOLDEN["previous_positions"])
    assert operator.captures == 2


@pytest.mark.parametrize("case", list(PROJECTION_GOLDEN["cases"]))
def test_search_boundaries_and_recovery_keep_full_baseline_evidence(tmp_path, case):
    recover = case == "recover_changed_identity"
    if recover:
        vision, operator = make_vision(tmp_path, ["recorded", "reviewed_support_control"])
    else:
        vision, operator = make_projection_control(tmp_path, case)

    observation = vision.read_backend_layout(GOLDEN["previous_positions"], recover=recover)

    expected = PROJECTION_GOLDEN["cases"][case]
    assert normalized(dataclasses.asdict(observation)) == expected["result"]
    assert normalized(vision.last_layout_diagnostics) == expected["diagnostics"]
    assert operator.captures == expected["captures"]
