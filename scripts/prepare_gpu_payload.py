"""Prepare a relative-path DirectML overlay from the vendored official wheel.

Build-time tool only: does not install packages, mutate the supplied application,
download models, or send game input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

SOURCE = Path(__file__).resolve().parents[1]
WHEEL = "onnxruntime_directml-1.24.4-cp312-cp312-win_amd64.whl"
EXPECTED = "f2ecb68b7b7b259d2ef3112ae760149f9b5a1e7c0fbb73d539da6250a648a614"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wheel = SOURCE / "vendor" / WHEEL
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == EXPECTED
    assert not args.output.exists(), "Do not overwrite an existing payload"
    config = (args.app / "rapidocr/config.yaml").read_bytes()
    assert config.count(b"use_dml: false") + config.count(b"use_dml: true") == 1
    config = config.replace(b"use_dml: false", b"use_dml: true", 1)
    args.output.mkdir(parents=True)
    entries = {}
    with ZipFile(wheel) as archive:
        assert archive.testzip() is None
        for name in ("onnxruntime_pybind11_state.pyd", "onnxruntime.dll",
                     "onnxruntime_providers_shared.dll", "DirectML.dll"):
            relative = "onnxruntime/capi/" + name
            entries[relative] = archive.read(relative)
        for name in ("LICENSE", "ThirdPartyNotices.txt"):
            entries["onnxruntime/directml/" + name] = archive.read("onnxruntime/" + name)
    entries["rapidocr/config.yaml"] = config
    entries["GPU_OCR.ru.md"] = (SOURCE / "GPU_OCR.ru.md").read_bytes()
    metadata = dict(provider="DmlExecutionProvider", enabled=True,
        compiled_onnx_api="1.27.0", native_onnx_runtime="1.24.4", rapidocr="3.9.1",
        official_wheel=WHEEL, official_wheel_sha256=EXPECTED,
        vendor_url="https://pypi.org/project/onnxruntime-directml/1.24.4/",
        python_core_recompiled=False, models_changed=False,
        runtime_sha256={name: hashlib.sha256(data).hexdigest() for name, data in entries.items()})
    entries["gpu_ocr_runtime.json"] = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for name, content in entries.items():
        path = args.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(json.dumps(dict(files=len(entries), output=args.output.as_posix(), downloads=False), indent=2))


if __name__ == "__main__":
    main()
