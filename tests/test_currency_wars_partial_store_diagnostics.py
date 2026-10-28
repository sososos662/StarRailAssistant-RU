"""Public shopping diagnostics with real parsing/quotas and replayed OS boundaries."""
from __future__ import annotations

from copy import deepcopy
import json

from PIL import Image
import pytest

from tests.test_currency_wars_shop_navigation_perf import navigation  # noqa: F401
from extensions.cw_plus.logic import ActionResult


def replay_partial(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    operator.offer_names[2] = "未收录角色"
    task._vision.max_samples = 12
    task._vision.begin_sample_scope("diag001", "partial", critical_reserve=0)
    frames, store_frames = [], []
    screenshot, ocr_engine = operator.screenshot, operator.ocr_engine

    def capture(**kwargs):
        frame = screenshot(**kwargs)
        # Every capture is distinguishable, even after the shop closes.
        frame.putpixel((0, 1079), (operator.captures, 71, 93))
        frames.append(frame.copy())
        return frame

    def read(image, **kwargs):
        rows = ocr_engine(image, **kwargs)
        if image.size == (1325, 54):
            store_frames.append(frames[-1].copy())
            if image.mode == "RGB":
                rows = deepcopy(rows)
                rows[4] = (rows[4][0], "Uncatalogued", rows[4][2])
        return rows

    monkeypatch.setattr(operator, "screenshot", capture)
    monkeypatch.setattr(operator, "ocr_engine", read)
    return frames, store_frames


def test_partial_store_saves_the_decision_frame_roi_both_ocr_passes_and_slots(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    frames, store_frames = replay_partial(navigation, monkeypatch)

    result = task.shopping()

    assert result.result == ActionResult.INDETERMINATE and result.reason == "partial_store", result
    assert result.attempted_purchases == result.confirmed_purchases == 0
    assert operator.purchases == operator.inputs == [] and operator.gold == 20
    assert operator.shop_open is False and operator.toggle_events == ["close"]
    samples = list(task._vision.sample_dir.glob("*_partial_store.png"))
    assert len(samples) == 1
    sample = samples[0]
    assert len(store_frames) == 2  # Gray + RGB, not an extra diagnostic OCR.
    with Image.open(sample) as saved:
        assert saved.mode == "RGB" and saved.size == (1920, 1080)
        assert saved.tobytes() == store_frames[0].tobytes() == store_frames[1].tobytes()
        assert saved.tobytes() != frames[-1].tobytes()
    metadata = json.loads(sample.with_suffix(".json").read_text(encoding="utf-8"))
    scan = metadata["store_scan"]
    assert scan["source"] == "decision_frame"
    assert scan["roi"] == [.19, .26, .88, .31]
    assert scan["crop_box"] == [365, 281, 1690, 335]
    assert scan["state"] == "ready" and scan["reason"] == "partial_unrecognized_cards"
    assert scan["selected_method"] == "gray"
    gray, rgb = scan["attempts"]
    assert gray["method"] == "gray" and rgb["method"] == "rgb"
    assert len(gray["rows"]) == len(rgb["rows"]) == 10
    assert gray["rows"][4] == {"text": "未收录角色", "score": .999,
                                "box": [[671, 10], [711, 10], [711, 31], [671, 31]]}
    assert rgb["rows"][4]["text"] == "Uncatalogued"
    assert gray["unknown_names"] == ["未收录角色"]
    assert rgb["unknown_names"] == ["Uncatalogued"]
    for attempt in scan["attempts"]:
        assert attempt["state"] == "ready" and attempt["reason"] == "partial_unrecognized_cards"
        assert [slot["slot_index"] for slot in attempt["slots"]] == [0, 1, 3, 4]
        assert all(slot["name"] == "藿藿" and slot["price"] == 2 for slot in attempt["slots"])
    images = {entry["role"]: task._vision.sample_dir / entry["file"]
              for entry in metadata["evidence_images"]}
    assert set(images) == {"store_roi_rgb", "store_roi_gray"}
    for role, mode in (("store_roi_rgb", "RGB"), ("store_roi_gray", "L")):
        with Image.open(images[role]) as saved:
            assert saved.mode == mode
            assert saved.tobytes() == store_frames[0].crop((365, 281, 1690, 335)).convert(mode).tobytes()
    assert sample.with_suffix(".json").stat().st_size <= 8192


def test_long_unrecognized_ocr_still_leaves_a_bounded_partial_sample(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    replay_partial(navigation, monkeypatch)
    operator.offer_names = ["藿藿"] + ["未" * 120] * 4
    store_rows = operator.store_rows

    def noisy_rows():
        rows = store_rows()
        return rows[:2] + [row for index, row in enumerate(rows[2:])
                           for _ in range(3 if index % 2 == 0 else 1)]

    monkeypatch.setattr(operator, "store_rows", noisy_rows)

    result = task.shopping()

    assert result.reason == "partial_store" and result.confirmed_purchases == 0
    samples = list(task._vision.sample_dir.glob("*_partial_store.png"))
    assert len(samples) == 1
    sidecar = samples[0].with_suffix(".json")
    assert sidecar.stat().st_size <= 8192
    scan = json.loads(sidecar.read_text(encoding="utf-8"))["store_scan"]
    assert scan["metadata_truncated"] is True
    assert len(scan["attempts"]) == 2
    assert all(len(attempt["rows"]) == 18 for attempt in scan["attempts"])
    assert all(attempt["slots"][0]["slot_index"] == 0 for attempt in scan["attempts"])
    assert operator.inputs == operator.purchases == [] and operator.gold == 20


@pytest.mark.parametrize("quota", ["disabled", "reason_zero", "run_exhausted"])
def test_partial_store_respects_existing_sampling_quotas(navigation, monkeypatch, quota):
    task, operator = navigation.task, navigation.operator
    replay_partial(navigation, monkeypatch)
    if quota == "disabled":
        task._vision.max_samples = 0
    elif quota == "reason_zero":
        task._vision.begin_sample_scope("diag001", quota, critical_reserve=0,
                                       reason_quotas={"partial_store": 0})
    else:
        # One real public sample consumes the existing total quota.
        task._vision.max_samples = 1
        assert task._vision.capture_sample("earlier_issue", frame=operator.frame) is not None

    result = task.shopping()

    assert result.reason == "partial_store" and result.result == ActionResult.INDETERMINATE
    assert not list(task._vision.sample_dir.rglob("*partial_store*"))
    assert operator.inputs == operator.purchases == [] and operator.gold == 20
    assert operator.toggle_events == ["close"] and operator.shop_open is False


def test_fully_unknown_store_keeps_its_original_diagnostic_reason(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    _, store_frames = replay_partial(navigation, monkeypatch)
    operator.offer_names = ["未收录角色"] * 5
    operator.scene.update({("store", index): ("unknown", 1) for index in range(5)})

    result = task.shopping()

    assert result.reason == "unknown" and result.result == ActionResult.INDETERMINATE
    samples = list(task._vision.sample_dir.glob("*_unknown_store.png"))
    assert len(samples) == 1 and not list(task._vision.sample_dir.glob("*_partial_store.png"))
    with Image.open(samples[0]) as saved:
        assert saved.tobytes() == store_frames[0].tobytes()
    assert operator.inputs == operator.purchases == [] and operator.gold == 20
    assert operator.shop_open is False


def test_color_recovery_of_a_partial_scan_keeps_the_initial_evidence(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    replay_partial(navigation, monkeypatch)
    read = operator.ocr_engine

    def recovered(image, **kwargs):
        rows = read(image, **kwargs)
        if image.mode == "RGB" and image.size == (1325, 54):
            rows[4] = (rows[4][0], "藿藿", rows[4][2])
        return rows

    monkeypatch.setattr(operator, "ocr_engine", recovered)

    result = task.shopping()

    assert result.result == ActionResult.CONFIRMED and result.reason == "coin_reserve"
    samples = list(task._vision.sample_dir.glob("*_partial_store.json"))
    assert len(samples) == 1
    scan = json.loads(samples[0].read_text(encoding="utf-8"))["store_scan"]
    assert scan["selected_method"] == "rgb" and scan["reason"] == ""
    assert scan["attempts"][0]["unknown_names"] == ["未收录角色"]
    assert scan["attempts"][1]["unknown_names"] == []
    assert len(scan["attempts"][1]["slots"]) == 5
    assert operator.purchases == operator.inputs == [] and operator.gold == 20


def test_partial_color_attempt_does_not_change_an_unknown_gray_decision_or_use_two_reasons(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    replay_partial(navigation, monkeypatch)
    operator.offer_names = ["未收录角色"] * 5
    operator.scene.update({("store", index): ("unknown", 1) for index in range(5)})
    read = operator.ocr_engine

    def partial_color(image, **kwargs):
        rows = read(image, **kwargs)
        if image.mode == "RGB" and image.size == (1325, 54):
            rows[0] = (rows[0][0], "藿藿", rows[0][2])
        return rows

    monkeypatch.setattr(operator, "ocr_engine", partial_color)

    result = task.shopping()

    assert result.result == ActionResult.INDETERMINATE and result.reason == "unknown"
    samples = list(task._vision.sample_dir.glob("*_unknown_store.json"))
    assert len(samples) == 1 and not list(task._vision.sample_dir.glob("*_partial_store.png"))
    scan = json.loads(samples[0].read_text(encoding="utf-8"))["store_scan"]
    assert scan["state"] == "unknown" and scan["selected_method"] == "gray"
    assert scan["attempts"][1]["state"] == "ready"
    assert scan["attempts"][1]["reason"] == "partial_unrecognized_cards"
    assert operator.purchases == operator.inputs == [] and operator.gold == 20


def test_one_partial_event_and_its_roi_images_consume_only_one_total_sample(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    replay_partial(navigation, monkeypatch)
    task._vision.max_samples = 2
    task._vision.begin_sample_scope("diag001", "single-event", critical_reserve=0,
                                   reason_quotas={"unknown_coins_geometry": 0})

    result = task.shopping()

    assert result.reason == "partial_store"
    assert len(list(task._vision.sample_dir.glob("*_partial_store.png"))) == 1
    assert task._vision.capture_sample("remaining_quota", frame=operator.frame) is not None
    assert task._vision.capture_sample("no_quota_left", frame=operator.frame) is None
    assert task._vision.last_sample_reason == "run_quota_exhausted"


def test_stop_during_color_ocr_propagates_without_a_diagnostic_capture_or_spending(navigation, monkeypatch):
    from SRACore.util.errors import ThreadStoppedError

    task, operator = navigation.task, navigation.operator
    replay_partial(navigation, monkeypatch)
    read = operator.ocr_engine

    def interrupted(image, **kwargs):
        rows = read(image, **kwargs)
        if image.mode == "RGB" and image.size == (1325, 54):
            operator.stop_event.set()
        return rows

    monkeypatch.setattr(operator, "ocr_engine", interrupted)

    with pytest.raises(ThreadStoppedError):
        task.shopping()

    assert operator.purchases == operator.inputs == [] and operator.gold == 20
    assert not list(task._vision.sample_dir.glob("*_partial_store.png"))
