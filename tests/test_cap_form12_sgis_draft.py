"""End-to-end statutory Form 12: SGIS census totals are visible and auditable."""
from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from pyproj import Transformer
from shapely.geometry import box, mapping

from engine.stage2 import cap_baseline_docx as cap
from engine.stage2 import cap_catalog_docx as catalog
from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import sgis_population as sgis
from engine.stage2.project import Stage2Project


ORIGIN = "35.1800000,126.9000000"


def setup_project():
    p = Stage2Project(project_id="CAP-SGIS-FORM12", company_name="가상 산업시설", cap_required=True)
    p.set_authoring_scope(psm_selected=False, cap_selected=True)
    p.set_field(sc.SCENARIO_KEY, "사고시나리오(입력)", [
        {"사고시나리오명": "독성-1", "사고원점 좌표": ORIGIN},
        {"사고시나리오명": "독성-2", "사고원점 좌표": ORIGIN},
    ], "CALCULATED")
    impacts = [
        iw.ScenarioImpact("독성-1", "가상물질", "TK-1", sc.TOXIC, 100.0, 20.0, "시험 근거", (), ()),
        iw.ScenarioImpact("독성-2", "가상물질", "TK-2", sc.TOXIC, 200.0, 120.0, "시험 근거", (), ()),
    ]
    p.set_field(iw.IMPACT_TABLE_KEY, "영향평가(프로그램)", [
        {
            "사고시나리오명": i.name, "유해화학물질명": i.material,
            "대상 설비번호": i.tag, "사고유형": i.kind,
            "장외거리(m)": i.off_site_m, "영향반경(m)": i.radius_m,
            "거주민수": "", "근로자수": "",
            "사고원점 좌표": ORIGIN, "KORA/GIS 근거": "시험 자동 계산",
        }
        for i in impacts
    ], "CALCULATED")
    p.set_field(iw.SUMMARY_KEY, "총괄영향범위", [{}], "CALCULATED")
    return p, impacts


class FakeSGIS:
    def available_years(self):
        return ["2025", "2024"]

    def administrative_areas(self, geom):
        x, y = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform(126.9, 35.18)
        return [{"properties": {"adm_cd": "29000000"},
                 "geometry": mapping(box(x - 450, y - 450, x + 450, y + 450))}]

    def counts(self, adm_cd, year):
        if year == "2025":
            raise sgis.SGISPopulationYearUnavailable("2025년 해당 지역 자료 비공개")
        return 6000, 800, 300


def _map_cell(scenario_table):
    return scenario_table.rows[16].cells[0]


def _scenario_tables(doc):
    return [
        t for t in doc.tables if len(t.rows) == 18
        and "사고시나리오" in t.cell(0, 0).text
        and t.cell(1, 0).text.strip() == "영향범위"
    ]


def test_sgis_reuses_one_existing_calculation_to_fill_each_scenario_map_note():
    p, impacts = setup_project()
    with patch.object(iw, "evaluate", return_value=impacts):
        sgis.refresh_for_draft(p, impacts, client=FakeSGIS())
        # No second network request should occur while generating DOCX.
        with patch.object(sgis, "SGISClient", side_effect=AssertionError("NO API")):
            original = cap.build_cap_baseline_draft(p)
            assembled = catalog.build_cap_draft(p)

    for data in (original, assembled):
        doc = Document(BytesIO(data))
        tables = _scenario_tables(doc)
        assert len(tables) == 2
        with ZipFile(BytesIO(data)) as z:
            assert len([n for n in z.namelist() if n.startswith("word/media/")]) == 2
        for idx, table in enumerate(tables):
            assert len(_map_cell(table)._tc.xpath(".//a:blip")) == 1
            text = _map_cell(table).text
            assert "SGIS 2024년" in text
            assert "전체 영향범위 자동 추정" in text
            assert "산업단지" in text
            assert "구분값이 아닙니다" in text
            values = p.get_field(sgis.RESULT_KEY).value["scenario"][impacts[idx].name]
            assert str(values["거주민수"]) in text
            assert str(values["근로자수"]) in text
            # Official in/out location remains unknown: do not invent split.
            assert "거주민(   )명" in table.cell(3, 2).text
            assert "근로자(   )명" in table.cell(4, 2).text
            assert "장외 (" in table.cell(1, 1).text

    evidence = p.get_field(sgis.RESULT_KEY).value
    assert evidence["year"] == "2024"
    assert evidence["year_selection"].startswith("이전 공통연도")


def test_changed_scenario_origin_cannot_reuse_stale_sgis_annotation():
    p, impacts = setup_project()
    with patch.object(iw, "evaluate", return_value=impacts):
        sgis.refresh_for_draft(p, impacts, client=FakeSGIS())
        assert sgis.current_draft_for_form12(p) is not None

    # A changed accident radius in the active calculation invalidates the
    # old year/area-weighted population estimate, not the whole draft.
    updated = [
        iw.ScenarioImpact(impacts[0].name, impacts[0].material, impacts[0].tag,
                          impacts[0].kind, 175.0, impacts[0].off_site_m,
                          impacts[0].basis, (), ()),
        impacts[1],
    ]
    with patch.object(iw, "evaluate", return_value=updated):
        assert sgis.current_draft_for_form12(p) is None
        out = cap.build_cap_baseline_draft(p)
    doc = Document(BytesIO(out))
    assert len(_scenario_tables(doc)) == 2
    assert all("SGIS 2024년" not in _map_cell(t).text for t in _scenario_tables(doc))


def test_form12_draft_without_sgis_still_draws_scenario_impact_map():
    p, _ = setup_project()
    data = cap.build_cap_baseline_draft(p)
    doc = Document(BytesIO(data))
    scenario = _scenario_tables(doc)[0]
    assert len(_map_cell(scenario)._tc.xpath(".//a:blip")) == 1
    assert "SGIS" not in _map_cell(scenario).text


def test_no_origin_or_radius_is_not_replaced_with_a_made_up_map():
    p, _ = setup_project()
    rows = [dict(row) for row in p.get_field(iw.IMPACT_TABLE_KEY).value]
    rows[0]["사고원점 좌표"] = ""
    rows[0]["영향반경(m)"] = ""
    p.set_field(iw.IMPACT_TABLE_KEY, "영향평가", rows, "CALCULATED")
    data = cap.build_cap_baseline_draft(p)
    first = _scenario_tables(Document(BytesIO(data)))[0]
    assert not _map_cell(first)._tc.xpath(".//a:blip")
    assert "SGIS" not in _map_cell(first).text
