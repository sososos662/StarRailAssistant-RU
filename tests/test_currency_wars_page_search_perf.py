"""Public layout seam: exact recorded evidence with a bounded resampling workload."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import cv2
from PIL import Image
import pytest

from SRACore.util.errors import ThreadStoppedError
from extensions.cw_plus.paths import CALIBRATION_ROOT
from tests.test_currency_wars_layout_performance import GOLDEN, make_vision

CONTROLS = json.loads((Path(__file__).parent / "fixtures/page_search_perf/golden.json").read_text(encoding="utf-8"))


def test_negative_badge_search_keeps_exact_evidence_without_resampling_impossible_colors(
        tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["no_badge"])
    original_resize = Image.Image.resize
    resampled_pixels = 0

    def measured_resize(image, size, *args, **kwargs):
        nonlocal resampled_pixels
        if tuple(size) == (64, 64):
            resampled_pixels += 64 * 64
        return original_resize(image, size, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "resize", measured_resize)

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    expected = GOLDEN["cases"]["no_badge"]
    assert json.loads(json.dumps(dataclasses.asdict(observation))) == expected["result"]
    assert json.loads(json.dumps(vision.last_layout_diagnostics[
        "layout_support_authentication"])) == expected["support_diagnostics"]
    assert operator.captures == 2
    # Baseline on this fixed recorded row: 108490 RGB grids / 444375040 pixels.
    # A workload budget, not a timing gate on a machine shared by three agents.
    assert resampled_pixels <= 70_000 * 64 * 64


@pytest.mark.parametrize("case", ("recorded_shifted", "support_shifted", "wide_range_negative"))
def test_shifted_support_and_high_contrast_distractors_keep_full_original_evidence(tmp_path, case):
    base = {"recorded_shifted": "recorded", "support_shifted": "reviewed_support_control",
            "wide_range_negative": "no_badge"}[case]
    vision, operator = make_vision(tmp_path, [base])
    original = operator.frames[0]
    frame = Image.new("RGB", original.size, (100, 100, 150))
    frame.paste(original, (0, 0) if case == "wide_range_negative" else (7, 2))
    if case == "wide_range_negative":
        for x, y in GOLDEN["previous_positions"]:
            px, py = round(x * 1920 + 35), round(y * 1080 - 50)
            frame.paste((0, 0, 0), (px - 12, py, px - 10, py + 2))
            frame.paste((255, 255, 255), (px - 10, py, px - 8, py + 2))
    operator.frames = [frame]

    observation = vision.read_backend_layout(CONTROLS["previous_positions"])

    expected = CONTROLS["cases"][case]
    assert json.loads(json.dumps(dataclasses.asdict(observation))) == expected["result"]
    assert json.loads(json.dumps(vision.last_layout_diagnostics)) == expected["diagnostics"]
    assert operator.captures == expected["captures"] == 2


def test_unavailable_color_bound_falls_back_to_full_search_without_changing_evidence(tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["recorded"])

    def unavailable_extrema(image):
        raise ValueError("offline injected extrema failure")

    monkeypatch.setattr(Image.Image, "getextrema", unavailable_extrema)

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    expected = GOLDEN["cases"]["recorded"]
    assert json.loads(json.dumps(dataclasses.asdict(observation))) == expected["result"]
    assert json.loads(json.dumps(vision.last_layout_diagnostics[
        "layout_support_authentication"])) == expected["support_diagnostics"]
    assert operator.captures == 2


def test_stop_during_color_bound_is_not_swallowed_by_exact_fallback(tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["recorded"])

    def stopped_extrema(image):
        raise ThreadStoppedError("停止", "测试停止")

    monkeypatch.setattr(Image.Image, "getextrema", stopped_extrema)

    with pytest.raises(ThreadStoppedError):
        vision.read_backend_layout(GOLDEN["previous_positions"])

    assert operator.captures == 1


def test_cv_failure_cannot_grant_empty_ordinary_or_support_permissions(tmp_path, monkeypatch):
    vision, operator = make_vision(tmp_path, ["recorded"])
    thread_count = cv2.getNumThreads()

    def failed_norm(*args, **kwargs):
        raise cv2.error("offline injected CV failure")

    monkeypatch.setattr(cv2, "norm", failed_norm)

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    assert observation.reason == "backend_support_profile_unavailable"
    assert observation.geometry_valid is True
    assert observation.unknown_protected_slots == tuple(range(6))
    assert observation.ordinary_slots == observation.protected_slots == ()
    assert observation.ordinary_count_confirmed is False and observation.ordinary_count is None
    assert operator.captures == 2
    assert cv2.getNumThreads() == thread_count


def test_negative_color_evidence_cannot_be_reused_on_changed_second_frame(tmp_path):
    vision, operator = make_vision(tmp_path, ["no_badge", "reviewed_support_control"])

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    assert observation.valid is False
    assert observation.reason == "layout_not_stable"
    assert operator.captures == 2


def test_visible_support_outside_detected_row_still_blocks_layout_acceptance(tmp_path):
    vision, operator = make_vision(tmp_path, ["no_badge"])
    frame = operator.frames[0].copy()
    profile = json.loads((CALIBRATION_ROOT / "backend_locked_support.json").read_text(encoding="utf-8"))
    rx, ry = profile["position"]
    sx = round((0.24140625 - rx) * 1920)
    sy = round((0.6199074074074075 - ry) * 1080)
    # An actual reviewed portrait + badge, deliberately without a surrounding
    # card border. It cannot add a slot, but must veto the incomplete row.
    for template in profile["templates"]:
        left, top, _, _ = template["relative_box"]
        with Image.open(CALIBRATION_ROOT / template["path"]) as crop:
            frame.paste(crop.convert("RGB"), (round((rx + left) * 1920) + sx,
                                               round((ry + top) * 1080) + sy))
    operator.frames = [frame]

    observation = vision.read_backend_layout(CONTROLS["previous_positions"])

    expected = CONTROLS["cases"]["exterior_support"]
    assert observation.valid is False and observation.geometry_valid is False
    assert observation.reason == "backend_support_row_incomplete"
    assert json.loads(json.dumps(dataclasses.asdict(observation))) == expected["result"]
    assert json.loads(json.dumps(vision.last_layout_diagnostics)) == expected["diagnostics"]
    assert operator.captures == expected["captures"] == 1
