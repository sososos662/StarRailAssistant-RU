"""PERF-001: public shopping only; work counters are performance instrumentation."""
import sys

import cv2
import numpy as np
import pytest
from PIL import ImageDraw

from extensions.cw_plus.logic import ActionResult
from tests.test_currency_wars_shop_navigation_perf import navigation, ocr_row  # noqa: F401
from tests.test_currency_wars_slow_preparation import engine
from extensions.cw_plus.unicode_templates import load_template


def test_shop_geometry_has_bounded_python_pixel_work(navigation):
    gold_calls = 0

    def count_work(frame, event, arg):
        nonlocal gold_calls
        if event == "call" and frame.f_code.co_name == "gold" and (
                frame.f_code.co_filename.endswith("equipment_choice.py")):
            gold_calls += 1

    previous = sys.getprofile()
    sys.setprofile(count_work)
    try:
        result = navigation.task.shopping()
    finally:
        sys.setprofile(previous)

    assert result.result == ActionResult.CONFIRMED
    assert navigation.operator.toggle_events == ["close"]
    assert navigation.operator.purchases == navigation.operator.inputs == []
    assert navigation.operator.captures >= 2
    # Baseline: 1,043,450 Python pixel calls. Count work, never shared-CPU seconds.
    assert gold_calls < 10_000, gold_calls


def test_page_search_keeps_all_checks_without_full_screen_integer_index_grids(navigation, monkeypatch):
    integer_grid_elements = 0
    template_calls = 0
    original_arange, original_match = np.arange, cv2.matchTemplate

    def measured_arange(*args, **kwargs):
        nonlocal integer_grid_elements
        values = original_arange(*args, **kwargs)
        if values.size >= 1_000_000:
            integer_grid_elements += values.size
        return values

    def measured_match(*args, **kwargs):
        nonlocal template_calls
        template_calls += 1
        return original_match(*args, **kwargs)

    monkeypatch.setattr(np, "arange", measured_arange)
    monkeypatch.setattr(cv2, "matchTemplate", measured_match)

    result = navigation.task.shopping()

    assert result.result == ActionResult.CONFIRMED
    assert navigation.operator.toggle_events == ["close"]
    assert navigation.operator.captures == 10
    assert template_calls == 102  # No removed searches, no cross-frame reuse.
    assert integer_grid_elements < 50_000_000, integer_grid_elements


def install_probability_panel(operator, *, fault=None):
    """A screen/OCR/input recording, not a replacement classifier."""
    capture, click = operator.screenshot, operator.click_point
    state = {"visible": True, "closes": []}

    def screenshot(**kwargs):
        frame = capture(**kwargs)
        if state["visible"]:
            draw = ImageDraw.Draw(frame)
            draw.rectangle((374, 238, 1527, 300), fill=(20, 50, 210))
            draw.rectangle((394, 325, 1526, 820), fill=(20, 20, 20))
            draw.rectangle((390, 246, 450, 261), fill="white")
            for x, color in ((835, (30, 180, 30)), (1025, (30, 60, 210)),
                             (1217, (160, 50, 210)), (1405, (210, 140, 40))):
                draw.rectangle((x, 335, x + 35, 352), fill=color)
            if fault != "cross_missing":
                draw.line((1484, 251, 1516, 283), fill="white", width=3)
                draw.line((1516, 251, 1484, 283), fill="white", width=3)
            if fault == "panel_missing":
                draw.rectangle((394, 325, 1526, 820), fill="white")
            if fault:
                # Unauthenticated standalone panel: no underlying page evidence.
                # The legacy classifier does not promise to identify every damaged
                # dialog exposing independently valid preparation buttons.
                draw.rectangle((0, 0, 500, 180), fill=(15, 25, 35))
                draw.rectangle((1550, 960, 1620, 1010), fill=(15, 25, 35))
            operator.visible_history[-1] = ("overlay", operator.action_epoch, operator.clock.value)
            operator.register_ocr(frame, "overlay")
            title = frame.crop((374, 238, 874, 300))
            rows = [ocr_row("商店刷新概率", width=180, score=.90 if fault == "low_title" else .999)]
            operator._ocr_records[operator.image_key(title)] = rows
        return frame

    def click_point(x, y, **kwargs):
        if state["visible"]:
            assert (x, y) == pytest.approx((1500 / 1920, 267 / 1080))
            state["closes"].append((x, y))
            state["visible"] = False
            operator.action_epoch += 1
            operator.sleep(kwargs.get("after_sleep", 0))
            return True
        return click(x, y, **kwargs)

    operator.screenshot, operator.click_point = screenshot, click_point
    return state


