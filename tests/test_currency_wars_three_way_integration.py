"""Public layout -> preparation -> shopping composition; all input remains replay-only."""
import pytest

from tests.test_currency_wars_slow_preparation import engine
from tests.test_currency_wars_formation_order import formation_order, scene_roster
from tests.test_currency_wars_layout_performance import GOLDEN, make_vision
from tests.test_currency_wars_shop_navigation_perf import NavigationOperator
from extensions.cw_plus.logic import ActionResult
from extensions.cw_plus.paths import CALIBRATION_ROOT
from extensions.cw_plus.preparation import Readiness
from extensions.cw_plus.vision import CurrencyWarsVision


@pytest.mark.parametrize("reward_on_open", [False, True])
def test_confirmed_layout_and_shorter_preparation_keep_fresh_shop_authority(
        formation_order, tmp_path, reward_on_open):
    task, operator, clock = formation_order.task, formation_order.operator, formation_order.clock
    reader, frames = make_vision(tmp_path / "layout", ["no_badge"])

    layout = reader.read_backend_layout(GOLDEN["previous_positions"])

    assert layout.valid and layout.geometry_valid and layout.ordinary_count_confirmed
    assert frames.captures == 2
    # Feed the public layout result into the recorded preparation input. Names
    # are replay perception, not an OCR claim about the independent layout crop.
    task.off_field_area = list(layout.positions)
    task._confirmed_layout_positions = tuple(layout.positions)
    task._backend_ordinary_slots = tuple(layout.ordinary_slots)
    task._layout_valid = layout.valid
    task._backend_identity_confirmed = layout.ordinary_count_confirmed
    operator.points.clear()
    for area, slots in task._observations.items():
        for index in range(len(slots)):
            operator.points[getattr(task, area + "_area")[index]] = (area, index)

    prepared = task.prepare_for_battle()

    assert prepared.state == Readiness.DEGRADED, prepared
    assert len(operator.moves) == 2
    assert scene_roster(operator)["on_field"] == sorted([
        ("姬子·启行", 1), ("丹恒·饮月", 1), ("椒丘", 1)])
    # Continue the same task at the screen/OCR boundary. The shop frames use
    # real templates and the real vision/page logic, never OS input.
    shop = NavigationOperator(clock)
    shop.scene = dict(operator.scene)
    shop.points = dict(operator.points)
    shop.offer_names = ["万敌"] * 5
    if reward_on_open:
        shop.offer_names[0] = "三月七"
        shop.overlay = engine.CWIMG.SELECT_INVEST_STRATEGY
    task.operator = shop
    task._vision = CurrencyWarsVision(shop, CALIBRATION_ROOT / "profile.json",
                                     tmp_path / "shop", max_samples=0)
    task._preparation_round = (2, 5)
    task._preparation_round_context = (task._cycle_number, task._last_completed_battle_id,
                                       task._preparation_departure_confirmed)
    task.shopping_budget.update(actions=1, experiences=0, refreshes=0)

    result = task.shopping()

    assert shop.purchases == [] and shop.inputs == [] and shop.gold == 20
    assert shop.shop_open is False
    if reward_on_open:
        assert shop.reward_selections == 1
        assert result.result == ActionResult.INDETERMINATE, result
        assert result.reason == "purchase_targets_unknown"
    else:
        assert result.result == ActionResult.CONFIRMED, result
        assert shop.store_reads > 0
        assert shop.toggle_events == ["close"]
