"""有界的线程上下文诊断；不改变操作、等待或异常传播。"""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import json
import time

from loguru import logger


_ACTIVE = ContextVar("sra_phase_timing", default=None)
_KEYS = ("capture", "wait", "cpu_pages", "cpu_geometry", "ocr", "transition", "recovery", "other")


class _Timing:
    def __init__(self, clock):
        self.clock = clock
        self.started = self.last = (round(clock() * 1e6), round(time.process_time() * 1e6))
        self.current = "other"
        self.stages = {key: [0, 0, 0] for key in _KEYS}

    def switch(self, key):
        # 整数微秒保持分区精确，避免逐叶浮点舍入累积制造假超额。
        now = round(self.clock() * 1e6), round(time.process_time() * 1e6)
        values = self.stages[self.current]
        for index in (0, 1):
            values[index] += max(0, now[index] - self.last[index])
        previous, self.current, self.last = self.current, key, now
        return previous

    def record(self, scope, source, outcome):
        self.switch("other")
        return dict(scope=scope, capture_source=source, outcome=outcome,
                    accounting="exclusive_wall_and_process", process_clock="process_wide",
                    wall_s=max(0, self.last[0] - self.started[0]) / 1e6,
                    process_s=max(0, self.last[1] - self.started[1]) / 1e6,
                    stages={key: dict(wall_s=values[0] / 1e6, process_s=values[1] / 1e6,
                                      spans=values[2]) for key, values in self.stages.items()})


def _stage(key):
    """只累计当前叶阶段；嵌套结束后恢复父阶段，日志不逐调用输出。"""
    if key not in _KEYS:
        raise ValueError("unknown timing stage")

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            timing = _ACTIVE.get()
            if timing is None:
                return function(*args, **kwargs)
            previous = timing.switch(key)
            timing.stages[key][2] = min(999999, timing.stages[key][2] + 1)
            try:
                return function(*args, **kwargs)
            finally:
                timing.switch(previous)
        return wrapped
    return decorate


@_stage("wait")
def _wait(sleeper, seconds):
    """保留原始 sleep 函数与参数，不切换到其他等待实现。"""
    return sleeper(seconds)


def _capture_source(operator):
    # 不能把 replay 的 copy 或伪造 type='Browser' 当作真实窗口截图。
    seen = set()
    while id(operator) not in seen:
        seen.add(id(operator))
        inner = vars(operator).get("_operator") if hasattr(operator, "__dict__") else None
        if inner is None:
            break
        operator = inner
    module = type(operator).__module__
    if hasattr(operator, "__dict__") and "screenshot" in vars(operator):
        return "injected_operator"
    if module == "SRACore.operators.operator":
        return "local_operator"
    if module == "SRACore.operators.browser_operator":
        return "browser_operator"
    return "injected_operator"


@contextmanager
def _scope(scope, operator, *, clock=None):
    """父作用域存在时复用，不生成第二份可相加的记录。"""
    if _ACTIVE.get() is not None:
        yield
        return
    timing = _Timing(clock or time.monotonic)
    token = _ACTIVE.set(timing)
    outcome = "returned"
    try:
        yield
    except BaseException:
        outcome = "raised"
        raise
    finally:
        _ACTIVE.reset(token)
        try:
            record = timing.record(scope, _capture_source(operator), outcome)
            logger.debug("CW_TIMING " + json.dumps(record, separators=(",", ":")))
        except Exception:
            # 诊断失败不可掩盖停止或原始业务异常。
            pass


def _report(scope, *, stage="other", clock=None):
    """最外层操作仅输出一条固定字段记录；内层操作只切换阶段。"""
    def decorate(function):
        staged = _stage(stage)(function)

        @wraps(function)
        def wrapped(self, *args, **kwargs):
            with _scope(scope, self.operator, clock=clock):
                return staged(self, *args, **kwargs)
        return wrapped
    return decorate
