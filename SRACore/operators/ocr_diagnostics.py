"""实际模型会话的初始化快照；不修改 OCR 配置或执行提供程序。"""
from __future__ import annotations

import json

from loguru import logger
from rapidocr import RapidOCR as _RapidOCR

from SRACore.util.phase_timing import _stage


class RapidOCR(_RapidOCR):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        models = {}
        for role in ("det", "cls", "rec"):
            try:
                component = getattr(self, "text_" + role, None)
                # 已安装 RapidOCR: TextDetector.session -> OrtInferSession.session。
                session = getattr(getattr(component, "session", None), "session", None)
                getter = getattr(session, "get_providers", None)
                if not callable(getter):
                    models[role] = dict(status="unavailable", providers=[])
                    continue
                providers = getter()  # 每模型仅初始化时调用一次，不查询全局 available。
                if not isinstance(providers, (tuple, list)) or not all(isinstance(p, str) for p in providers):
                    models[role] = dict(status="invalid", providers=[])
                    continue
                bounded = []
                for provider in providers[:4]:
                    value = provider[:64]
                    while len(json.dumps(value)) > 96:
                        value = value[:-1]
                    bounded.append(value)
                models[role] = dict(status="observed", providers=bounded)
                if bounded != list(providers):
                    models[role]["truncated"] = True
            except Exception as error:
                models[role] = dict(status="unavailable", providers=[], error=type(error).__name__[:64])
        try:
            logger.info("OCR_PROVIDERS " + json.dumps(dict(
                evidence="model_session_get_providers_at_initialization",
                scope="session_provider_order_not_per_node_execution", models=models), separators=(",", ":")))
        except Exception:
            pass  # 诊断输出失败不能导致已初始化的模型失效。

    @_stage("ocr")
    def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)
