"""Zooming or panning a map must not rerun the page (and show the loader).

streamlit-folium reruns the script whenever a value listed in
``returned_objects`` changes. Only clicks and drawings are user actions that
need saving; zoom/center/bounds would rerun the app on every mouse-wheel move.
"""
from __future__ import annotations

import ast
from pathlib import Path

VIEW_ONLY = {"zoom", "center", "bounds", "last_active_drawing"}


def _st_folium_calls():
    for path in sorted((Path(__file__).resolve().parents[1] / "ui").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "st_folium":
                yield path.name, node


def _string_constants(node):
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_every_map_reports_only_clicks_or_drawings():
    calls = list(_st_folium_calls())
    assert {name for name, _ in calls} >= {"scenario_results_page.py", "evidence_workspace_page.py"}
    for name, call in calls:
        returned = next((kw.value for kw in call.keywords if kw.arg == "returned_objects"), None)
        # Without returned_objects every zoom/pan is reported and reruns the page.
        assert returned is not None, f"{name}: st_folium needs returned_objects"
        values = _string_constants(returned)
        assert values, f"{name}: returned_objects must list click/drawing values"
        assert not values & VIEW_ONLY, f"{name}: {sorted(values & VIEW_ONLY)} reruns on zoom/pan"