def test_probability_panel_closes_only_after_full_authentication_with_bounded_pixel_work(navigation):
    state = install_probability_panel(navigation.operator)
    pixel_predicates = 0

    def count_work(frame, event, arg):
        nonlocal pixel_predicates
        if event == "call" and frame.f_code.co_name == "<lambda>" and (
                frame.f_code.co_filename.endswith("shop_overlay.py")):
            pixel_predicates += 1

    previous = sys.getprofile()
    sys.setprofile(count_work)
    try:
        result = navigation.task.shopping()
    finally:
        sys.setprofile(previous)

    assert result.result == ActionResult.CONFIRMED, result
    assert len(state["closes"]) == 1
    assert navigation.operator.toggle_events == ["close"]
    assert navigation.operator.purchases == navigation.operator.inputs == []
    assert pixel_predicates < 1_000, pixel_predicates


@pytest.mark.parametrize("fault", ["cross_missing", "panel_missing", "low_title"])
def test_incomplete_probability_evidence_never_authorizes_a_close(navigation, fault):
    state = install_probability_panel(navigation.operator, fault=fault)
    navigation.task.SHOP_STATE_TIMEOUT = 1.2

    result = navigation.task.shopping()

    assert result.result == ActionResult.INDETERMINATE
    assert state["closes"] == []
    assert navigation.operator.toggle_events == navigation.operator.inputs == []
    assert navigation.operator.store_reads == 0


def install_equipment_cards(operator, *, fault=None):
    capture, click = operator.screenshot, operator.click_point
    state = {"visible": True, "selections": [], "frames": 0}

    def screenshot(**kwargs):
        frame = capture(**kwargs)
        if state["visible"]:
            state["frames"] += 1
            draw = ImageDraw.Draw(frame)
            for index, x in enumerate((679, 970, 1260)):
                if fault == "partial" and index == 0:
                    continue
                draw.rectangle((x, 115, x + 258, 292), outline=(210, 170, 70), width=2)
                if fault == "two_pixel_gaps":
                    for dx in (40, 120, 200):
                        draw.rectangle((x + dx, 114, x + dx + 1, 118), fill=(15, 25, 35))
                        draw.rectangle((x + dx, 289, x + dx + 1, 294), fill=(15, 25, 35))
                if fault == "three_pixel_gaps":
                    draw.rectangle((x + 120, 114, x + 122, 118), fill=(15, 25, 35))
                    draw.rectangle((x + 120, 289, x + 122, 294), fill=(15, 25, 35))
                if fault == "sides_missing":
                    draw.rectangle((x - 2, 120, x + 3, 286), fill=(15, 25, 35))
                    draw.rectangle((x + 255, 120, x + 261, 286), fill=(15, 25, 35))
            if fault == "changed_second" and state["frames"] >= 3:
                draw.rectangle((1262, 120, 1515, 286), fill=(190, 80, 200))
            if fault in {"three_pixel_gaps", "sides_missing"}:
                draw.rectangle((0, 0, 500, 110), fill=(15, 25, 35))
                draw.rectangle((1550, 960, 1620, 1010), fill=(15, 25, 35))
            draw.rectangle((1025, 25, 1100, 32), fill="white")
            operator.visible_history[-1] = ("overlay", operator.action_epoch, operator.clock.value)
            operator.register_ocr(frame, "overlay")
            title = frame.crop((1018, 15, 1200, 105))
            rows = [ocr_row("选择装备", 5, 5, 120), ocr_row("请选择1个", 5, 40, 120)]
            if fault == "low_title":
                rows = [ocr_row("选择装备", 5, 5, 120, .90)]
            operator._ocr_records[operator.image_key(title)] = rows
        return frame

    def click_point(x, y, **kwargs):
        if state["visible"]:
            assert (x, y) == pytest.approx((1389 / 1920, 203.5 / 1080))
            state["selections"].append((x, y))
            state["visible"] = False
            operator.action_epoch += 1
            operator.sleep(kwargs.get("after_sleep", 0))
            return True
        return click(x, y, **kwargs)

    operator.screenshot, operator.click_point = screenshot, click_point
    return state


