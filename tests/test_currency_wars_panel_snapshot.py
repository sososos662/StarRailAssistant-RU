"""Real template matching and host OCR semantics at the public preparation boundary."""
from dataclasses import replace
from types import MethodType, SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from SRACore.operators.ioperator import IOperator
from SRACore.util.errors import ThreadStoppedError
from extensions.cw_plus.vision import CurrencyWarsVision
from extensions.cw_plus.paths import CALIBRATION_ROOT
from extensions.cw_plus.preparation import Readiness
from extensions.cw_plus.formation import RoleProvider, RoleRequirement
from tests.test_currency_wars_slow_preparation import replay, ReplayVision, engine


class PanelVision(ReplayVision):
    def __init__(self, operator, tmp_path):
        super().__init__(operator)
        self.reader = CurrencyWarsVision(operator, CALIBRATION_ROOT / "profile.json", tmp_path, max_samples=0)

    def operator_ocr(self, **kwargs):
        return self.reader.operator_ocr(**kwargs)

    def _engine_ocr(self, image, **kwargs):
        return self.reader._engine_ocr(image, **kwargs)


@pytest.fixture
def panel_replay(replay, tmp_path):
    task, operator = replay.task, replay.operator
    operator.type = "Local"
    operator.ocr_confidence = .7
    operator.is_save_ocr_image = False
    operator.ocr = MethodType(IOperator.ocr, operator)
    operator.panel_captures = 0
    operator.panel_score = .999
    task._vision = PanelVision(operator, tmp_path / "samples")
    star = Image.open(engine.CWIMG.STAR).convert("RGB")

    def screenshot(*, from_x=None, from_y=None, to_x=None, to_y=None, **kwargs):
        operator.clock.advance(.5)  # The unchanged host screenshot wait.
        frame = operator.frame.copy()
        if operator.selected == ("on_field", 0):
            operator.panel_captures += 1
            _, stars = operator.scene[operator.selected]
            for n in range(stars):
                frame.paste(star, (1596 + n * 19, 163))
        if from_x is not None:
            frame = frame.crop((from_x * 1920, from_y * 1080, to_x * 1920, to_y * 1080))
        return frame

    def ocr_engine(image, **kwargs):
        name = operator.scene.get(operator.selected, (None, 0))[0]
        return SimpleNamespace(txts=[name] if name else None,
            boxes=np.array([[[1, 1], [100, 1], [100, 40], [1, 40]]]),
            scores=[operator.panel_score])

    previous_locate = operator.locate_all

    def locate_all(*args, **kwargs):
        # Original host/wrapper performs a separate capture and a post-match pause.
        screenshot()
        operator.clock.advance(.5)
        return previous_locate(*args, **kwargs)

    operator.screenshot, operator.ocr_engine, operator.locate_all = screenshot, ocr_engine, locate_all
    task._purchase_pending_names.clear()
    task._purchase_scan_baseline = None
    task._observations["on_field"][0] = replace(task._observations["on_field"][0], stars=None)
    task._slot_evidence.pop(("on_field", 0), None)
    task._dirty_slots.add(("on_field", 0))
    return replay


def require_panel_stars(task, stars):
    role = RoleRequirement(candidates=("丹恒·饮月",), on_missing="block")
    task.formation_config = replace(task.formation_config,
        roles={"panel": (RoleProvider("丹恒·饮月", ("on_field",), stars),)},
        stages=tuple(replace(stage, role_requirements={"panel": role})
                     for stage in task.formation_config.stages))


@pytest.mark.parametrize("stars", [1, 2, 3])
def test_name_and_stars_share_one_fresh_panel_capture(panel_replay, stars, record_property):
    name, _ = panel_replay.operator.scene["on_field", 0]
    panel_replay.operator.scene["on_field", 0] = (name, stars)
    require_panel_stars(panel_replay.task, stars)
    started = panel_replay.clock.value
    result = panel_replay.task.prepare_for_battle()

    record_property("virtual_seconds", panel_replay.clock.value - started)
    record_property("panel_captures", panel_replay.operator.panel_captures)
    assert result.state == Readiness.READY, result
    assert panel_replay.operator.panel_captures == 1
    assert panel_replay.operator.inputs == []


@pytest.mark.parametrize("stars", [1, 2])
def test_shared_panel_does_not_promote_stars_above_the_observed_count(panel_replay, stars):
    name, _ = panel_replay.operator.scene["on_field", 0]
    panel_replay.operator.scene["on_field", 0] = (name, stars)
    require_panel_stars(panel_replay.task, stars + 1)

    result = panel_replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert panel_replay.operator.inputs == []


@pytest.mark.parametrize("score", [.7, .69])
def test_panel_snapshot_retains_strict_host_name_confidence(panel_replay, score):
    panel_replay.operator.panel_score = score

    result = panel_replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert panel_replay.operator.inputs == []


def test_panel_without_confirmed_stars_cannot_authorize_preparation(panel_replay):
    name, _ = panel_replay.operator.scene["on_field", 0]
    panel_replay.operator.scene["on_field", 0] = (name, 0)
    require_panel_stars(panel_replay.task, 1)

    result = panel_replay.task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert panel_replay.operator.inputs == []


@pytest.mark.parametrize("mode", ["cloud", "custom_ocr"])
def test_nonstandard_panel_reader_keeps_its_original_capture_path(panel_replay, mode):
    operator = panel_replay.operator
    if mode == "cloud":
        operator.type = "Browser"
    else:
        host_ocr = operator.ocr
        operator.ocr = lambda **kwargs: host_ocr(**kwargs)

    result = panel_replay.task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert operator.panel_captures == 2
    assert operator.inputs == []


def test_stop_after_panel_capture_is_not_swallowed(panel_replay):
    operator = panel_replay.operator
    capture = operator.screenshot

    def stop_on_panel(**kwargs):
        frame = capture(**kwargs)
        if operator.selected == ("on_field", 0):
            operator.stop_event.set()
        return frame

    operator.screenshot = stop_on_panel
    with pytest.raises(ThreadStoppedError):
        panel_replay.task.prepare_for_battle()
    assert operator.inputs == []


def test_failed_shared_ocr_probe_falls_back_without_spending_a_recovery(panel_replay):
    operator = panel_replay.operator
    read = operator.ocr_engine
    calls = 0

    def transient_failure(image, **kwargs):
        nonlocal calls
        if operator.selected == ("on_field", 0) and image.size == (202, 61):
            calls += 1
            if calls == 1:
                raise RuntimeError("recorded transient OCR error")
        return read(image, **kwargs)

    operator.ocr_engine = transient_failure
    result = panel_replay.task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert result.recoveries == 0
    assert operator.inputs == []
