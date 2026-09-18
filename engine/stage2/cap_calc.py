from __future__ import annotations

"""Geometric helpers for CAP handling-facility design capacity (설계용량, m3).

These are plain geometry formulas for the common vessel shapes. They do not
model dished/elliptical heads, internals, or fill-level derating; where the
manual prescribes a different 내용적 formula for a specific vessel type, the
company-confirmed design capacity must be entered instead.
"""

import math

SHAPES = {
    "vertical_cylinder": "수직 원통형(평판 상·하부)",
    "horizontal_cylinder": "수평 원통형(평판 양단)",
    "sphere": "구형",
    "box": "직육면체",
}

# Required dimension names (meters) per shape.
SHAPE_DIMENSIONS = {
    "vertical_cylinder": ("diameter_m", "height_m"),
    "horizontal_cylinder": ("diameter_m", "length_m"),
    "sphere": ("diameter_m",),
    "box": ("length_m", "width_m", "height_m"),
}


def internal_volume_m3(shape: str, **dims: float) -> float | None:
    """Return the geometric internal volume in m3, or None if inputs are unusable."""
    needed = SHAPE_DIMENSIONS.get(shape)
    if needed is None:
        return None
    values = []
    for name in needed:
        value = dims.get(name)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        values.append(number)

    if shape in {"vertical_cylinder", "horizontal_cylinder"}:
        diameter, length = values
        return math.pi / 4.0 * diameter**2 * length
    if shape == "sphere":
        return math.pi / 6.0 * values[0] ** 3
    length, width, height = values
    return length * width * height