@pytest.mark.parametrize("fault", [None, "two_pixel_gaps"])
def test_three_actual_equipment_frames_allow_only_one_right_card_input(navigation, fault):
    state = install_equipment_cards(navigation.operator, fault=fault)

    navigation.task.shopping()

    assert len(state["selections"]) == 1
    assert state["frames"] == 3  # Two page observations plus fresh content confirmation.
    assert navigation.operator.purchases == navigation.operator.inputs == []


@pytest.mark.parametrize("fault", ["partial", "low_title", "changed_second", "three_pixel_gaps", "sides_missing"])
def test_equipment_unknown_title_partial_or_changed_confirmation_blocks_input(navigation, fault):
    state = install_equipment_cards(navigation.operator, fault=fault)
    navigation.task.SHOP_STATE_TIMEOUT = 1.2

    result = navigation.task.shopping()

    assert result.result == ActionResult.INDETERMINATE
    assert state["selections"] == []
    assert navigation.operator.toggle_events == navigation.operator.inputs == []
    assert navigation.operator.store_reads == 0


@pytest.mark.parametrize("grayscale", [True, False])
def test_page_match_uses_first_above_threshold_not_the_later_best_match(navigation, monkeypatch, grayscale):
    import pyscreeze

    operator = navigation.operator
    operator.tm_confidence = .95
    monkeypatch.setattr(pyscreeze, "GRAYSCALE_DEFAULT", grayscale)
    capture, click = operator.screenshot, operator.click_box
    selected = []
    earlier = load_template(engine.CWIMG.FOLD).convert("RGB")
    ImageDraw.Draw(earlier).rectangle((3, 3, 5, 5), fill="white")

    def screenshot(**kwargs):
        frame = capture(**kwargs)
        if operator.visible_history[-1][0] == "open":
            frame.paste(earlier, (100, 500))
            operator.register_ocr(frame, "open")
        return frame

    def click_box(box, **kwargs):
        selected.append((box.left, box.top))
        return click(box, **kwargs)

    operator.screenshot, operator.click_box = screenshot, click_box

    result = navigation.task.shopping()

    assert result.result == ActionResult.CONFIRMED
    assert selected == [(100, 500)]
    assert operator.purchases == operator.inputs == []


def test_stop_before_equipment_content_confirmation_cannot_select_a_card(navigation):
    from SRACore.util.errors import ThreadStoppedError

    state = install_equipment_cards(navigation.operator)
    navigation.operator.stop_on_capture = 3

    with pytest.raises(ThreadStoppedError):
        navigation.task.shopping()

    assert state["selections"] == []
    assert navigation.operator.toggle_events == navigation.operator.inputs == []


def test_partial_personality_stays_unknown_and_cannot_be_bought(navigation):
    navigation.operator.offer_names[1] = "UnknownPerson"

    result = navigation.task.shopping()

    assert result.result == ActionResult.INDETERMINATE
    assert result.reason == "partial_store"
    assert navigation.operator.purchases == navigation.operator.inputs == []
    assert navigation.operator.toggle_events == ["close"]
