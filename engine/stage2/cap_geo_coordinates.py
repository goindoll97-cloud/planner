"""Validate incident-origin coordinates; a mailing address is never a coordinate.

The form accepts numeric WGS84 pairs in either historical 'latitude,longitude'
or map-style 'longitude,latitude' order. The original text is retained in the
statutory form, while a missing/invalid value stays blank for human review.
"""
from __future__ import annotations

import math
import re


def valid_origin(value: object) -> bool:
    text = str(value or "").strip().strip("()[]")
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2 or not all(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", x) for x in parts):
        return False
    first, second = (float(x) for x in parts)
    if not math.isfinite(first) or not math.isfinite(second):
        return False
    return ((-90 <= first <= 90 and -180 <= second <= 180) or
            (-180 <= first <= 180 and -90 <= second <= 90))


def confirmed_origin(value: object) -> str:
    """Return a numeric coordinate pair verbatim, never a guessed address point."""
    return str(value or "").strip() if valid_origin(value) else ""
