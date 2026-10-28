"""Recorded geometry with reviewed portrait/badge pixels at search boundaries."""
from __future__ import annotations

import json

from PIL import Image

from extensions.cw_plus.paths import CALIBRATION_ROOT
from tests.test_currency_wars_layout_performance import GOLDEN, make_vision

CONTROLS = {
    "left_search_corner": (0, -10, -10, 0),
    "right_search_corner": (5, 10, 10, 0),
    "half_pixel_robot": (2, 0.5, 0, 1),
    "half_pixel_visored": (4, 9.5, -9, 2),
}


def make_projection_control(tmp_path, name):
    reader, operator = make_vision(tmp_path, ["no_badge"])
    frame = operator.frames[0].copy()
    profile = json.loads((CALIBRATION_ROOT / "backend_locked_support.json").read_text(encoding="utf-8"))
    index, dx, dy, variant = CONTROLS[name]
    position = GOLDEN["cases"]["no_badge"]["result"]["positions"][index]
    rx, ry = profile["position"]
    shift_x = round((position[0] - rx) * 1920)
    shift_y = round((position[1] - ry) * 1080)
    portrait = ([profile["templates"][0]] + profile["portrait_variants"])[variant]
    for template in (portrait, profile["templates"][1]):
        left, top, _, _ = template["relative_box"]
        x = round((rx + left) * 1920) + shift_x
        y = round((ry + top) * 1080) + shift_y
        with Image.open(CALIBRATION_ROOT / template["path"]) as crop:
            frame.paste(crop.convert("RGB"), (x + int(dx), y + dy))
    if dx != int(dx):
        # Fractional translation of the whole recorded image retains actual
        # border evidence; the baseline, not this builder, decides acceptance.
        frame = frame.transform(frame.size, Image.Transform.AFFINE,
                                (1, 0, -(dx - int(dx)), 0, 1, 0),
                                resample=Image.Resampling.BILINEAR)
    operator.frames = [frame]
    return reader, operator
