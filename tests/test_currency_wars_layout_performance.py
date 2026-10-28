"""Public layout compatibility and opt-in timing gate on a sanitized recorded row."""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest
from PIL import Image

RUNTIME_ROOT = Path(os.environ.get("SRA_CW_RUNTIME_ROOT", Path(__file__).resolve().parents[1]))
if os.environ.get("SRA_CW_RUNTIME_ROOT"):
    sys.path.insert(0, str(RUNTIME_ROOT))

from extensions.cw_plus.paths import CALIBRATION_ROOT
from extensions.cw_plus.vision import CurrencyWarsVision
from SRACore.util.errors import ThreadStoppedError

FIXTURES = Path(__file__).parent / "fixtures/layout_performance"
GOLDEN = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))


class LayoutFrames:
    window_context = SimpleNamespace(width=1920, height=1080)

    def __init__(self, names):
        self.frames = []
        for name in names:
            image = Image.new("RGB", (1920, 1080), (100, 100, 150))
            with Image.open(FIXTURES / (name + ".png")) as row:
                image.paste(row.convert("RGB"), (192, 560))
            self.frames.append(image)
        self.captures = 0

    def screenshot(self):
        image = self.frames[min(self.captures, len(self.frames) - 1)].copy()
        self.captures += 1
        return image

    def sleep(self, seconds):
        pass  # Benchmark measures recognition, not the unchanged inter-frame sleep.


def make_vision(tmp_path, names, **kwargs):
    operator = LayoutFrames(names)
    vision = CurrencyWarsVision(operator, CALIBRATION_ROOT / "profile.json", tmp_path,
                               max_samples=0, **kwargs)
    return vision, operator


@pytest.mark.parametrize("case", list(GOLDEN["cases"]))
def test_layout_and_all_support_diagnostics_match_captured_reference(tmp_path, case):
    vision, operator = make_vision(tmp_path, [case])

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    expected = GOLDEN["cases"][case]
    assert json.loads(json.dumps(dataclasses.asdict(observation))) == expected["result"]
    actual_diagnostics = json.loads(json.dumps(vision.last_layout_diagnostics["layout_support_authentication"]))
    assert actual_diagnostics == expected["support_diagnostics"]
    assert operator.captures == expected["capture_count"] == 2


def test_changed_second_frame_cannot_reuse_first_frame_support_identity(tmp_path):
    vision, operator = make_vision(tmp_path, ["recorded", "reviewed_support_control"])

    observation = vision.read_backend_layout(GOLDEN["previous_positions"])

    assert observation.valid is False
    assert observation.reason == "layout_not_stable"
    assert operator.captures == 2


def test_stop_during_layout_search_is_propagated(tmp_path):
    checks = 0

    def stop_check():
        nonlocal checks
        checks += 1
        if checks >= 100:
            raise ThreadStoppedError("停止", "测试停止")

    vision, operator = make_vision(tmp_path, ["recorded"], stop_check=stop_check)

    with pytest.raises(ThreadStoppedError):
        vision.read_backend_layout(GOLDEN["previous_positions"])

    assert operator.captures == 1


@pytest.mark.skipif(os.environ.get("SRA_CW_PERF") != "1", reason="explicit local timing gate, not a CI latency assertion")
def test_recorded_layout_is_at_least_30_percent_faster_than_captured_baseline(tmp_path):
    vision, _ = make_vision(tmp_path, ["recorded"])

    started = time.perf_counter()
    result = vision.read_backend_layout(GOLDEN["previous_positions"])
    elapsed = time.perf_counter() - started

    assert result.valid
    assert elapsed < GOLDEN["cases"]["recorded"]["seconds_before"] * 0.7, f"{elapsed:.3f}s"
