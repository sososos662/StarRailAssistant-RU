"""Fresh Windows x64 fork build. No upload, installation or application startup.

Python 3.12 with .[full] and Nuitka; .NET 10 SDK; Node/pnpm are build tools only.
Output must not exist. Existing main.dist, installed SRA and AppData are never inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile

from export_source import archive_source, digest, export, source_files

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.25.0-beta.1"


def run(output, label, command, *, cwd=ROOT, environment=None):
    print("START", label, flush=True)
    log = output / "logs" / (label + ".log")
    with log.open("xb") as stream:
        completed = subprocess.run([str(x) for x in command], cwd=cwd, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, timeout=5400)
    print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]), flush=True)
    if completed.returncode:
        raise RuntimeError(f"{label} failed ({completed.returncode}); see {log}")


def overlay(source, destination):
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pdb", ".pyc"}:
            continue
        if path.name == "web.config" or path.name.startswith("opencv_videoio_ffmpeg"):
            continue
        target = destination / path.relative_to(source)
        if target.exists() and digest(target) != digest(path):
            raise RuntimeError(f"Conflicting build outputs: {target.relative_to(destination)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def model_payload(args, output, rapidocr_package, specs):
    available = args.models_dir or rapidocr_package / "models"
    target = output / "models"
    target.mkdir()
    for model in specs:
        source = available / model["file"]
        destination = target / model["file"]
        if source.is_file():
            shutil.copyfile(source, destination)
        elif args.allow_downloads:
            with urllib.request.urlopen(model["url"], timeout=120) as response, destination.open("xb") as stream:
                shutil.copyfileobj(response, stream)
        else:
            raise FileNotFoundError(f"Model missing: {source}; pass --models-dir or explicitly --allow-downloads")
        if digest(destination) != model["sha256"]:
            raise ValueError(f"Model SHA256 mismatch: {model['file']}")
    return target


def licenses(runtime, *, nuget_assets=None):
    versions = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        versions[name] = distribution.version
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_.")
        for entry in distribution.files or []:
            relative = Path(entry)
            if ".." in relative.parts or not any(
                    p.lower().startswith(("license", "notice", "thirdpartynotice", "copying"))
                    for p in relative.parts):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            target = runtime / "third_party/python" / safe_name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    nuget = {}
    asset_paths = list(nuget_assets) if nuget_assets is not None else [
        ROOT / "SRAFrontend" / project / "obj/project.assets.json"
        for project in ("SRAFrontend", "SRAFrontend.Desktop", "SRAFrontend.Server")]
    for assets_path in asset_paths:
        if not assets_path.is_file():
            continue
        assets = json.loads(assets_path.read_text(encoding="utf-8-sig"))
        for identifier, library in assets.get("libraries", {}).items():
            if library.get("type") != "package":
                continue
            nuget[identifier] = library.get("sha512")
            for folder in assets.get("packageFolders", {}):
                package = Path(folder) / library["path"]
                if not package.is_dir():
                    continue
                for source in package.rglob("*"):
                    if not source.is_file() or not (source.suffix == ".nuspec" or source.name.lower().startswith(
                            ("license", "notice", "thirdpartynotice", "copying"))):
                        continue
                    target = runtime / "third_party/nuget" / identifier / source.relative_to(package)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    target = runtime / "third_party/dependencies.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"python_build_environment": versions, "nuget": nuget}, indent=2) + "\n",
                      encoding="utf-8")
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory outside the source tree")
    parser.add_argument("--models-dir", type=Path, help="Reuse existing model files after SHA256 verification")
    parser.add_argument("--ocr", choices=("directml", "cpu"), default="directml")
    parser.add_argument("--dotnet", default=os.environ.get("DOTNET_EXE", "dotnet"))
    parser.add_argument("--pnpm", default="pnpm")
    parser.add_argument("--allow-downloads", action="store_true", help="Allow model/compiler and package restore downloads")
    parser.add_argument("--plan", action="store_true", help="Validate inputs and print plan without building or writing")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error("--output must not exist and must be outside the source tree")
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32":
        parser.error("Build requires Windows x64 Python 3.12")
    if sys.maxsize <= 2**32:
        parser.error("64-bit Python required")
    for package, expected in (("rapidocr", "3.9.1"), ("onnxruntime", "1.27.0")):
        if metadata.version(package) != expected:
            parser.error(f"Build API requires {package}=={expected}")
    metadata.version("nuitka")
    dotnet = shutil.which(args.dotnet)
    pnpm_path = shutil.which(args.pnpm)
    pnpm = [pnpm_path] if pnpm_path else []
    if not pnpm and args.pnpm == "pnpm" and shutil.which("corepack"):
        pnpm = [shutil.which("corepack"), "pnpm"]
    if not dotnet or not pnpm:
        parser.error(".NET SDK and pnpm must be available (or pass --dotnet / --pnpm)")
    spec = importlib.util.find_spec("rapidocr")
    rapidocr_package = Path(spec.origin).parent
    models = json.loads((ROOT / "ocr-models.json").read_text(encoding="utf-8"))["models"]
    available = args.models_dir or rapidocr_package / "models"
    for model in models:
        path = available / model["file"]
        if path.exists() and digest(path) != model["sha256"]:
            parser.error(f"Model SHA256 mismatch: {model['file']}")
        if not path.is_file() and not args.allow_downloads:
            parser.error(f"Missing {model['file']}; use --models-dir or --allow-downloads")
    inputs = {name: digest(path) for name, path in source_files().items()}
    revision = (ROOT / "FORK_VERSION").read_text(encoding="utf-8").strip()
    if args.plan:
        print(json.dumps({"revision": revision, "ocr": args.ocr, "source_files": len(inputs),
                          "models": models, "fresh_backend": True, "fresh_publish": True,
                          "uploads": False, "starts_application": False}, indent=2))
        return
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    environment = os.environ.copy()
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", PYTHONDONTWRITEBYTECODE="1")
    if not args.allow_downloads:
        environment["COREPACK_ENABLE_NETWORK"] = "0"
    for key in ("APPDATA", "TEMP", "TMP"):
        folder = output / "state" / key
        folder.mkdir(parents=True)
        environment[key] = str(folder)
    # LOCALAPPDATA retains the existing Nuitka compiler cache; no system installation.
    model_dir = model_payload(args, output, rapidocr_package, models)
    webui = ROOT / "SRAFrontend/srafrontend-webui"
    if not (webui / "node_modules").is_dir() and not args.allow_downloads:
        raise RuntimeError("Install WebUI dependencies first, or explicitly allow downloads")
    if args.allow_downloads:
        run(output, "webui-install", [*pnpm, "install", "--frozen-lockfile"], cwd=webui, environment=environment)
    run(output, "webui-build", [*pnpm, "build"], cwd=webui, environment=environment)
    backend = output / "backend"
    command = [sys.executable, "-B", "-m", "nuitka", "--standalone", "--mingw64", "--jobs=4",
               "--windows-console-mode=force", "--windows-icon-from-ico=resources/SRAicon.ico",
               "--company-name=StarRailAssistant Team", "--product-name=StarRailAssistant",
               "--file-version=2.25.0", "--product-version=2.25.0", "--copyright=Copyright 2024 Shasnow",
               "--file-description=StarRailAssistant Component", "--output-filename=SRA-cli", "--remove-output",
               "--output-dir=" + str(backend), "--include-package=selenium.webdriver.edge",
               "--include-package=selenium.webdriver.firefox", "--include-package=selenium.webdriver.chrome",
               "--include-package=selenium.webdriver.common.action_chains"]
    if args.allow_downloads:
        command.append("--assume-yes-for-downloads")
    run(output, "backend", [*command, "main.py"], environment=environment)
    dotnet_artifacts = output / "dotnet-artifacts"
    local_feed = output / "empty-nuget-feed"
    local_feed.mkdir()
    for project, label in (("SRAFrontend.Desktop", "desktop"), ("SRAFrontend.Server", "server")):
        project_path = ROOT / "SRAFrontend" / project / (project + ".csproj")
        restore = [dotnet, "restore", project_path, "-r", "win-x64", "--artifacts-path", dotnet_artifacts,
                   "-p:SelfContained=true", "-p:NuGetAudit=false"]
        if not args.allow_downloads:
            restore.extend(["--source", local_feed])
        run(output, "restore-" + label, restore, environment=environment)
        command = [dotnet, "publish", project_path,
                   "-c", "Release", "-r", "win-x64", "--self-contained", "true", "-t:Rebuild",
                   "-p:DebugType=None", "-p:DebugSymbols=false",
                   "-p:PathMap=" + str(ROOT) + "=/_/src", "--artifacts-path", dotnet_artifacts, "--no-restore",
                   "-p:IncludeNativeLibrariesForSelfExtract=true", "-o", output / label]
        run(output, label, command, environment=environment)
    runtime = output / "runtime"
    runtime.mkdir()
    for folder in (backend / "main.dist", output / "desktop", output / "server"):
        overlay(folder, runtime)
    for name, path in source_files().items():
        if name.split("/")[0] not in {"extensions", "tasks", "resources"} and name not in {
                "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "FORK_VERSION", "README_RU.md",
                "README.md", "README.ru.md", "README.zh.md", "README.en.md", "FORK.md", "UPSTREAM.md", "CHANGELOG_RU.md", "SECURITY.md",
                "GPU_OCR.ru.md", "ocr-models.json"} and not name.startswith("docs/"):
            continue
        target = runtime / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    localization = runtime / "SRACore/localization"
    localization.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "SRACore/localization").glob("*.json"):
        shutil.copyfile(path, localization / path.name)
    ocr = runtime / "rapidocr"
    ocr.mkdir(exist_ok=True)
    shutil.copytree(model_dir, ocr / "models", dirs_exist_ok=True)
    for name in ("config.yaml", "default_models.yaml"):
        shutil.copyfile(rapidocr_package / name, ocr / name)
    if args.ocr == "directml":
        payload = output / "gpu-payload"
        run(output, "directml", [sys.executable, "-B", ROOT / "scripts/prepare_gpu_payload.py",
                                  "--app", runtime, "--output", payload], environment=environment)
        for path in payload.rglob("*"):
            if path.is_file():
                target = runtime / path.relative_to(payload)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    system = Path(os.environ["WINDIR"]) / "System32"
    for name in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if not (runtime / name).is_file():
            shutil.copyfile(system / name, runtime / name)
    versions = licenses(runtime, nuget_assets=dotnet_artifacts.rglob("project.assets.json"))
    if inputs != {name: digest(path) for name, path in source_files().items()}:
        raise RuntimeError("Source changed while building; candidate must not be published")
    for name in ("SRA-cli.exe", "SRA.exe", "SRA-server.exe"):
        if not (runtime / name).is_file():
            raise RuntimeError(f"Required build output missing: {name}")
    info = {"schema": 1, "fork_version": revision, "app_version": VERSION, "ocr": args.ocr,
            "source_sha256": inputs, "python_packages": versions, "fresh_backend": True,
            "note": "Locally built artifact. Not a full-game acceptance or byte-reproducible build claim."}
    (runtime / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    manifest = {p.relative_to(runtime).as_posix(): digest(p, "md5") for p in sorted(runtime.rglob("*")) if p.is_file()}
    (runtime / "manifest.md5.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts = output / "artifacts"
    artifacts.mkdir()
    name = "StarRailAssistant_" + revision + "_win-x64_" + args.ocr
    archive_path = artifacts / (name + ".zip")
    with ZipFile(archive_path, "x", compression=ZIP_DEFLATED) as archive:
        for path in sorted(runtime.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(runtime).as_posix())
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Runtime ZIP CRC failed")
    archive_path.with_suffix(".zip.sha256").write_text(f"{digest(archive_path)}  {archive_path.name}\n", encoding="ascii")
    export(output / "source")
    archive_source(output / "source", artifacts / (name + "_Source.zip"))
    print("BUILD COMPLETE:", artifacts, "(not published; acceptance tests still required)")


if __name__ == "__main__":
    main()
