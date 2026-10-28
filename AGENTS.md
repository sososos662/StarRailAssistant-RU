# AGENTS.md

StarRailAssistant (SRA) automates *Honkai: Star Rail* via screen recognition. Windows-only; the game window must be
1920x1080 (fullscreen at 1080p, windowed above it) or recognition fails. Python 3.12 backend + .NET 10 frontend
(Avalonia desktop / ASP.NET Core server) + Vue 3 WebUI.

## Repository layout

- `main.py` — backend entry point (delegates to `SRACore/__main__.py`).
- `SRACore/` — CLI (`cli2.py`, cmd2-based), task/extension registries, operators (vision + input), notifications,
  services, utils, generated models.
- `tasks/` — task implementations.
- `extensions/` — extension implementations; `extensions/cw_plus/` is a large self-contained subsystem.
- `resources/img/**` — image templates, referenced only through `tasks/img.py` constants.
- `tests/` — pytest suite for the backend.
- `SRAFrontend/` — .NET solution: `SRAFrontend` (shared core), `SRAFrontend.Desktop` (Avalonia), `SRAFrontend.Server`
  (ASP.NET Core API + MCP).
- `SRAFrontend/srafrontend-webui/` — Vue 3 + Element Plus WebUI. **It has its own `AGENTS.md`; read it before working
  in that subtree.**
- `scripts/` — packaging, version bumping, model/localization generation, cleanup.

## Commands

Setup (Python 3.12 only, `requires-python >=3.12,<3.13`):

```bash
pip install -e ".[full]"   # full = desktop deps (pyautogui/pywin32/...); ".[dev]" for pytest
```

Run the backend:

```bash
python main.py                        # interactive CLI; self-elevates unless --no-admin
python main.py -c "task run Default"  # one-shot command(s); '+' chains several
```

Test:

```bash
python scripts/check_offline.py --output ../checks-new tests             # isolated state; new output directory
python -m pytest tests/test_main.py -q                                 # one file
python -m pytest tests/test_runner_blocking.py::test_start_and_wait_blocks_until_worker_finishes -q
```

Lint — blocking flake8 is configured in `.github/workflows/ci.yml`; there is no local config file:

```bash
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics   # blocking
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```

Frontend / server (from repo root):

```bash
dotnet run --project SRAFrontend/SRAFrontend.Desktop/SRAFrontend.Desktop.csproj
dotnet run --project SRAFrontend/SRAFrontend.Server/SRAFrontend.Server.csproj   # http://localhost:5073
```

Repo scripts:

```bash
npm run build -- --output ../build-new   # safe local fork build; no publishing
npm run modelgen   # regenerate SRACore/models/*.py from the C# models
npm run pyl10nc    # regenerate localization from SRACore/localization/resource.toml
npm run ver | ver:release | ver:patch | ver:pre
npm run clean      # recursively drop __pycache__
```

## Architecture

**Frontend ↔ backend is CLI-over-stdio.** The frontend spawns the Python backend as a child process and writes commands
to its stdin; there is no private IPC protocol. `-c`/repl input is appended to `sys.argv` and executed by
`SRACore/cli2.py`. Every command accepts `--json` and then prints the `{success, message, data}` envelope
(`SRACore/cli2.py::output`) that the HTTP API returns as `R`. `SRAFrontend/SRAFrontend/Services/LocalBackendService.cs`
holds the exact commands issued (`task run <config>`, `task status --json`, `operator call <method> '<json>' --json`,
`extension schema <id> --json`, …). **Changing a `--json` payload shape is a cross-language API change** — update
`LocalBackendService.cs` and the WebUI together.

**Server surface.** `SRAFrontend.Server` exposes `/api/**` REST, `/openapi/v1.json`, Swagger in Debug, the static
WebUI, and MCP tools at `/mcp` (`McpController.cs`: `sra_screenshot`, `sra_task_run`, `sra_operator_call`,
`sra_config_update`, …). The WebUI generates its task and settings forms from the OpenAPI schema, so backend config
models are the source of truth for the web UI.

**Dynamic imports.** `tasks/` and `extensions/` are not packages (no `__init__.py`). `SRACore.util.dynamic_import`
and `load_extensions()` scan `*.py` and import them, relying on `main.py` putting cwd on `sys.path`. Both are
therefore run from the repo root and read paths like `tasks/config/trailblaze_power.toml` and `resources/img/...`
**relative to cwd**.

**Registries.** Tasks use `@task(order=N)`, extensions use
`@extension(extension_id=..., background=...)` (`SRACore/task/__init__.py`, `SRACore/extension/__init__.py`).
Registration happens at import time, so dropping a file into `tasks/` or `extensions/` is usually all that is needed;
`task reload` / `extension reload` re-import in place for hot reload. Extension config models are Pydantic models
taken from the decorator's generic parameter and served as JSON Schema for form generation.

