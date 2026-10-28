"""Public terminal navigation with sanitized saved pixels and actual OCR responses."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest
from loguru import logger

from tests.test_currency_wars_terminal_exit import TerminalOperator, OCR
from tests.test_currency_wars_slow_preparation import engine
from SRACore.util.errors import ThreadStoppedError

FIXTURES = Path(__file__).parent / 'fixtures/terminal_recorded_235133'
RECORDED = json.loads((FIXTURES / 'ocr.json').read_text(encoding='utf-8'))


@pytest.fixture
def recorded_terminal(tmp_path, monkeypatch):
    operator = TerminalOperator()
    with Image.open(FIXTURES / 'summary.png') as crop:
        frame = Image.new('RGB', (1920,1080))
        frame.paste(crop, (500,160))
    operator.pages['summary'] = frame
    readings = {**OCR, **RECORDED}

    def ocr(image, **kwargs):
        return deepcopy(readings.get(hashlib.sha256(image.tobytes()).hexdigest(), []))

    operator.ocr_engine = ocr
    monkeypatch.setattr(engine, 'time', SimpleNamespace(monotonic=operator.clock.monotonic))
    task = engine.CurrencyWars(operator, 1, data_dir=tmp_path)
    task.REWARD_TRANSITION_TIMEOUT = 8
    task._vision.max_samples = 0
    return task, operator


def test_recorded_success_with_partial_native_action_ocr_returns_to_main(recorded_terminal):
    task, operator = recorded_terminal

    assert task.handle_game_over(None) is True

    assert operator.page == 'main'
    assert operator.clicks == ['终局：final_summary', '终局：final_next_page', '终局：final_return']


def test_recorded_final_health_is_confirmed_from_two_fresh_same_roi_gray_frames(recorded_terminal):
    task, operator = recorded_terminal
    messages = []
    sink = logger.add(lambda message: messages.append(message.record['message']))
    try:
        assert task.handle_game_over(None) is True
    finally:
        logger.remove(sink)
    assert operator.page == 'main'
    assert any('小队生命值=100' in message for message in messages)


@pytest.mark.parametrize('fault', ['weak_action','wrong_action','stop_action'])
def test_expanded_action_still_needs_exact_confident_text_and_stop_safety(recorded_terminal, fault):
    task, operator = recorded_terminal
    read = operator.ocr_engine

    def ocr(image, **kwargs):
        rows = read(image, **kwargs)
        if image.size == (1152,280):
            if fault == 'stop_action':
                operator.stop_event.set()
            elif fault == 'weak_action':
                rows[0] = (rows[0][0], rows[0][1], .89)
            else:
                rows[0] = (rows[0][0], '下一页', .999)
        return rows

    operator.ocr_engine = ocr
    expected = ThreadStoppedError if fault == 'stop_action' else RuntimeError
    with pytest.raises(expected):
        task.handle_game_over(None)
    assert operator.clicks == []


def test_recorded_second_frame_losing_evaluation_cannot_authorize_summary_click(recorded_terminal):
    task, operator = recorded_terminal
    capture = operator.screenshot
    calls = 0

    def screenshot(**kwargs):
        nonlocal calls
        frame = capture(**kwargs)
        calls += 1
        if calls % 2:
            frame.paste((0,0,0), (576,335,1325,421))
        return frame

    operator.screenshot = screenshot
    with pytest.raises(RuntimeError, match='result_terminal_navigation_timeout'):
        task.handle_game_over(None)
    assert operator.clicks == []


@pytest.mark.parametrize('value,score', [('150', .999), ('100', .89), ('100 | 99', .999)])
def test_final_gray_fallback_never_overrides_invalid_weak_or_conflicting_rgb_health(recorded_terminal, value, score):
    task, operator = recorded_terminal
    read = operator.ocr_engine
    gray_calls = 0

    def ocr(image, **kwargs):
        nonlocal gray_calls
        if image.size == (268,54):
            if image.mode == 'L':
                gray_calls += 1
                return read(image, **kwargs)
            box = [[24,6],[240,6],[240,50],[24,50]]
            if value == '100 | 99':
                return [(box,'小队生命值100',score),(box,'小队生命值99',score)]
            return [(box,'小队生命值'+value,score)]
        return read(image, **kwargs)

    operator.ocr_engine = ocr
    messages = []
    sink = logger.add(lambda message: messages.append(message.record['message']))
    try:
        assert task.handle_game_over(None) is True
    finally:
        logger.remove(sink)
    assert gray_calls == 0
    assert any('小队生命值=None' in message for message in messages)
