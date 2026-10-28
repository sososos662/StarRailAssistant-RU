"""Public shop replay with a layout-broken logical keyboard and fake Win32 boundary."""
import ctypes
from types import SimpleNamespace

import pytest
from PIL import Image

from tests.test_currency_wars_slow_preparation import ReplayClock, ReplayOperator, ReplayVision, engine
from extensions.cw_plus.logic import SlotObservation, SlotState
from SRACore.util.errors import ThreadStoppedError


class ShopReplayOperator(ReplayOperator):
    type = "Local"

    def __init__(self, clock):
        super().__init__(clock)
        self.shop_open = False
        self.level = 6
        self.progress = 34
        self.gold = 20
        self.native_events = []
        self.game_accepts = True
        self.active = True
        self.minimum_hold = 0

    def is_window_active(self):
        return self.active

    def screenshot(self):
        frame = self.frame.copy()
        if self.shop_open:
            frame.paste(Image.open(engine.CWIMG.FOLD).convert("RGB"), (1550, 960))
        return frame

    def click_point(self, x, y, **kwargs):
        if (x, y) == (0.8438, 0.8481) or (x, y) == (1620, 915):
            self.shop_open = True
        return super().click_point(x, y, **kwargs)

    def click_box(self, box, after_sleep=0, **kwargs):
        if box.source == engine.CWIMG.FOLD:
            self.shop_open = False
        self.sleep(after_sleep)
        return True

    def press_key(self, key, **kwargs):
        self.inputs.append(("logical_key", key))
        if self.type == "Browser" and key == "f":
            self.gold -= 4
            self.level = 7
            self.progress = 2
        return True  # Recorded behavior with VkKeyScan('f'/'d') == -1: no game change.

    def ocr(self, *, from_x=None, **kwargs):
        text = (str(self.gold) if from_x == 0.815 else "4" if from_x == 0.158 else
                "2" if from_x == 0.846 else "备战阶段 2-5" if from_x in (0.105, 0.205) else "")
        return [([[5, 10], [28, 10], [28, 31], [5, 31]], text, 0.999)] if text else []

    def send_input(self, count, inputs, size):
        assert count == len(inputs)
        assert size == 40  # Windows x64 INPUT includes the largest (mouse) union member.
        events = [(event.type, event.ki.wVk, event.ki.wScan, event.ki.dwFlags) for event in inputs]
        assert all(event[0:2] == (1, 0) and event[3] in (8, 10) for event in events)
        self.native_events.append(events)
        for event in events:
            if event[3] == 8:
                self.held_since = self.clock.value
                continue
            held = self.clock.value - self.held_since
            if not self.game_accepts or held < self.minimum_hold:
                continue
            if event[2] == 0x21:  # Physical F, independent of RU/EN.
                self.gold -= 4
                self.progress += 4
                if self.progress >= 36:
                    self.level += 1
                    self.progress -= 36
            elif event[2] == 0x20:  # Physical D.
                self.gold -= 2
        return count


class ShopReplayVision(ReplayVision):
    def operator_ocr(self, **kwargs):
        return self.operator.ocr(**kwargs)

    def read_level(self, parser):
        return SimpleNamespace(level=self.operator.level, evidence="recorded_level",
            reason="matched_level_label", raw_text=f"购买经验 | Lv.{self.operator.level} | {self.operator.progress}/36")

    def slot_is_empty_batch(self, area, positions):
        return {i: True for i in range(len(positions))}


