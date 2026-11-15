"""Render the stored GIS site boundary and nearby receptors in Form 8's map cell.

A self-contained, offline PNG replaces the old text-only location summary.
It uses only a user-confirmed site polygon and current GIS source geometries;
it never geocodes an address or guesses coordinates during DOCX export.
Numbered pins match the reviewed Form 8 list. Unreviewed GIS candidates are
shown as unnumbered hollow pins and cannot be mistaken for approved targets.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import nearest_points, transform

from . import cap_form8_workspace as f8
from . import cap_surroundings as surrounding
from .project import Stage2Project

BUFFER_M = 500
WIDTH, HEIGHT = 1320, 780


@dataclass(frozen=True)
class Form8Map:
    png: bytes
    placed: int
    missing: int
    provisional: int
    source: str


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _numeric_wgs84(raw: object) -> tuple[float, float] | None:
    """Return (longitude, latitude) only for plausible Korean WGS84 pairs."""
    try:
        first, second = [float(text.strip()) for text in str(raw).split(",")]
    except (ValueError, TypeError):
        return None
    if not all(math.isfinite(x) for x in (first, second)):
        return None
    lat, lon = (first, second) if 33 <= first <= 39 and 124 <= second <= 132 else (second, first)
    return (lon, lat) if 33 <= lat <= 39 and 124 <= lon <= 132 else None


def _outline(draw: ImageDraw.ImageDraw, geom, screen, *, color, width: int, fill=None):
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for part in parts:
        if part.geom_type != "Polygon":
            continue
        points = [screen(x, y) for x, y in part.exterior.coords]
        if fill is not None:
            draw.polygon(points, fill=fill)
        draw.line(points, fill=color, width=width, joint="curve")
        for hole in part.interiors:
            inside = [screen(x, y) for x, y in hole.coords]
            if fill is not None:
                draw.polygon(inside, fill=(255, 255, 255))
            draw.line(inside, fill=color, width=max(width // 2, 2))


def _location(geometry: Mapping, projector, site_m, extent):
    try:
        geo = surrounding.checked_geometry(dict(geometry))
        metric = transform(projector, geo)
        if metric.is_empty or not metric.intersects(extent):
            return None
        # A river or large building footprint may cross the 500m area while
        # its representative point lies outside it. Plot the actual closest
        # point on the GIS geometry to the site, not an arbitrary centroid.
        point = nearest_points(site_m, metric)[1]
        return point if extent.covers(point) else None
    except (ValueError, TypeError):
        return None


def render_site_map(project: Stage2Project, reviewed_rows: list[dict], *,
                    draft: bool = False) -> Form8Map | None:
    """Draw the saved boundary, 500 m buffer and source-backed target pins.

    Returns None only when the user has not recorded a valid site polygon.
    """
    site = surrounding.boundary(project)
    if site is None:
        return None
    site_m = surrounding.metric_geometry(mapping(site))
    extent = site_m.buffer(BUFFER_M)
    if extent.is_empty:
        return None

    source_record = surrounding.boundary_record(project)
    source = str(source_record.get("source") or "사업장 경계(사용자 확인)")
    survey = surrounding.survey(project) if surrounding.is_current(project) else {}
    locations: dict[str, list[Any]] = {}
    forward = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform

    for raw in survey.get("objects", []):
        if not isinstance(raw, Mapping):
            continue
        name = f8._norm(raw.get("name"))
        if not name or not isinstance(raw.get("geometry"), Mapping):
            continue
        position = _location(raw["geometry"], forward, site_m, extent)
        if position is not None:
            locations.setdefault(name, []).append(position)

    def located(row: Mapping) -> Any | None:
        coords = _numeric_wgs84(row.get("좌표") or row.get("보호대상 좌표"))
        if coords:
            point = Point(*forward(*coords))
            if extent.covers(point):
                return point
        points = locations.get(f8._norm(row.get("보호대상 명칭")), [])
        if not points:
            return None
        # Same-name GIS objects may represent multiple nearby parts of a
        # facility. Prefer the measured boundary distance where available.
        try:
            distance = float(row.get("사업장 경계와 거리(m)"))
        except (ValueError, TypeError):
            distance = None
        if distance is not None and math.isfinite(distance):
            return min(points, key=lambda p: abs(site_m.distance(p) - distance))
        return min(points, key=site_m.distance)

    x0, y0, x1, y1 = extent.bounds
    map_left, map_top, map_right, map_bottom = 60, 75, WIDTH - 60, HEIGHT - 100
    map_w, map_h = map_right - map_left, map_bottom - map_top
    scale = min(map_w / max(x1 - x0, 1), map_h / max(y1 - y0, 1)) * 0.89
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sx, sy = (map_left + map_right) / 2, (map_top + map_bottom) / 2

    def screen(x: float, y: float) -> tuple[int, int]:
        return (round(sx + (x - cx) * scale), round(sy - (y - cy) * scale))

    image = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, WIDTH - 20, HEIGHT - 18), outline=(188, 195, 204), width=2)
    draw.text((46, 34), "SITE LOCATION / 500 m SURROUNDINGS", font=_font(27), fill=(35, 48, 65))

    # Simple measured grid: this is not a satellite/topographic base map.
    step = 100.0
    a = math.floor(x0 / step) * step
    while a <= x1:
        x, _ = screen(a, cy)
        if map_left <= x <= map_right:
            draw.line((x, map_top, x, map_bottom), fill=(237, 240, 244), width=1)
        a += step
    b = math.floor(y0 / step) * step
    while b <= y1:
        _, y = screen(cx, b)
        if map_top <= y <= map_bottom:
            draw.line((map_left, y, map_right, y), fill=(237, 240, 244), width=1)
        b += step

    _outline(draw, extent, screen, color=(55, 90, 134), width=4)
    _outline(draw, site_m, screen, color=(30, 54, 73), width=5, fill=(178, 193, 204))
    mx, my = screen(site_m.representative_point().x, site_m.representative_point().y)
    draw.text((mx + 8, my - 34), "SITE", font=_font(23), fill=(25, 42, 58))

    placed, missing = 0, 0
    for row in reviewed_rows:
        point = located(row)
        if point is None:
            missing += 1
            continue
        placed += 1
        x, y = screen(point.x, point.y)
        # Numbered *outline* pins are candidates written to the first draft,
        # not an assertion that a reviewer has legally confirmed them.
        if draft:
            draw.ellipse((x - 17, y - 17, x + 17, y + 17),
                         fill=(255, 255, 255), outline=(26, 65, 107), width=4)
        else:
            draw.ellipse((x - 17, y - 17, x + 17, y + 17),
                         fill=(26, 65, 107), outline=(255, 255, 255), width=3)
        label = str(row.get("일련번호") or placed)
        box = draw.textbbox((0, 0), label, font=_font(20))
        draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - 3),
                  label, font=_font(20), fill=(26, 65, 107) if draft else "white")

    # Unconfirmed GIS rows can be drawn for orientation only, never numbered.
    provisional = placed if draft else 0
    if not reviewed_rows:
        for row in f8.saved_rows(project):
            point = located(row)
            if point is None:
                continue
            x, y = screen(point.x, point.y)
            draw.ellipse((x - 9, y - 9, x + 9, y + 9), outline=(129, 141, 155), width=3)
            provisional += 1

    # North and metric scale provide orientation; the legend explicitly says
    # there is no background map, so the figure is not mislabeled as a base map.
    draw.line((WIDTH - 95, 105, WIDTH - 95, 157), fill=(20, 40, 65), width=4)
    draw.polygon(((WIDTH - 95, 92), (WIDTH - 106, 112), (WIDTH - 84, 112)), fill=(20, 40, 65))
    draw.text((WIDTH - 107, 66), "N", font=_font(23), fill=(20, 40, 65))
    bar_m = 100 if (x1 - x0) < 1000 else 200
    bar_px = bar_m * scale
    start_x, bar_y = 72, HEIGHT - 92
    draw.line((start_x, bar_y, start_x + bar_px, bar_y), fill=(30, 47, 66), width=5)
    draw.line((start_x, bar_y - 8, start_x, bar_y + 8), fill=(30, 47, 66), width=3)
    draw.line((start_x + bar_px, bar_y - 8, start_x + bar_px, bar_y + 8), fill=(30, 47, 66), width=3)
    draw.text((start_x, bar_y + 13), f"{bar_m} m", font=_font(20), fill=(30, 47, 66))
    draw.text((340, HEIGHT - 82), "OUTLINE: 500 m  |  SHADED: SITE", font=_font(19), fill=(43, 60, 78))
    draw.text((340, HEIGHT - 51),
              "NUMBER: DRAFT TARGET" if draft else "NUMBER: REVIEWED  |  RING: UNREVIEWED",
              font=_font(17), fill=(92, 104, 118))
    draw.text((WIDTH - 295, HEIGHT - 44), "GIS DRAFT / NO BASEMAP", font=_font(16), fill=(113, 122, 134))
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Form8Map(buffer.getvalue(), placed, missing, provisional, source)
