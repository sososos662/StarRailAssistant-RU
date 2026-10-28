"""Public preparation with real empty-emblem recognition on recorded pixels."""
import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tests.test_currency_wars_slow_preparation import replay, ReplayVision
from extensions.cw_plus.vision import CurrencyWarsVision
from extensions.cw_plus.paths import CALIBRATION_ROOT
from extensions.cw_plus.logic import SlotObservation, SlotState
from extensions.cw_plus.preparation import Readiness

FIXTURES = Path(__file__).parent / "fixtures/frontend_empty"
META = json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8"))["round_1_2"]
BOUNDS = tuple(round((META["position"][i % 2] + offset) * (1920, 1080)[i % 2])
               for i, offset in enumerate(META["relative_box"]))


class RecordedFieldVision(ReplayVision):
    def __init__(self, operator, tmp_path):
        super().__init__(operator)
        self.visual = CurrencyWarsVision(operator, CALIBRATION_ROOT / "profile.json",
                                        tmp_path, max_samples=0)

    def slot_is_empty(self, area, index, point):
        if (area, index) == ("on_field", 2):
            return self.visual.slot_is_empty(area, index, point)
        return super().slot_is_empty(area, index, point)

    def read_empty_slots(self, area, positions):
        answers = super().read_empty_slots(area, positions)
        if area == "on_field" and 2 in answers:
            answers[2] = self.visual.read_empty_slots(area, {2: positions[2]})[2]
        return answers


def prepare_recorded_slot(replay, tmp_path, crop):
    task, operator = replay.task, replay.operator
    operator.frame.paste(crop, BOUNDS[:2])
    original_empty = operator.currency_wars_slot_is_empty
    operator.currency_wars_slot_is_empty = lambda area, index: (
        None if (area, index) == ("on_field", 2) else original_empty(area, index))
    task._vision = RecordedFieldVision(operator, tmp_path / "samples")
    task._purchase_pending_names.clear()
    task._purchase_scan_baseline = None
    task._observations["on_field"][2] = SlotObservation(2, SlotState.UNKNOWN,
                                                       evidence="investment_reward_unknown")
    task._slot_evidence.pop(("on_field", 2), None)
    task._dirty_slots.add(("on_field", 2))
    return task


@pytest.mark.parametrize("case", ["round_1_1", "round_1_2", "earlier_run"])
def test_recorded_empty_frontend_slot_allows_preparation_after_unknown_reward(replay, tmp_path, case):
    with Image.open(FIXTURES / (case + ".png")) as image:
        task = prepare_recorded_slot(replay, tmp_path, image.convert("RGB"))

    result = task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert replay.operator.inputs == []


def test_fresh_two_frame_empty_frontend_does_not_need_a_panel_click_or_ocr(replay, tmp_path):
    with Image.open(FIXTURES / "round_1_2.png") as image:
        task = prepare_recorded_slot(replay, tmp_path, image.convert("RGB"))

    result = task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert ("on_field", 2) not in replay.operator.slot_clicks
    assert replay.operator.inputs == []


@pytest.mark.parametrize("control", ["blank", "gradient", "star", "noise", "occupied",
                                     "top_hidden", "middle_hidden", "bottom_hidden"])
def test_incomplete_or_missing_empty_emblem_cannot_authorize_preparation(replay, tmp_path, control):
    with Image.open(FIXTURES / "round_1_2.png") as image:
        crop = image.convert("RGB")
    color = crop.getpixel((1, crop.height // 2))
    if control == "occupied":
        with Image.open(CALIBRATION_ROOT / "field-occupied-0-on_field-0.png") as portrait:
            crop = portrait.convert("RGB").resize(crop.size)
    elif control in {"blank", "gradient", "star", "noise"}:
        crop = Image.new("RGB", crop.size, color)
        draw = ImageDraw.Draw(crop)
        if control == "gradient":
            for y in range(crop.height):
                draw.line((0, y, crop.width, y), fill=tuple(min(255, c + y // 8) for c in color))
        elif control == "star":
            draw.regular_polygon((crop.width // 2, crop.height // 2, 8), 5, fill=(160, 160, 190))
        elif control == "noise":
            rng = random.Random(527)
            crop.putdata([tuple(min(255, c + 15) for c in color) if rng.random() < .25 else color
                          for _ in range(crop.width * crop.height)])
    else:
        third = crop.height // 3
        y = {"top_hidden": 0, "middle_hidden": third, "bottom_hidden": 2 * third}[control]
        ImageDraw.Draw(crop).rectangle((0, y, crop.width, y + third + 2), fill=color)
    task = prepare_recorded_slot(replay, tmp_path, crop)

    result = task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert replay.operator.inputs == []


def test_disagreeing_live_frames_cannot_authorize_empty_frontend_slot(replay, tmp_path):
    with Image.open(FIXTURES / "round_1_2.png") as image:
        empty = image.convert("RGB")
    task = prepare_recorded_slot(replay, tmp_path, empty)
    with Image.open(CALIBRATION_ROOT / "field-occupied-0-on_field-0.png") as image:
        occupied = image.convert("RGB").resize(empty.size)
    screenshots = 0

    def changing_frame():
        nonlocal screenshots
        frame = replay.operator.frame.copy()
        frame.paste(empty if screenshots % 2 else occupied, BOUNDS[:2])
        screenshots += 1
        return frame

    replay.operator.screenshot = changing_frame

    result = task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert replay.operator.inputs == []