@pytest.fixture
def shop_replay(tmp_path, monkeypatch, request):
    clock = ReplayClock()
    operator = ShopReplayOperator(clock)
    operator.type = getattr(request, "param", "Local")
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(engine, "CurrencyWarsVision", ShopReplayVision)
    monkeypatch.setattr(ctypes.windll.user32, "SendInput", operator.send_input)
    task = engine.CurrencyWars(operator, 1, data_dir=tmp_path)
    task.is_overclock = True
    task.min_level = task.mid_level = 7
    task.min_coins = 0
    task.shopping_budget.update(actions=3, experiences=1, refreshes=0)
    task._layout_valid = task._backend_identity_confirmed = True
    task._backend_ordinary_slots = tuple(range(6))
    task._bench_dirty = task._placement_pending = False
    for area, observations in task._observations.items():
        for i in range(len(observations)):
            obs = SlotObservation(i, SlotState.EMPTY, occupied=False, evidence="two_empty_frames")
            observations[i] = obs
            task._slot_evidence[area, i] = (obs, clock.value)
    task._field_observed_at = task._bench_observed_at = clock.value
    return SimpleNamespace(task=task, operator=operator)


def test_shop_buys_experience_with_layout_independent_physical_key(shop_replay):
    task, operator = shop_replay.task, shop_replay.operator

    result = task.shopping()

    assert operator.gold == 16, result
    assert operator.level == 7
    assert result.reason != "experience_no_progress"
    assert operator.inputs == []


def test_physical_key_is_held_long_enough_for_a_game_frame(shop_replay):
    task, operator = shop_replay.task, shop_replay.operator
    operator.minimum_hold = 0.03

    result = task.shopping()

    assert operator.gold == 16, result


def test_shop_refreshes_with_physical_key_and_observes_payment(shop_replay):
    task, operator = shop_replay.task, shop_replay.operator
    operator.level = 7
    task.shopping_budget.update(refreshes=1)

    result = task.shopping()

    assert operator.gold == 18, result
    assert result.refreshes == 1
    assert result.reason != "refresh_no_progress"
    assert len(operator.native_events) == 2
    assert operator.native_events[0][0][2] == 0x20
    assert operator.inputs == []


def test_accepted_os_input_without_game_progress_is_not_replayed_or_treated_as_paid(shop_replay):
    task, operator = shop_replay.task, shop_replay.operator
    operator.game_accepts = False

    result = task.shopping()

    assert result.reason == "experience_no_progress"
    assert operator.gold == 20 and operator.level == 6
    assert len(operator.native_events) == 2


@pytest.mark.parametrize("fault", ["os_rejects", "inactive_window"])
def test_failed_input_is_bounded_and_does_not_spend(shop_replay, monkeypatch, fault):
    task, operator = shop_replay.task, shop_replay.operator
    if fault == "os_rejects":
        monkeypatch.setattr(ctypes.windll.user32, "SendInput", lambda *args: 0)
    else:
        operator.active = False

    result = task.shopping()

    assert result.reason == "experience_click_failed"
    assert operator.gold == 20
    assert operator.native_events == []


def test_failed_release_retries_only_key_up_without_repeating_purchase(shop_replay, monkeypatch):
    task, operator = shop_replay.task, shop_replay.operator
    sent = []

    def partial_send(count, events, size):
        sent.append([event.ki.dwFlags for event in events])
        return 0 if len(sent) == 2 else 1

    monkeypatch.setattr(ctypes.windll.user32, "SendInput", partial_send)
    result = task.shopping()

    assert result.reason == "experience_click_failed"
    assert sent == [[8], [10], [10]]
    assert operator.gold == 20


def test_stop_after_os_input_does_not_send_another_action(shop_replay, monkeypatch):
    task, operator = shop_replay.task, shop_replay.operator
    sent = []

    def stop_send(count, events, size):
        sent.append([event.ki.dwFlags for event in events])
        operator.stop_event.set()
        return count

    monkeypatch.setattr(ctypes.windll.user32, "SendInput", stop_send)
    with pytest.raises(ThreadStoppedError):
        task.shopping()

    assert sent == [[8], [10]]


@pytest.mark.parametrize("shop_replay", ["Browser"], indirect=True)
def test_cloud_operator_retains_its_original_input_path(shop_replay):
    task, operator = shop_replay.task, shop_replay.operator

    task.shopping()

    assert operator.gold == 16 and operator.level == 7
    assert operator.inputs == [("logical_key", "f")]
    assert operator.native_events == []
