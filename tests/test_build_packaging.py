"""Windows delivery excludes build caches without dropping real notices or helpers."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_ru


@pytest.mark.parametrize("name", [
    "SRA.exe", "SRA-cli.exe", "onnxruntime/capi/DirectML.dll",
    "selenium/webdriver/common/windows/selenium-manager.exe",
    "selenium/webdriver/common/mutation-listener.js",
    "third_party/python/packaging/packaging.dist-info/licenses/LICENSE.APACHE",
])
def test_runtime_policy_preserves_windows_dependencies_and_licenses(name):
    assert build_ru.include_runtime_file(Path(name))


@pytest.mark.parametrize("name", [
    "module/__pycache__/file.cpython-312.pyc", "module/file.PYC", "module/file.pyo", "SRA.pdb",
    "third_party/python/packaging/packaging/licenses/__pycache__/_spdx.cpython-312.pyc",
    "selenium/webdriver/common/linux/selenium-manager",
    "selenium/webdriver/common/macos/selenium-manager", "../LICENSE",
])
def test_runtime_policy_rejects_caches_and_other_os_helpers(name):
    assert not build_ru.include_runtime_file(Path(name))


@pytest.mark.parametrize("name", [
    "package.dist-info/licenses/LICENSE", "package.dist-info/licenses/LICENSE.APACHE",
    "package.dist-info/licenses/LICENSE.BSD", "package/NOTICE.txt", "COPYING",
    "THIRD-PARTY-NOTICES.txt", "licenses/attribution.md", "licenses/third-party/MIT",
])
def test_license_policy_preserves_actual_legal_material(name):
    assert build_ru.is_license_material(Path(name))


@pytest.mark.parametrize("name", [
    "packaging/licenses/__init__.py", "packaging/licenses/_spdx.py",
    "packaging/licenses/__pycache__/_spdx.cpython-312.pyc",
    "nuitka/reports/LicenseReport.rst.j2", "licenses/worker.exe", "../LICENSE",
    "package/ordinary.py", "package/LicenseReport.rst",
])
def test_license_policy_rejects_source_cache_and_build_templates(name):
    assert not build_ru.is_license_material(Path(name))


def test_overlay_excludes_other_os_without_removing_windows_manager(tmp_path):
    source = tmp_path / "input"
    destination = tmp_path / "runtime"
    names = {
        "selenium/webdriver/common/windows/selenium-manager.exe": b"windows",
        "selenium/webdriver/common/linux/selenium-manager": b"linux",
        "selenium/webdriver/common/macos/selenium-manager": b"macos",
        "module/__pycache__/cached.pyc": b"cache",
        "module/notice.txt": b"keep",
    }
    for name, data in names.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    build_ru.overlay(source, destination)
    assert {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()} == {
        "selenium/webdriver/common/windows/selenium-manager.exe", "module/notice.txt"}


def test_license_collection_does_not_copy_code_from_directory_named_licenses(tmp_path, monkeypatch):
    package = tmp_path / "installed"
    entries = ["pkg.dist-info/licenses/LICENSE", "pkg/licenses/__init__.py",
               "pkg/licenses/__pycache__/__init__.pyc", "pkg/reports/LicenseReport.rst.j2"]
    for name in entries:
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")
    distribution = SimpleNamespace(metadata={"Name": "test-package"}, version="1", files=entries,
                                   locate_file=lambda entry: package / entry)
    monkeypatch.setattr(build_ru.metadata, "distributions", lambda: [distribution])
    runtime = tmp_path / "runtime"
    assert build_ru.licenses(runtime, nuget_assets=[]) == {"test-package": "1"}
    assert {path.relative_to(runtime).as_posix() for path in runtime.rglob("*") if path.is_file()} == {
        "third_party/python/test-package/pkg.dist-info/licenses/LICENSE", "third_party/dependencies.json"}
