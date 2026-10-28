from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('codepage', ['cp1251', 'cp1252', 'gbk'])
def test_standard_streams_roundtrip_without_replacement(codepage, tmp_path):
    env = os.environ.copy()
    env.update(PYTHONIOENCODING=codepage + ':strict', PYTHONUTF8='0')
    text = '中文 Русский English ё — →'
    code = (
        'import sys; from SRACore.util.standard_io import configure_standard_streams; '
        'configure_standard_streams(); '
        'text=sys.stdin.readline().rstrip("\\n"); '
        'print(text); print(text, file=sys.stderr)'
    )
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                            input=(text + '\n').encode('utf-8'), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode('utf-8').strip() == text
    assert result.stderr.decode('utf-8').strip() == text


def test_in_memory_capture_streams_are_not_replaced(monkeypatch):
    from SRACore.util.standard_io import configure_standard_streams
    streams = [io.StringIO() for _ in range(3)]
    for name, stream in zip(('stdin', 'stdout', 'stderr'), streams):
        monkeypatch.setattr(sys, name, stream)
    configure_standard_streams()
    assert [sys.stdin, sys.stdout, sys.stderr] == streams


@pytest.mark.parametrize('codepage', ['cp1251', 'cp1252', 'gbk'])
@pytest.mark.parametrize('language', [0, 2])
def test_currency_wars_launch_feedback_under_legacy_windows_codepages(codepage, language, tmp_path):
    state = tmp_path / 'SRA'
    state.mkdir()
    (state / 'settings.json').write_text(json.dumps({'display': {'language': language}}), encoding='utf-8')
    env = os.environ.copy()
    env.update(APPDATA=str(tmp_path), HOME=str(tmp_path),
               PYTHONIOENCODING=codepage + ':strict', PYTHONUTF8='0')
    # No username: the real extension must reject config before any game input.
    # Query a Unicode identifier as well to test the incoming UTF-8 pipe.
    commands = 'extension schema 中文Русский --json\nextension run CurrencyWarsPlus\nextension schema CurrencyWarsPlus --json\nquit\n'
    result = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--inline', '--no-admin'],
                            cwd=ROOT, env=env, input=commands.encode('utf-8'),
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    stdout = result.stdout.decode('utf-8')
    stderr = result.stderr.decode('utf-8')
    assert 'UnicodeEncodeError' not in stdout + stderr
    assert 'UnicodeDecodeError' not in stdout + stderr
    assert '\ufffd' not in stdout + stderr
    assert ('已启动扩展' if language == 0 else 'Расширение «CurrencyWarsPlus» запущено') in stdout
    assert ('请先在货币战争优化版的配置中填写开拓者名称。' if language == 0
            else 'Сначала укажите имя Первопроходца') in stderr
    responses = [json.loads(line) for line in stdout.splitlines() if line.startswith('{')]
    assert any('中文Русский' in item.get('message', '') for item in responses)
    assert any(isinstance(item.get('data'), dict) and 'properties' in item['data'] for item in responses)
