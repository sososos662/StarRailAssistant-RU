"""The public source export retains the explicitly approved Europe variant only."""
import hashlib
from pathlib import PurePosixPath

from scripts.export_source import source_files


def test_public_export_contains_approved_europe_variant_and_only_release_strategies():
    prefix = "extensions/cw_plus/strategies/"
    files = source_files()
    strategies = {PurePosixPath(name).name for name in files if name.startswith(prefix)}
    assert strategies == {
        "himeko_level5_quality_level7_two_star_20261018.json",
        "silver_wolf_lv999_budget_economy_20261017.json",
        "himeko_global_europe_20261026.json",
        "货币战争增强版_标准配置填写规范.annotated.jsonc",
    }
    europe = files[prefix + "himeko_global_europe_20261026.json"]
    assert hashlib.sha256(europe.read_bytes()).hexdigest() == (
        "62583343108ab9ce16a3b5e00ce46275f4639f75ab1a400c48f85b9d3d7e8cbe")


def test_russian_landing_page_and_named_translation_are_both_exported_and_identical():
    files = source_files()
    assert files["README.md"].read_bytes() == files["README.ru.md"].read_bytes()
    landing = files["README.md"].read_text(encoding="utf-8")
    assert "## Что добавлено и улучшено в форке" in landing
    assert "Химэко Нова (Европа)" in landing
    assert "README.zh.md" in files
