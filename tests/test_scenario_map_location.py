"""Automatic boundary/incident-origin behavior and no duplicate Excel entry."""
from unittest.mock import patch

import pytest
from shapely.geometry import mapping, shape

from engine.stage2 import cap_surroundings as survey
from engine.stage2 import scenario_map_location as location
from engine.stage2 import scenario_pipeline
from engine.stage2.project import Stage2Project


def area(west=127.000, south=37.000, east=127.002, north=37.002):
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north],
            [west, north], [west, south]
        ]]
    }


def project():
    p = Stage2Project(project_id="MAP-GEOMETRY", company_name="연습사업장", cap_required=True)
    survey.save_boundary(p, area(), "경계 지도 클릭 2026-11-10", confirmed=True)
    p.set_field(
        scenario_pipeline.INPUT_KEY, "실제 엑셀 사고시나리오 검토값",
        [{"설비번호": "TK-01", "액위(m)": "2.3", "누출지점 배관길이(m)": "7.5",
          "비열비": "1.3"}],
        "USER_CONFIRMED",
    )
    return p


def test_map_click_saves_only_coordinates_and_calculated_distance_preserving_excel_facts():
    p = project()
    with patch.object(scenario_pipeline.sc, "_facility_rows", return_value=[{"설비번호": "TK-01"}]), \
         patch.object(scenario_pipeline, "refresh") as refresh:
        origin, distance = location.save_location(p, "TK-01", 37.001, 127.001)
        assert origin == "37.0010000,127.0010000"
        assert 0 < distance < 200
        rows = scenario_pipeline.file_inputs(p)
        assert rows["TK-01"]["액위(m)"] == "2.3"
        assert rows["TK-01"]["누출지점 배관길이(m)"] == "7.5"
        assert rows["TK-01"]["비열비"] == "1.3"
        assert rows["TK-01"]["사고원점 좌표"] == origin
        assert rows["TK-01"]["경계까지 거리(m)"] == distance
        assert p.get_field(scenario_pipeline.INPUT_KEY).value[0].get("사고원점 좌표") is None
        assert p.get_field(scenario_pipeline.MAP_INPUT_KEY) is not None
        refresh.assert_called_once()
        location.save_location(p, "TK-01", 37.001, 127.001)
        refresh.assert_called_once()  # duplicate click must not repeat computation
        # Simulate a new Excel upload changing only the factual liquid head.
        p.set_field(scenario_pipeline.INPUT_KEY, "새 엑셀 자료",
                    [{"설비번호": "TK-01", "액위(m)": "3.1"}], "USER_CONFIRMED")
        assert scenario_pipeline.file_inputs(p)["TK-01"]["액위(m)"] == "3.1"
        assert scenario_pipeline.file_inputs(p)["TK-01"]["사고원점 좌표"] == origin
        assert scenario_pipeline.file_inputs(p)["TK-01"]["경계까지 거리(m)"] == distance
        # Replacing the business address invalidates old GIS-specific facts.
        p.set_field("business.address", "사업장 주소", "다른 시·군의 사업장", "USER_CONFIRMED")
        assert "사고원점 좌표" not in scenario_pipeline.file_inputs(p)["TK-01"]
        assert scenario_pipeline.file_inputs(p)["TK-01"]["액위(m)"] == "3.1"


def test_boundary_change_recomputes_distance_and_does_not_invent_new_origin():
    p = project()
    with patch.object(scenario_pipeline.sc, "_facility_rows", return_value=[{"설비번호": "TK-01"}]), \
         patch.object(scenario_pipeline, "refresh"):
        _, old = location.save_location(p, "TK-01", 37.001, 127.001)
    survey.save_boundary(p, area(east=127.0014), "필지 수정 2026-11-10", confirmed=True)
    assert location.refresh_boundary_distances(p)
    row = scenario_pipeline.file_inputs(p)["TK-01"]
    assert row["경계까지 거리(m)"] != old
    assert row["액위(m)"] == "2.3"
    survey.save_boundary(p, area(east=127.0003), "필지 재수정 2026-11-10", confirmed=True)
    assert location.refresh_boundary_distances(p)
    row = scenario_pipeline.file_inputs(p)["TK-01"]
    assert row["사고원점 좌표"] == "37.0010000,127.0010000"
    assert row["경계까지 거리(m)"] == ""
    assert row["액위(m)"] == "2.3"


def test_outside_boundary_or_unknown_equipment_is_never_saved_as_location():
    p = project()
    with patch.object(scenario_pipeline.sc, "_facility_rows", return_value=[{"설비번호": "TK-01"}]), \
         patch.object(scenario_pipeline, "refresh"):
        with pytest.raises(ValueError, match="경계 밖"):
            location.save_location(p, "TK-01", 37.004, 127.004)
        with pytest.raises(ValueError, match="설비목록"):
            location.save_location(p, "FAKE-00", 37.001, 127.001)
    assert scenario_pipeline.file_inputs(p)["TK-01"].get("사고원점 좌표") is None


def test_auto_boundary_persistence_skips_unchanged_polygon_and_never_needs_button():
    from ui import scenario_results_page as page
    p = project()
    existing = survey.boundary(p)
    poly = area()
    with patch.object(page.ss, "confirm") as confirm, patch.object(page, "save_project"):
        unchanged = page._persist_selected_boundary(
            p, mode=page.DRAW, parcels=[], drawings=[{"type": "Feature", "geometry": poly}],
            origin="지도 화면",
        )
        assert unchanged == ""
        confirm.assert_not_called()
        changed = page._persist_selected_boundary(
            p, mode=page.DRAW, parcels=[], drawings=[
                {"type": "Feature", "geometry": area(east=127.0015)}
            ], origin="지도 화면",
        )
        confirm.assert_called_once()
    assert existing is not None
