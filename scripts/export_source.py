"""Export a source-only fork tree. Never read AppData, run the app or publish files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "863509072bf2011b4d5a3e3d71072b6cd269637e"
ROOT_FILES = {
    ".gitattributes", ".gitignore", "AGENTS.md", "CHANGELOG_RU.md", "ChangeLog2.0.md",
    "CONTRIBUTING.md", "FORK_VERSION", "FORK.md", "GPU_OCR.ru.md", "LICENSE", "main.py",
    "NOTICE", "package.json", "pyproject.toml", "README_RU.md", "README.en.md", "README.md",
    "README.ru.md", "README.zh.md",
    "SECURITY.md", "THIRD_PARTY_NOTICES.md", "UPSTREAM.md", "ocr-models.json", "FORK_CHANGES.json",
}
ROOT_DIRS = {".github", "docs", "extensions", "resources", "scripts", "setup", "SRACore",
             "SRAFrontend", "tasks", "tests", "vendor"}
EXCLUDED_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "bin", "obj",
    "dist", "main.dist", "main.build", "build", "log", "logs", "reports", "evidence",
    "TestResults", ".vs", ".idea", ".venv", ".vscode", "output", ".pnpm-store", ".agents",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pdb", ".log", ".exe", ".dll", ".pyd", ".zip",
                     ".tsbuildinfo", ".user", ".key", ".pem"}
PUBLIC_PLUS_STRATEGIES = {
    "himeko_level5_quality_level7_two_star_20261018.json",
    "silver_wolf_lv999_budget_economy_20261017.json",
    "himeko_global_europe_20261026.json",
    "货币战争增强版_标准配置填写规范.annotated.jsonc",
}


def digest(path: Path, algorithm="sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def source_files(root: Path = ROOT) -> dict[str, Path]:
    result = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        relative_parent = parent.relative_to(root)
        directories[:] = sorted(name for name in directories if name not in EXCLUDED_DIRS
                                 and not name.endswith(".egg-info")
                                 and (parent != root or name in ROOT_DIRS)
                                 and (relative_parent.parts, name) != (("SRAFrontend", "SRAFrontend.Server"), "wwwroot"))
        for name in directories:
            if (parent / name).is_symlink():
                raise ValueError(f"Source symlink requires review: {(parent / name).relative_to(root)}")
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(root)
            if relative.parts[:3] == ("extensions", "cw_plus", "strategies") and name not in PUBLIC_PLUS_STRATEGIES:
                continue
            if parent == root and name not in ROOT_FILES:
                continue
            demo_config = relative.as_posix() == "SRAFrontend/srafrontend-webui/.env.demo"
            if path.suffix.lower() in EXCLUDED_SUFFIXES or name == ".eslintcache" or (
                    name.startswith(".env") and not demo_config):
                continue
            if path.is_symlink():
                raise ValueError(f"Source symlink requires review: {relative}")
            if path.stat().st_size >= 100 * 1024 * 1024:
                raise ValueError(f"File exceeds GitHub regular Git limit: {relative}")
            result[relative.as_posix()] = path
    for required in ("LICENSE", "main.py", "pyproject.toml", "FORK_VERSION"):
        if required not in result:
            raise ValueError(f"Required source missing: {required}")
    return result


def upstream_files(path: Path) -> dict[str, str]:
    result = {}
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Invalid upstream ZIP CRC")
        for entry in archive.infolist():
            parts = PurePosixPath(entry.filename).parts
            if entry.is_dir() or len(parts) < 2:
                continue
            if PurePosixPath(entry.filename).is_absolute() or ".." in parts:
                raise ValueError("Unsafe upstream member")
            name = PurePosixPath(*parts[1:]).as_posix()
            if name in result:
                raise ValueError(f"Duplicate upstream member: {name}")
            result[name] = hashlib.sha256(archive.read(entry)).hexdigest()
    if "LICENSE" not in result or "main.py" not in result:
        raise ValueError("Expected official source ZIP with a single root directory")
    return result


def export(output: Path, *, root: Path = ROOT, upstream_zip: Path | None = None):
    output = output.resolve()
    root = root.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("Output must be a new directory outside the source tree")
    files = source_files(root)
    if upstream_zip is not None:
        files.pop("FORK_CHANGES.json", None)
    hashes = {name: digest(path) for name, path in files.items()}
    output.mkdir(parents=True)
    for name, path in files.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if digest(destination) != hashes[name]:
            raise RuntimeError(f"Source changed during export: {name}")
    if upstream_zip is not None:
        upstream = upstream_files(upstream_zip)
        if hashes["LICENSE"] != upstream["LICENSE"]:
            raise ValueError("Upstream license must be retained byte-for-byte")
        diff = {
            "schema": 1, "prepared_date": "2026-10-28", "base_tag": "v2.25.0-beta.1",
            "base_commit": BASE_COMMIT, "upstream_zip_sha256": digest(upstream_zip),
            "fork_version": (root / "FORK_VERSION").read_text(encoding="utf-8").strip(),
            "added": [{"path": n, "sha256": hashes[n]} for n in sorted(hashes.keys() - upstream.keys())],
            "changed": [{"path": n, "upstream_sha256": upstream[n], "sha256": hashes[n]}
                        for n in sorted(hashes.keys() & upstream.keys()) if hashes[n] != upstream[n]],
            "removed_from_source_export": sorted(upstream.keys() - hashes.keys()),
            "unchanged_count": sum(hashes[n] == upstream[n] for n in hashes.keys() & upstream.keys()),
            "note": "Content inventory, not a Git commit or proof of GitHub fork-network linkage.",
        }
        path = output / "FORK_CHANGES.json"
        path.write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        hashes[path.name] = digest(path)
    manifest = {"schema": 1, "algorithm": "sha256", "files": hashes,
                "note": "Manifest excludes itself. Private data/caches/build outputs are not exported."}
    (output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def archive_source(directory: Path, destination: Path):
    if destination.exists():
        raise FileExistsError(destination)
    with ZipFile(destination, "x", compression=ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory).as_posix())
    with ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Source ZIP CRC check failed")
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{digest(destination)}  {destination.name}\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream-zip", type=Path)
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    manifest = export(args.output, upstream_zip=args.upstream_zip)
    if args.zip:
        archive_source(args.output, args.zip)
    print(json.dumps({"exported_files": len(manifest["files"]) + 1,
                      "output": str(args.output), "published": False}, indent=2))


if __name__ == "__main__":
    main()
