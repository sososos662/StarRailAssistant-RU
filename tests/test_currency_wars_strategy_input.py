"""Public import-stage replay; clipboard and OS input are in-memory fakes only."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

RUNTIME_ROOT = Path(os.environ.get("SRA_CW_RUNTIME_ROOT", Path(__file__).resolve().parents[1]))
if os.environ.get("SRA_CW_RUNTIME_ROOT"):
    sys.path.insert(0, str(RUNTIME_ROOT))

from SRACore.operators.model import Box
from SRACore.util.errors import ThreadStoppedError

engine = importlib.import_module("extensions.cw_plus.CurrencyWars")
CODE = "##NUeqZIpMK/hEG9cYxn4Rp2a++/H0kjEfkk2Wb6BwkqM=##"


class ImportReplayOperator:
    def __init__(self):
        self.settings = SimpleNamespace()
        self.window_context = SimpleNamespace(width=1920, height=1080)
        self.stop_event = Event()
        self.tm_confidence = 0.9
        self.ocr_confidence = 0.7
        self.clock = 1000.0
        self.phase = "strategy"
        self.clipboard = ""
        self.text = ""
        self.confirms = 0
        self.native_pastes = 0
        self.shortcut_pastes = 0
        self.inputs = []
        self.native_works = False
        self.read_text = None
        self.application_confirmed = True
        self.ocr_score = 0.99
        self.stop_after_paste = False
        self.hide_control = None
        self.dialog = Image.open(Path(__file__).parent / "fixtures/cw_strategy_code_dialog.png").convert("RGB")

    def sleep(self, seconds):
        self.clock += seconds

    def screenshot(self):
        self.clock += 0.05
        frame = Image.new("RGB", (1920, 1080), (15, 25, 35))
        if self.phase == "dialog":
            frame.paste(self.dialog, (398, 288))
            if self.hide_control == "title":
                ImageDraw.Draw(frame).rectangle((870, 324, 1048, 360), fill=(196, 196, 196))
            elif self.hide_control == "paste":
                ImageDraw.Draw(frame).rectangle((1418, 509, 1470, 562), fill=(196, 196, 196))
            if self.text:
                draw = ImageDraw.Draw(frame)
                draw.rectangle((445, 430, 1395, 635), fill=(196, 196, 196))
                draw.text((458, 435), self.text, fill=(55, 55, 55),
                          font=ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 24))
        elif self.phase == "applied":
            frame.paste(Image.open(engine.CurrencyWars.STRATEGY_APPLIED_IMAGE).convert("RGB"), (1200, 850))
        elif self.phase == "preparation":
            frame.paste(Image.open(engine.CWIMG.PREPARATION_STAGE).convert("RGB"), (20, 20))
            frame.paste(Image.open(engine.CWIMG.FOLD).convert("RGB"), (1000, 850))
        return frame

    def wait_img(self, template, **kwargs):
        return self.locate(template)

    def locate(self, template, **kwargs):
        if template == engine.CWIMG.STRATEGY and self.phase == "strategy":
            return Box(1570, 45, 80, 44, source=template)
        if template == engine.CWIMG.ENTER_STRATEGY_CODE and self.phase == "strategy":
            return Box(1400, 960, 166, 48, source=template)
        if template == engine.IMG.ENSURE2 and self.phase == "dialog":
            return Box(987, 713, 364, 62, source=template)
        if template == engine.CWIMG.APPLY_STRATEGY and self.phase == "apply":
            return Box(1400, 900, 160, 50, source=template)
        if (template == engine.CurrencyWars.STRATEGY_APPLIED_IMAGE and self.phase == "applied"
                and self.application_confirmed):
            return Box(1200, 850, 160, 50, source=template)
        return None

    def locate_any(self, templates, **kwargs):
        for index, template in enumerate(templates):
            box = self.locate(template)
            if box is not None:
                return index, box
        return -1, None

    def click_box(self, box, *, after_sleep=0, **kwargs):
        self.inputs.append(box.source)
        if box.source == engine.CWIMG.ENTER_STRATEGY_CODE:
            self.phase = "dialog"
        elif box.source == engine.IMG.ENSURE2:
            self.confirms += 1
            if self.text:
                self.phase = "apply"
        elif str(box.source).endswith("strategy_code_paste.png"):
            self.native_pastes += 1
            if self.native_works:
                self.text = self.clipboard
            if self.stop_after_paste:
                self.stop_event.set()
        elif box.source == engine.CWIMG.APPLY_STRATEGY:
            self.phase = "applied"
        self.sleep(after_sleep)
        return True

    def click_point(self, *args, after_sleep=0, **kwargs):
        self.sleep(after_sleep)
        return True

    def copy(self, text):
        self.clipboard = text

    def paste(self):
        self.shortcut_pastes += 1  # Replay the observed silent no-op.

    def ocr_engine(self, image, **kwargs):
        text = self.read_text if self.read_text is not None else self.text or "请输入攻略码..."
        return [([[0, 0], [700, 0], [700, 25], [0, 25]], text, self.ocr_score)]

    def press_key(self, key, **kwargs):
        self.inputs.append(key)
        if key == "esc" and self.phase == "applied":
            self.phase = "preparation"
        return True


@pytest.fixture
def replay(tmp_path, monkeypatch):
    operator = ImportReplayOperator()
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=lambda: operator.clock))
    task = engine.CurrencyWars(operator, 1, data_dir=tmp_path)
    task.strategy_code = CODE
    return SimpleNamespace(task=task, operator=operator)


def test_empty_paste_never_submits_strategy_code(replay):
    assert replay.task.handle_game_entered() is False
    assert replay.operator.confirms == 0, "The recorded empty field must never be submitted"
    assert engine.CWIMG.APPLY_STRATEGY not in replay.operator.inputs
    assert replay.operator.native_pastes == 1


def test_native_paste_imports_even_when_shortcut_is_a_noop(replay):
    assert Path(engine.__file__).resolve() == (RUNTIME_ROOT / "extensions/cw_plus/CurrencyWars.py").resolve()
    replay.operator.native_works = True

    assert replay.task.handle_game_entered() is True
    assert replay.operator.confirms == 1
    assert replay.operator.native_pastes == 1
    assert replay.operator.shortcut_pastes == 0
    assert replay.operator.phase == "preparation"


@pytest.mark.parametrize("reading", ["", "请输入攻略码...", "##WrongCodeThatDoesNotMatchAnything123456##"])
def test_unrecognized_or_wrong_text_cannot_be_submitted(replay, reading):
    replay.operator.native_works = True
    replay.operator.read_text = reading

    assert replay.task.handle_game_entered() is False
    assert replay.operator.confirms == 0


def test_sending_apply_is_not_proof_that_strategy_was_applied(replay):
    replay.operator.native_works = True
    replay.operator.application_confirmed = False

    assert replay.task.handle_game_entered() is False
    assert replay.operator.phase == "applied"
    assert "esc" not in replay.operator.inputs


@pytest.mark.parametrize("control", ["title", "paste"])
def test_unconfirmed_dialog_never_receives_clipboard_input(replay, control):
    replay.operator.hide_control = control

    assert replay.task.handle_game_entered() is False
    assert replay.operator.clipboard == ""
    assert replay.operator.native_pastes == replay.operator.confirms == 0


@pytest.mark.parametrize("score", [0.69, float("nan")])
def test_unreliable_ocr_never_authorizes_submission(replay, score):
    replay.operator.native_works = True
    replay.operator.ocr_score = score

    assert replay.task.handle_game_entered() is False
    assert replay.operator.confirms == 0


def test_stop_after_paste_is_propagated_without_confirmation(replay):
    replay.operator.stop_after_paste = True

    with pytest.raises(ThreadStoppedError):
        replay.task.handle_game_entered()

    assert replay.operator.confirms == 0
