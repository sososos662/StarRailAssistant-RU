"""Replay the generic badge doubt and recorded Blade confidence at public preparation."""
from PIL import Image
import pytest

from tests.test_currency_wars_slow_preparation import replay, ReplayVision, engine
from extensions.cw_plus.layout import LayoutObservation
from extensions.cw_plus.logic import SlotObservation, SlotState
from extensions.cw_plus.preparation import Readiness


class IdentityReplayVision(ReplayVision):
    score = 0.89194
    names = ("千冶·刃",)
    layout_seconds = 1

    def read_backend_layout(self, previous_positions, **kwargs):
        self.operator.clock.advance(self.layout_seconds)
        return LayoutObservation(True, tuple(previous_positions), geometry_valid=True,
                       reason="backend_identity_partial", unknown_protected_slots=(3,),
                       ordinary_slots=(0, 1, 2, 4, 5), ordinary_count_confirmed=False, ordinary_count=None)

    def _slot_is_empty(self, area, index, position, **kwargs):
        return False

    def _engine_ocr(self, image, *, minimum_confidence=None):
        # Same-frame panel ROI; event-title crops never return a character name.
        if image.size != (202, 61) or self.operator.selected != ("off_field", 3):
            return []
        index = getattr(self, "panel_reads", 0)
        self.panel_reads = index + 1
        name = self.names[index % len(self.names)]
        return [([[1, 21], [99, 21], [99, 60], [1, 60]], name, self.score)] if (
            minimum_confidence is None or self.score >= minimum_confidence) else []


@pytest.fixture
def identity_replay(replay):
    task, operator = replay.task, replay.operator
    operator.ocr_confidence = 0.7
    operator.scene[("off_field", 3)] = operator.scene.pop(("off_field", 1))
    task._backend_unknown_slots = {3}
    task._backend_ordinary_slots = (0, 1, 2, 4, 5)
    task._backend_identity_confirmed = False
    task._observations["off_field"][3] = SlotObservation(3, SlotState.UNKNOWN,
                                                       evidence="backend_identity_unknown")
    task._vision = IdentityReplayVision(operator)
    star = Image.open(engine.CWIMG.STAR).convert("RGB")
    operator.frame.paste(star, (1596, 163))
    return replay


def test_generic_badge_doubt_can_recover_a_known_blade_at_normal_ocr_confidence(identity_replay):
    task, operator = identity_replay.task, identity_replay.operator

    result = task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert operator.inputs == []  # Recognition must never buy, drag, sell or force battle.


def test_identity_review_with_recorded_layout_duration_finishes_without_forcing_battle(identity_replay):
    task, operator = identity_replay.task, identity_replay.operator
    task._vision.layout_seconds = 23

    result = task.prepare_for_battle()

    assert result.state == Readiness.READY, result
    assert operator.inputs == []


@pytest.mark.parametrize("fault", ["weak_ocr", "unknown_name", "disagreeing_frames", "missing_stars"])
def test_identity_recovery_cannot_bypass_missing_or_conflicting_evidence(identity_replay, fault):
    task, operator = identity_replay.task, identity_replay.operator
    if fault == "weak_ocr":
        task._vision.score = 0.69
    elif fault == "unknown_name":
        task._vision.names = ("Несуществующий персонаж",)
    elif fault == "disagreeing_frames":
        task._vision.names = ("千冶·刃", "三月七")
    else:
        operator.frame.paste((15, 25, 35), (1593, 162, 1671, 185))

    result = task.prepare_for_battle()

    assert result.state == Readiness.BLOCKED, result
    assert operator.inputs == []
