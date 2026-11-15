"""Offline geographic illustration for Annex Form 12's impact-area map cell.

Uses the actual saved accident origin and deterministic impact radius, never a
business mailing address as a substitute. Existing GIS source geometries are
optional and shown only if they intersect the scenario circle. This is a
source-backed schematic, not a georeferenced official background map.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from typing import Any, Mapping

from PIL import Image, ImageDraw
from pyproj import Transformer
from shapely.geometry import Point, mapping
from shapely.ops import nearest_points

from . import cap_form8_map as common_map
from . import cap_surroundings as surroundings
from . import sgis_population
from .project import Stage2Project

WIDTH, HEIGHT = 1240, 650
MAX_DRAW_RADIUS_M = sgis_population.MAX_RADIUS_M


@dataclass(frozen=True)
class ScenarioMap:
    png: bytes
    site_boundary_drawn: bool
    mapped_candidates: int


def render_scenario_map(project: Stage2Project, record: Mapping[str, Any]) -> ScenarioMap | None:
    """Draw exactly the circle implied by one scenario's known origin and radius."""
    try:
        lon, lat = sgis_population._parse_origin(record.get("사고원점 좌표"))
        radius = float(record.get("영향반경(m)"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(radius) or radius <= 0 or radius > MAX_DRAW_RADIUS_M:
        return None
    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform
    cx, cy = to_metric(lon, lat)
    origin = Point(cx, cy)
    circle = origin.buffer(radius, resolution=80)

    site = None
    try:
        boundary = surroundings.boundary(project)
        if boundary is not None:
            site = surroundings.metric_geometry(mapping(boundary))
    except (ValueError, TypeError):
        site = None

    # Include the site in the view if its real boundary reaches outside the
    # impact circle; do not make the red impact circle appear to include it.
    extra = site if site is not None else origin
    shape_bounds = circle.union(extra.buffer(min(radius * 0.03, 20))).bounds
    xmin, ymin, xmax, ymax = shape_bounds
    margin = max(75.0, radius * 0.14)
    xmin -= margin
    xmax += margin
    ymin -= margin
    ymax += margin

    left, top, right, bottom = 52, 65, WIDTH - 52, HEIGHT - 94
    sx, sy = (left + right) / 2, (top + bottom) / 2
    scale = min((right - left) / max(xmax - xmin, 1),
                (bottom - top) / max(ymax - ymin, 1))
    xm, ym = (xmin + xmax) / 2, (ymin + ymax) / 2

    def point(x: float, y: float) -> tuple[int, int]:
        return (round(sx + (x - xm) * scale), round(sy - (y - ym) * scale))

    img = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((17, 18, WIDTH - 17, HEIGHT - 16), outline=(195, 203, 214), width=2)
    draw.text((45, 25), "ACCIDENT SCENARIO - IMPACT EXTENT (GIS DRAFT)",
              font=common_map._font(23), fill=(43, 59, 78))
    # Metric grid, north arrow and a real scale bar.
    grid = max(50.0, 10 ** math.floor(math.log10(radius)) / 2)
    xx = math.floor(xmin / grid) * grid
    while xx <= xmax:
        x, _ = point(xx, ym)
        if left <= x <= right:
            draw.line((x, top, x, bottom), fill=(240, 242, 246), width=1)
        xx += grid
    yy = math.floor(ymin / grid) * grid
    while yy <= ymax:
        _, y = point(xm, yy)
        if top <= y <= bottom:
            draw.line((left, y, right, y), fill=(240, 242, 246), width=1)
        yy += grid

    common_map._outline(draw, circle, point, color=(161, 59, 60), width=5)
    if site is not None:
        common_map._outline(draw, site, point, color=(35, 72, 97), width=4,
                            fill=(209, 221, 231))

    plotted = 0
    if surroundings.is_current(project):
        survey = surroundings.survey(project)
        used = set()
        for item in survey.get("objects", []):
            if not isinstance(item, Mapping) or not isinstance(item.get("geometry"), Mapping):
                continue
            ident = str(item.get("id") or item.get("name") or "")
            if ident in used:
                continue
            try:
                geom = surroundings.metric_geometry(dict(item["geometry"]))
                if not circle.intersects(geom):
                    continue
                nearest = nearest_points(origin, geom)[1]
                if not circle.covers(nearest):
                    continue
            except (ValueError, TypeError):
                continue
            used.add(ident)
            x, y = point(nearest.x, nearest.y)
            # Unnumbered hollow pin = geometry-backed GIS candidate, not an
            # independently confirmed legal receptor. Lists retain their own
            # candidate status until per-scenario intersections are validated.
            draw.ellipse((x - 10, y - 10, x + 10, y + 10),
                         outline=(80, 113, 127), width=3, fill="white")
            plotted += 1

    x, y = point(cx, cy)
    draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(161, 59, 60))
    draw.line((x - 14, y, x + 14, y), fill=(161, 59, 60), width=2)
    draw.line((x, y - 14, x, y + 14), fill=(161, 59, 60), width=2)
    draw.text((x + 12, y + 12), "ORIGIN", font=common_map._font(17), fill=(113, 40, 42))
    nx, ny = WIDTH - 79, 92
    draw.line((nx, ny + 14, nx, ny + 66), fill=(39, 52, 70), width=3)
    draw.polygon(((nx, ny), (nx - 12, ny + 20), (nx + 12, ny + 20)),
                 fill=(39, 52, 70))
    draw.text((nx - 8, ny - 22), "N", font=common_map._font(22), fill=(39, 52, 70))

    bar_length = 100.0 if radius < 400 else 500.0 if radius < 1800 else 1000.0
    bar_px = round(bar_length * scale)
    bx, by = 54, HEIGHT - 77
    draw.line((bx, by, bx + bar_px, by), fill=(32, 51, 70), width=4)
    draw.line((bx, by - 7, bx, by + 7), fill=(32, 51, 70), width=3)
    draw.line((bx + bar_px, by - 7, bx + bar_px, by + 7), fill=(32, 51, 70), width=3)
    draw.text((bx, by + 10), f"{bar_length:g} m", font=common_map._font(17), fill=(38, 54, 76))
    draw.text((310, HEIGHT - 66),
              "RED: IMPACT RADIUS  |  GRAY: SITE  |  HOLLOW: GIS CANDIDATE",
              font=common_map._font(17), fill=(64, 77, 92))
    draw.text((WIDTH - 305, HEIGHT - 34), "SCHEMATIC / NO BASEMAP",
              font=common_map._font(15), fill=(112, 124, 136))

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return ScenarioMap(out.getvalue(), site is not None, plotted)
