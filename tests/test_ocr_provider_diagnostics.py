"""Agreed RapidOCR(image) seam with fake external ONNX sessions only."""
import json
from types import SimpleNamespace

import numpy as np
import pytest
from loguru import logger

from SRACore.operators.factory import RapidOCR


@pytest.mark.parametrize("mode", ["observed", "unavailable", "oversized"])
def test_initialized_models_report_actual_sessions_once_not_available_or_requested_providers(tmp_path, monkeypatch, mode):
    from rapidocr.inference_engine.onnxruntime import main as ort_boundary

    sessions = []

    class Session:
        def __init__(self, *args, **kwargs):
            self.reads = 0
            self.role = len(sessions)
            sessions.append(self)

        def get_providers(self):
            self.reads += 1
            if self.reads == 2 and mode == "unavailable":
                raise RuntimeError("diagnostic query failed")
            if self.reads == 2 and mode == "oversized":
                return ["測" * 10000] * 40
            # Deliberately mixed: a runtime-wide list cannot describe the models.
            return (["DmlExecutionProvider", "CPUExecutionProvider"] if self.role != 1
                    else ["CPUExecutionProvider"])

        def get_modelmeta(self):
            return SimpleNamespace(custom_metadata_map={"character": "a\nb"})

    monkeypatch.setattr(ort_boundary, "InferenceSession", Session)
    model = tmp_path / "external-fake-model.onnx"
    model.write_bytes(b"external session double, never passed to native ORT")
    params = {f"{role}.model_path": str(model) for role in ("Det", "Cls", "Rec")}
    params["Global.log_level"] = "error"
    messages = []
    sink = logger.add(lambda message: messages.append(message.record["message"]))
    try:
        ocr = RapidOCR(params=params)
        initial_reads = [session.reads for session in sessions]
        for _ in range(3):
            output = ocr(np.zeros((32, 80, 3), dtype=np.uint8),
                         use_det=False, use_cls=False, use_rec=False)
            assert output.txts is None
    finally:
        logger.remove(sink)

    records = [json.loads(message.split("OCR_PROVIDERS ", 1)[1])
               for message in messages if message.startswith("OCR_PROVIDERS ")]
    assert len(records) == 1
    assert records[0]["evidence"] == "model_session_get_providers_at_initialization"
    if mode == "observed":
        assert records[0]["models"] == {
            "det": {"status": "observed", "providers": ["DmlExecutionProvider", "CPUExecutionProvider"]},
            "cls": {"status": "observed", "providers": ["CPUExecutionProvider"]},
            "rec": {"status": "observed", "providers": ["DmlExecutionProvider", "CPUExecutionProvider"]},
        }
    elif mode == "unavailable":
        assert all(model["status"] == "unavailable" and model["providers"] == []
                   for model in records[0]["models"].values())
    else:
        assert all(model["truncated"] for model in records[0]["models"].values())
    # RapidOCR itself asks once to verify; diagnostic code adds exactly one read.
    assert initial_reads == [2, 2, 2]
    assert [session.reads for session in sessions] == initial_reads
    assert len(json.dumps(records[0])) < 2048
    (tmp_path / "providers.json").write_text(json.dumps(records[0], indent=2), encoding="utf-8")
