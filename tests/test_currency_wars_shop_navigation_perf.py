"""Public shopping replay: real page/vision logic, fake screen/OCR/input/time only."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest
from PIL import ImageDraw

from tests.test_currency_wars_slow_preparation import ReplayClock, ReplayOperator, engine
from extensions.cw_plus.characters import Characters
from extensions.cw_plus.logic import ActionResult, SlotObservation, SlotState
from extensions.cw_plus.unicode_templates import load_template
from SRACore.util.errors import ThreadStoppedError


def ocr_row(text, x=5, y=10, width=28, score=.999):
    return ([[x, y], [x + width, y], [x + width, y + 21], [x, y + 21]], text, score)


class NavigationOperator(ReplayOperator):
    """Only this replay boundary sends input; it never calls an OS operator."""
    type = "Browser"

    def __init__(self, clock):
        super().__init__(clock)
        self.shop_open = True
        self.gold = 20
        self.level = 7
        self.progress = 0
        self.toggle_events = []
        self.captures = 0
        self.store_reads = 0
        self.waits = []
        self.visible_history = []
        self.forced_pages = deque()
        self.after_open_pages = ()
        self.after_close_pages = ()
        self.overlay = None
        self.drop_open = self.drop_close = self.drop_purchase = self.drop_experience = False
        self.stop_on_capture = None
        self.action_epoch = 0
        self.offer_names = ["藿藿"] * 5
        self.offer_price = 2
        self.purchases = []
        self.open_capture_counts = []
        self.store_authority = []
        self.reward_selections = 0
        self._ocr_records = {}

    def sleep(self, seconds):
        self.waits.append(seconds)
        super().sleep(seconds)

    @staticmethod
    def image_key(image):
        return image.mode, image.size, hashlib.sha256(image.tobytes()).digest()

    def store_rows(self):
        rows = []
        for index, name in enumerate(self.offer_names):
            if name is None:
                continue
            x = round(((.25, .40, .55, .68, .80)[index] - .19) * 1920) - 20
            rows.append(ocr_row(name, x, width=40))
            if self.offer_price is not None:
                rows.append(ocr_row(str(self.offer_price), x + 65, width=15))
        return rows

    def register_ocr(self, frame, page):
        # Pixel-keyed OCR recordings are the only perception fake. The real
        # page classifier, geometry, price parser and vision cache remain active.
        rows = [
            ((.19, .26, .88, .31), self.store_rows() if page == "open" else []),
            ((.115, .780, .195, .905), [ocr_row(f"购买经验 | Lv.{self.level} | {self.progress}/40")]),
            ((.815, .824, .89, .881), [ocr_row(str(self.gold), 30, 15, 20)] if self.gold is not None else []),
            ((.815, .818, .89, .890), [ocr_row(str(self.gold), 30, 21, 20)] if self.gold is not None else []),
            ((.158, .900, .185, .938), [ocr_row("4", 12, 10, 12)]),
            ((.846, .475, .870, .515), [ocr_row("2", 12, 10, 12)]),
        ]
        for roi, answers in rows:
            box = tuple(round(value * frame.size[index % 2]) for index, value in enumerate(roi))
            crop = frame.crop(box)
            for mode in ("RGB", "L"):
                self._ocr_records[self.image_key(crop.convert(mode))] = answers

    def screenshot(self, **kwargs):
        self.captures += 1
        self.clock.advance(.05)
        frame = self.frame.copy()
        page = self.forced_pages.popleft() if self.forced_pages else (
            "open" if self.shop_open else "closed")
        if page == "open" or page == "overlay" and self.shop_open:
            frame.paste(load_template(engine.CWIMG.FOLD).convert("RGB"), (1550, 960))
            draw = ImageDraw.Draw(frame)
            draw.text((1595, 905), str(self.gold), fill="white")
            draw.text((230, 865), f"Lv.{self.level} {self.progress}/40", fill="white")
            draw.text((315, 985), "4", fill="white")
            draw.text((1636, 523), "2", fill="white")
            draw.text((400, 290), str(self.offer_names), fill="white")
        overlay = self.overlay if self.overlay is not None else (
            engine.CWIMG.SELECT_SIMPLE_EQUIPMENT if page == "overlay" else None)
        if overlay is not None:
            frame.paste(load_template(overlay).convert("RGB"), (750, 400))
            page = "overlay"
        self.visible_history.append((page, self.action_epoch, self.clock.value))
        self.register_ocr(frame, page)
        if self.captures == self.stop_on_capture:
            self.stop_event.set()
        return frame

    def ocr_engine(self, image, **kwargs):
        if image.size == (1325, 54):
            self.store_reads += 1
            self.store_authority.append(tuple(self.visible_history[-2:]))
        return deepcopy(self._ocr_records.get(self.image_key(image), []))

    def click_point(self, x, y, *, after_sleep=0, **kwargs):
        if (x, y) == (.5, .3) and self.overlay == engine.CWIMG.SELECT_INVEST_STRATEGY:
            self.reward_selections += 1
            self.action_epoch += 1
            self.overlay = None
            self.shop_open = False
            self.sleep(after_sleep)
            return True
        assert self.visible_history[-1][0] != "overlay", "An overlay cannot authorize shop input"
        self.action_epoch += 1
        if (x, y) == (.8438, .8481):
            self.toggle_events.append("open")
            self.open_capture_counts.append(self.captures)
            self.shop_open |= not self.drop_open
            self.forced_pages.extend(self.after_open_pages)
        else:
            assert y == .18 and x in (.25, .40, .55, .68, .80), "Unexpected non-shop input"
            assert self.shop_open
            slot = (.25, .40, .55, .68, .80).index(x)
            self.purchases.append(slot)
            if not self.drop_purchase and self.gold >= (self.offer_price or 2):
                self.offer_names[slot] = None
                self.gold -= self.offer_price or 2
        self.sleep(after_sleep)
        return True

    def click_box(self, box, *, after_sleep=0, **kwargs):
        assert box.source == engine.CWIMG.FOLD
        assert self.visible_history[-1][0] == "open"
        self.action_epoch += 1
        self.toggle_events.append("close")
        if not self.drop_close:
            self.shop_open = False
        self.forced_pages.extend(self.after_close_pages)
        self.sleep(after_sleep)
        return True

    def ocr(self, *, from_x=None, **kwargs):
        # The legacy operator OCR boundary captures a new screen for each call.
        self.screenshot()
        if from_x == .19:
            self.store_reads += 1
            return self.store_rows() if self.shop_open else []
        text = (str(self.gold) if from_x == .815 else "4" if from_x == .158 else
                "2" if from_x == .846 else "备战阶段 2-5" if from_x in (.105, .205) else
                f"购买经验 | Lv.{self.level} | {self.progress}/40" if from_x == .115 else "")
        return [ocr_row(text)] if text else []

    def press_key(self, key, **kwargs):
        assert key == "f", "No reroll, sale or battle input is allowed in this replay"
        self.inputs.append(("key", key))
        self.action_epoch += 1
        if self.gold >= 4 and not self.drop_experience:
            self.gold -= 4
            self.progress += 4
        return True


@pytest.fixture
def navigation(tmp_path, monkeypatch):
    saved = [(character, vars(character).copy())
             for character in {id(c): c for c in Characters.characters.values()}.values()]
    clock = ReplayClock()
    operator = NavigationOperator(clock)
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=clock.monotonic))
    task = engine.CurrencyWars(operator, 1, data_dir=tmp_path)
    task._vision.max_samples = 0
    task.min_level = task.mid_level = 7
    task.shopping_budget.update(actions=3, experiences=1, refreshes=0)
    # Recorded input state: this preparation's round and complete board were read.
    task._preparation_round = (2, 5)
    task._preparation_round_context = (task._cycle_number, task._last_completed_battle_id,
                                       task._preparation_departure_confirmed)
    task._layout_valid = task._backend_identity_confirmed = True
    task._backend_ordinary_slots = tuple(range(6))
    task._bench_dirty = task._placement_pending = False
    for area, observations in task._observations.items():
        for index in range(len(observations)):
            obs = SlotObservation(index, SlotState.EMPTY, occupied=False, evidence="two_empty_frames")
            observations[index] = obs
            task._slot_evidence[area, index] = (obs, clock.value)
    task._field_observed_at = task._bench_observed_at = clock.value
    try:
        yield SimpleNamespace(task=task, operator=operator, clock=clock)
    finally:
        for character, attributes in saved:
            vars(character).update(attributes)


def test_current_round_and_complete_board_do_not_close_and_reopen_an_already_open_shop(navigation):
    result = navigation.task.shopping()

    assert result.result == ActionResult.CONFIRMED, result
    assert navigation.operator.store_reads > 0  # Available cards are really read.
    assert navigation.operator.toggle_events == ["close"]  # Only the final cleanup.


def test_a_new_shopping_attempt_rereads_live_prices_instead_of_reusing_old_free_buttons(navigation):
    task, operator = navigation.task, navigation.operator
    task._coin_shop_open = True
    task._coin_action_costs.update(experience=0, refresh=0)
    task.min_level = 8
    operator.gold = 2  # Not enough for the real, visible four-coin experience button.

    result = task.shopping()

    assert result.reason == "low_coins", result
    assert operator.inputs == []
    assert operator.gold == 2


def test_a_closed_shop_needs_only_the_fresh_opening_attempt_not_an_extra_close_validation(navigation):
    task, operator = navigation.task, navigation.operator
    operator.shop_open = False

    result = task.shopping()

    assert result.result == ActionResult.CONFIRMED, result
    assert operator.open_capture_counts == [1]
    assert operator.toggle_events == ["open", "close"]
    assert operator.store_reads > 0 and operator.gold == 20


@pytest.mark.parametrize("fault", ["round_not_read", "round_context_changed", "dirty_board", "unknown_board"])
def test_a_required_round_or_board_check_keeps_the_original_closed_page_path(navigation, fault):
    task, operator = navigation.task, navigation.operator
    if fault == "round_not_read":
        task._preparation_round = None
    elif fault == "round_context_changed":
        task._preparation_round_context = None
    elif fault == "dirty_board":
        task._dirty_slots.add(("on_field", 0))
    else:
        task._observations["on_field"][0] = SlotObservation(0, SlotState.UNKNOWN)

    result = task.shopping()

    assert result.result == ActionResult.CONFIRMED, result
    assert operator.toggle_events == ["close", "open", "close"]


@pytest.mark.parametrize("pages", [("closed",), ("open", "closed"), ("closed", "open", "closed")])
def test_stale_or_opposite_frames_cannot_retoggle_or_authorize_a_purchase(navigation, pages):
    task, operator = navigation.task, navigation.operator
    operator.shop_open = False
    operator.after_open_pages = pages

    result = task.shopping()

    assert result.result == ActionResult.CONFIRMED, result
    assert operator.toggle_events == ["open", "close"]
    assert operator.store_authority
    assert all(len(frames) == 2 and all(frame[:2] == ("open", 1) for frame in frames)
               and frames[0][2] < frames[1][2] for frames in operator.store_authority)


def test_one_late_open_frame_after_closing_does_not_trigger_a_second_toggle(navigation):
    task, operator = navigation.task, navigation.operator
    operator.after_close_pages = ("open",)

    result = task.shopping()

    assert result.result == ActionResult.CONFIRMED, result
    assert operator.toggle_events == ["close"]
    assert operator.shop_open is False


def test_a_dropped_open_input_is_not_replayed_or_reported_as_shopping_success(navigation):
    task, operator = navigation.task, navigation.operator
    operator.shop_open = False
    operator.drop_open = True
    task.SHOP_STATE_TIMEOUT = 1.2

    result = task.shopping()

    assert result.result == ActionResult.INDETERMINATE and result.reason == "shop_not_open", result
    assert operator.toggle_events == ["open"]
    assert operator.store_reads == 0 and operator.gold == 20


@pytest.mark.parametrize("overlay", [engine.CWIMG.SELECT_SIMPLE_EQUIPMENT,
                                    engine.CWIMG.CONFIRM_SELECTION,
                                    engine.CWIMG.SETTLE, engine.CWIMG.CONTINUE, engine.IMG.Q])
def test_blocking_reward_unknown_selection_settlement_or_combat_cannot_expose_shop_controls(navigation, overlay):
    task, operator = navigation.task, navigation.operator
    operator.overlay = overlay
    task.SHOP_STATE_TIMEOUT = 1.2

    result = task.shopping()

    assert result.result == ActionResult.INDETERMINATE, result
    assert operator.toggle_events == [] and operator.inputs == []
    assert operator.store_reads == 0 and operator.gold == 20


def test_a_transient_overlay_is_waited_out_before_two_new_shop_frames(navigation):
    task, operator = navigation.task, navigation.operator
    operator.forced_pages.extend(("open", "overlay"))

    result = task.shopping()

    assert result.result == ActionResult.CONFIRMED, result
    assert operator.visible_history[1][0] == "overlay"
    assert operator.toggle_events == ["close"]
    assert all(all(frame[:2] == ("open", 0) for frame in frames)
               and frames[0][2] < frames[1][2] for frames in operator.store_authority)


def test_stop_on_the_second_fresh_shop_frame_propagates_without_spending(navigation):
    task, operator = navigation.task, navigation.operator
    operator.stop_on_capture = 2

    with pytest.raises(ThreadStoppedError):
        task.shopping()

    assert operator.store_reads == 0 and operator.toggle_events == [] and operator.inputs == []


def test_expired_preparation_still_closes_the_shop_without_reading_or_spending(navigation):
    task, operator = navigation.task, navigation.operator
    task._preparation_deadline = navigation.clock.value - 1

    result = task.shopping()

    assert result.reason == "preparation_budget_finished", result
    assert operator.toggle_events == ["close"] and operator.shop_open is False
    assert operator.store_reads == 0 and operator.inputs == []


def test_expiry_between_cached_decisions_still_runs_bounded_shop_cleanup(navigation, monkeypatch):
    task, operator, clock = navigation.task, navigation.operator, navigation.clock

    def progressing_time():
        now = clock.value
        clock.advance(.02)
        return now

    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=progressing_time))
    task._preparation_deadline = clock.value + .01

    result = task.shopping()

    assert result.reason == "preparation_budget_finished", result
    assert operator.toggle_events == ["close"] and operator.shop_open is False
    assert operator.store_reads == 0 and operator.inputs == []


def test_old_zero_coin_cache_does_not_skip_reading_and_buying_a_real_available_target(navigation):
    task, operator = navigation.task, navigation.operator
    task._last_coins_read = 0
    task.main_c = "三月七"
    task.strategy_characters = {"三月七": 1}
    operator.offer_names[0] = "三月七"

    result = task.shopping()

    assert result.confirmed_purchases == 1 and result.reason == "main_c_placement", result
    assert operator.purchases == [0] and operator.gold == 18
    assert operator.offer_names[0] is None and operator.shop_open is False


def test_unknown_live_coins_do_not_become_an_old_cached_balance(navigation):
    task, operator = navigation.task, navigation.operator
    task._last_coins_read = 20
    task.min_level = 8
    operator.gold = None

    result = task.shopping()

    assert result.result == ActionResult.INDETERMINATE and result.reason == "unknown_coins", result
    assert operator.inputs == [] and operator.purchases == [] and operator.shop_open is False


def test_an_unaccepted_unpriced_purchase_is_not_replayed_or_confirmed(navigation):
    task, operator = navigation.task, navigation.operator
    task.main_c = "三月七"
    task.strategy_characters = {"三月七": 1}
    operator.offer_names[0] = "三月七"
    operator.offer_price = None
    operator.drop_purchase = True

    result = task.shopping()

    assert result.result == ActionResult.INDETERMINATE and result.confirmed_purchases == 0, result
    assert result.reason == "purchase_not_confirmed"
    assert operator.purchases == [0] and operator.gold == 20 and operator.offer_names[0] == "三月七"


def test_an_unaccepted_experience_input_needs_real_progress_not_the_navigation_result(navigation):
    task, operator = navigation.task, navigation.operator
    task.min_level = 8
    operator.drop_experience = True

    result = task.shopping()

    assert result.reason == "experience_no_progress", result
    assert operator.inputs == [("key", "f")] and operator.gold == 20 and operator.progress == 0


def test_a_reward_during_opening_cannot_use_the_pre_reward_board_to_buy_a_target(navigation):
    task, operator = navigation.task, navigation.operator
    task.main_c = "三月七"
    task.strategy_characters = {"三月七": 1}
    operator.offer_names[0] = "三月七"
    operator.overlay = engine.CWIMG.SELECT_INVEST_STRATEGY

    result = task.shopping()

    assert operator.reward_selections == 1
    assert result.result == ActionResult.INDETERMINATE, result
    assert operator.purchases == [] and operator.inputs == [] and operator.gold == 20
