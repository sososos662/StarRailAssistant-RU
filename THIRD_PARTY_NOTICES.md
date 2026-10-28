# Сторонние компоненты

Этот файл не заменяет тексты лицензий поставщиков и не объявляет все зависимости
AGPL. Сохраняйте `LICENSE`, `NOTICE`, оригинальные уведомления и включённые
лицензии. Вместе с модифицированными бинарниками предоставляйте соответствующий
исходный код этой же ревизии и инструкции сборки.

| Компонент | Происхождение / уведомления |
| --- | --- |
| StarRailAssistant | Shasnow/StarRailAssistant, база v2.25.0-beta.1, AGPL-3.0-or-later |
| CurrencyWarsPlus | Атрибуция в исходных файлах сохранена; часть этого проекта |
| Python 3.12 / Nuitka | Python Software Foundation / Nuitka; лицензии runtime и сборщика различны |
| .NET / ASP.NET Core / Avalonia / SukiUI | Соответствующие NuGet-пакеты; версии закреплены в csproj, уведомления поставщиков сохраняются |
| Vue / Element Plus и WebUI-зависимости | `SRAFrontend/srafrontend-webui/package.json` и `pnpm-lock.yaml` |
| RapidOCR / модели PP-OCR | RapidAI/RapidOCR 3.9.1, PaddleOCR; ссылки и SHA256 моделей в `ocr-models.json` |
| ONNX Runtime | Microsoft/onnxruntime; API 1.27.0 и native DirectML 1.24.4 — явно документированная комбинация |
| DirectML payload | Официальный `onnxruntime-directml` wheel; `onnxruntime/directml/LICENSE` и `ThirdPartyNotices.txt` в готовом комплекте |
| VC runtime DLL | Подписанные Microsoft библиотеки в локальной папке программы, без изменения системных DLL |
| OpenCV / NumPy / Pillow / Selenium и прочие Python-зависимости | Версии в `pyproject.toml`; лицензии соответствующих пакетов |
| Игровые названия, изображения и распознавательные образцы | Права соответствующих владельцев; форк не заявляет права на игру или торговые марки |

Официальный DirectML wheel в `vendor/` сохранён для воспроизводимости. Его SHA256:
`f2ecb68b7b7b259d2ef3112ae760149f9b5a1e7c0fbb73d539da6250a648a614`.
Не меняйте его содержимое и не выдавайте сторонние библиотеки за собственную разработку.

Предлагаемый build-сценарий собирает доступные тексты лицензий Python-пакетов
в `third_party/python/` и сохраняет DirectML notices. Перед внешним выпуском
проверьте полноту уведомлений для фактически выбранного состава пакета,
включая NuGet-компоненты и модели. Это перечень происхождения, а не юридическая
гарантия пригодности любой произвольной перепаковки.
