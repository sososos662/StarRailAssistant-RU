from __future__ import annotations

import importlib
import json
import re
import string
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

from SRACore.localization import Resource
from SRACore.localization.presentation import localize_schema, translate

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "SRACore/localization/presentation.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def restore_language():
    original = Resource.lang
    yield
    Resource.set_language(original)


def fields(text):
    return Counter(re.findall(r"\{(\d+)\}", text))


@pytest.mark.parametrize("entry", CATALOG, ids=lambda item: item["key"])
def test_presentation_placeholders_and_translation(entry):
    assert fields(entry["source"]) == fields(entry["ru"])
    assert "\ufffd" not in entry["ru"]
    assert "???" not in entry["ru"]
    assert entry["ru"].strip()
    Resource.set_language("ru-RU")
    # Distinct sentinel values prove field positions survive reordering.
    source = re.sub(r"\{(\d+)\}", lambda m: f"VALUE_{m[1]}", entry["source"])
    expected = re.sub(r"\{(\d+)\}", lambda m: f"VALUE_{m[1]}", entry["ru"])
    # Very short punctuation-only formats are intentionally not matched by the
    # Python output boundary; the GUI uses strongly typed FormattableString.
    if len(re.sub(r"\{\d+\}", "", entry["source"])) >= 3 or not fields(entry["source"]):
        assert translate(source) == expected


def test_original_languages_are_untouched():
    for language in (0, 1):
        Resource.set_language(language)
        for entry in CATALOG:
            assert translate(entry["source"]) == entry["source"]


def test_existing_resource_keys_and_placeholders():
    resources = [json.loads((ROOT / f"SRACore/localization/resource_{lang}.json").read_text(encoding="utf-8"))
                 for lang in ("zh-cn", "en-us", "ru-ru")]
    assert resources[0].keys() == resources[1].keys() == resources[2].keys()
    for key in resources[0]:
        for data in resources[1:]:
            assert Counter((f, spec, conversion) for _, f, spec, conversion in string.Formatter().parse(resources[0][key]) if f is not None) == Counter(
                (f, spec, conversion) for _, f, spec, conversion in string.Formatter().parse(data[key]) if f is not None)
    Resource.set_language(2)
    assert Resource.lang == "ru-ru"
    assert Resource.task_notificationTitle == "Уведомление о задачах"


def test_gui_resource_key_parity():
    directory = ROOT / "SRAFrontend/SRAFrontend/Localization"
    for stem in ("Resources", "ExtraResources"):
        sets = [{n.attrib["name"]: n.findtext("value") or "" for n in ET.parse(directory / f"{stem}{lang}.resx").findall("data")}
                for lang in ("", ".zh", ".ru-RU")]
        assert sets[0].keys() == sets[1].keys() == sets[2].keys()
        assert all("\ufffd" not in value for value in sets[2].values())


def test_currency_wars_schema_keeps_actual_values_and_aliases():
    from extensions.currency_wars_plus import CurrencyWarsPlusConfig
    Resource.set_language(0)
    original = CurrencyWarsPlusConfig.model_json_schema()
    Resource.set_language(2)
    localized = localize_schema(original)
    assert not re.search(r"[\u4e00-\u9fff]", localized["description"])
    assert original["properties"].keys() == localized["properties"].keys()
    for key, prop in original["properties"].items():
        for technical in ("type", "enum", "default", "minimum", "maximum", "x-allow-custom", "x-refreshable"):
            assert prop.get(technical) == localized["properties"][key].get(technical)
    assert localized["properties"]["难度"]["x-enum-labels"] == ["Минимальная", "Максимальная", "Текущая"]
    assert localized["properties"]["攻略"]["x-refresh-label"] == "Сканировать папку стратегий"
    strategies = localized["properties"]["攻略"]
    assert {"himeko_level5_quality_level7_two_star_20261018",
            "silver_wolf_lv999_budget_economy_20261017"} <= set(strategies["enum"])
    assert len(strategies["enum"]) == len(strategies["x-enum-labels"])
    config = CurrencyWarsPlusConfig.model_validate({"开拓者名称": "Test", "难度": 2})
    saved = config.model_dump(by_alias=True)
    assert saved["开拓者名称"] == "Test"
    assert saved["难度"] == 2
    assert "Имя Первопроходца" not in saved


def test_language_setting_roundtrip():
    from SRACore.models.app_settings import AppSettings
    settings = AppSettings.from_dict({"display": {"language": 2}})
    assert settings.Display.Language == 2
    assert AppSettings.from_dict(json.loads(json.dumps(settings.to_dict()))).Display.Language == 2


def test_himeko_strategy_label_describes_her_gate_not_every_characters_stars():
    strategy = json.loads((ROOT / "extensions/cw_plus/strategies/himeko_level5_quality_level7_two_star_20261018.json").read_text(encoding="utf-8"))
    assert strategy["formation"]["upgrade_gate"] == {"from_level": 7, "fielded": {"姬子·启行": 2}}
    assert strategy["on_field"]["姬子·启行"] == 3
    Resource.set_language(2)
    assert translate(strategy["title"]) == "Химеко: ур. 5 — качество; ур. 7+ — Химеко 2★"


def test_currency_wars_runtimes_help_is_not_limited_to_reroll():
    Resource.set_language(2)
    assert translate("货币战争刷开局时的运行次数") == "Число партий «Валютных войн»; в подборе старта — число попыток"


def test_currency_wars_card_description_explains_what_the_extension_does():
    from SRACore.extension import extension_registry
    importlib.import_module("extensions.currency_wars_plus")
    Resource.set_language(2)
    assert translate(extension_registry.get("CurrencyWarsPlus").description) == (
        "Автоматически играет в «Валютные войны» по выбранной стратегии: покупает персонажей, "
        "расставляет команду и запускает бои. Поддерживает обычный режим и разгон.")
