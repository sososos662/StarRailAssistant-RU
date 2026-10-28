"""Integration regression at the agreed public shopping seam, no live input."""
import json

from loguru import logger

from tests.test_currency_wars_shop_navigation_perf import navigation  # noqa: F401
from tests.test_currency_wars_partial_store_diagnostics import replay_partial


def test_partial_sample_and_exclusive_timing_coexist_without_extra_ocr_or_purchase(navigation, monkeypatch):
    task, operator = navigation.task, navigation.operator
    _, frames = replay_partial(navigation, monkeypatch)
    messages = []
    sink = logger.add(lambda message: messages.append(message.record['message']))
    try:
        result = task.shopping()
    finally:
        logger.remove(sink)
    assert result.reason == 'partial_store'
    assert operator.purchases == operator.inputs == []
    assert operator.gold == 20 and operator.shop_open is False
    assert len(frames) == 2
    samples = list(task._vision.sample_dir.glob('*_partial_store.json'))
    assert len(samples) == 1
    metadata = json.loads(samples[0].read_text(encoding='utf-8'))
    assert metadata['store_scan']['source'] == 'decision_frame'
    assert len(metadata['store_scan']['attempts']) == 2
    records = [json.loads(message.split('CW_TIMING ', 1)[1])
               for message in messages if message.startswith('CW_TIMING ')]
    assert len(records) == 1
    timing = records[0]
    assert timing['scope'] == 'shopping' and timing['outcome'] == 'returned'
    assert sum(v['wall_s'] for v in timing['stages'].values()) <= timing['wall_s'] + 1e-5
    assert sum(v['process_s'] for v in timing['stages'].values()) <= timing['process_s'] + 1e-5
    assert len(json.dumps(timing)) < 2048