**Task contract.** Subclass `BaseTask` and implement `run() -> bool` (`False` = failure). `TaskManager.run()` walks
the enabled tasks of each config, calls `on_start`/`on_failed`/`on_completed` (which fan out to notifications) and, on
failure, delegates to `SRACore/util/task_recovery.py` to kill and relaunch the game before retrying the same config.
`TaskManager` and `ExtensionRunner` both subclass `SRACore/thread/runner.py::Runner` and **share one global work
thread**: at most one task or extension runs at a time, and `task stop` must request the stop on *both* runners.

**Vision and input.** Everything goes through `IOperator` (`SRACore/operators/ioperator.py`): template matching
(`locate`, `locate_all`, `locate_any`, `click_img`, `wait_img`), RapidOCR (`ocr`, `ocr_match`, `ocr_boxes`), HSV
color and rectangle detection. Implementations are `Operator` (PyAutoGUI/PyWin32, local game) and `BrowserOperator`
(Selenium, cloud game), chosen by `OperatorFactory`. `WindowContext` is shared between instances and `full_screen`
switches coordinates from window-relative to whole-screen. **Coordinate rule:** `int` args are absolute pixels,
`float` args are ratios (0–1) of the window; offsets follow the same convention.

**State on disk.** `%APPDATA%/SRA` (Linux: `~/.config/SRA`) holds `settings.json`, `configs/<Name>.json`, `cache.json`
and `cache/…` (`SRACore/util/const.py`, mirrored by `SRAFrontend/SRAFrontend/Data/DataPath.cs`); frontend and backend
read and write the **same** files. Python-side access goes through `SRACore/util/data_persister.py`, which also
migrates legacy config shapes. Runtime logs and failure screenshots go to the repo-local `log/` directory (gitignored).

## Conventions

- **Language.** Preserve the existing Chinese code/comment conventions and the localization boundary.
  This fork targets Russian-speaking users: `README.md` and `README.ru.md` are the same Russian landing page.
  `README.zh.md` retains the Chinese upstream document; `README.en.md` retains English with a fork notice.
  `README_RU.md` is the extended Russian guide. Keep language-switch links valid. Commit messages remain conventional.
- **Generated files — never hand-edit.** `SRACore/models/app_settings.py` and `SRACore/models/tasks_config.py` come
  from `SRAFrontend/SRAFrontend/Models/*.cs` via `npm run modelgen`; `SRACore/localization/resource.py`,
  `resource_zh-cn.json` and `resource_en-us.json` come from `resource.toml` via `npm run pyl10nc`. Edit the C# model
  or the TOML, then regenerate. WebUI `ResX` localization is updated by hand.
- **Version lives in three files**: `SRACore/util/const.py` (`VERSION`, which drives `pyproject.toml`),
  `package.json` and `SRAFrontend/SRAFrontend/Models/AppSettings.cs`. Change them together with `npm run ver`.
- **Localization** is attribute-style on the `Resource` singleton (`Resource.cli_intro`), resolved by
  `__getattribute__` from the generated JSON, with `str.format` placeholders in the TOML values.
- **Logging** uses `loguru` (`SRACore/util/logger.py`); do not add `print` for diagnostics.
- **Errors** use the coded enum in `SRACore/util/errors.py` (`SRA-XXXX-YYYY`, level prefixes 1xxx system … 9xxx
  other). `ThreadStoppedError` is the cooperative-stop signal recognized by `Runner` and the operators.
- **Types**: `from __future__ import annotations`, `StrEnum`, dataclasses and `# pyright: ignore[...]` markers around
  the `@task`/`@extension` decorators are the house style; follow it rather than loosening types.
- **Adding a user-visible field** means changing the backend model/schema: desktop Views bind to task configs and the
  WebUI renders from OpenAPI, so both follow the backend.
- **Fork releases.** Update `CHANGELOG_RU.md` and `docs/RELEASE_NOTES.ru.md`; keep the historical upstream
  `ChangeLog2.0.md`. `FORK_VERSION` is separate from the internal app version. Active workflows only run CI
  or create manual build artifacts. Six inherited publishing workflows are archived as `.disabled` files.
  Do not use upstream `scripts/package.py` for fork publication: it can upload to R2. Follow `docs/PUBLISHING.ru.md`.

## Known issues

Historical upstream test drift has been corrected; failures are not an accepted baseline for this fork.
See `docs/TESTING.ru.md` for exact checked revisions and counts. PERF-003 shop retries remain research, not a
completed optimization. Never weaken unknown-identity, two-fresh-frame, TTL, purchase or stop guards.
Offline checks do not prove full-game completion or a whole-party speedup. Do not start the game/tasks without consent.
