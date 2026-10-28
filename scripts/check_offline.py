"""Run pytest with isolated writable state; never start SRA or send game input."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for logs and isolated state")
    parser.add_argument("targets", nargs="*", default=["tests"])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        target = output / "state" / key
        target.mkdir(parents=True)
        environment[key] = str(target)
    for key in ("SRA_CW_RUNTIME_ROOT", "SRA_CW_PERF", "PYTEST_ADDOPTS"):
        environment.pop(key, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    command = [sys.executable, "-B", "-X", "utf8", "-m", "pytest", *args.targets,
               "-q", "-p", "no:cacheprovider", "--tb=short", "--junitxml", str(output / "pytest.xml"),
               "--basetemp", str(output / "pytest-temp")]
    with (output / "pytest.log").open("xb") as stream:
        result = subprocess.run(command, cwd=ROOT, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT)
    print((output / "pytest.log").read_text(encoding="utf-8", errors="replace"))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
