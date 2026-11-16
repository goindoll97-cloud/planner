"""End-to-end statutory Form 12: SGIS census totals are visible and auditable."""
from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from pyproj import Transformer
from shapely.geometry import Point, box, mapping

from engine.stage2 import cap_baseline_docx as cap
from engine.stage2 import cap_catalog_docx as catalog
from engine.stage2 import cap_form12_impact_map as impact_map
from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_surroundings as surroundings
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
            assert f'{values["거주민수"]:,}' in text
            assert f'{values["근로자수"]:,}' in text
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


def test_form12_impact_map_uses_only_receptor_candidates_for_its_scenario():
    p, _ = setup_project()
    surroundings.save_survey(p, [
        {"name": "가상 보호대상", "source": "GIS 원자료",
         "geometry": mapping(Point(126.9002, 35.18))},
        {"name": "보호대상 아닌 현장 설비", "source": "GIS 원자료",
         "geometry": mapping(Point(126.9001, 35.18))},
    ], center=(126.9, 35.18))
    p.set_field(iw.SCENARIO_TARGETS_KEY, "사고시나리오 보호대상 후보", [
        {"사고시나리오명": "독성-1", "보호대상 명칭": "가상 보호대상"},
        {"사고시나리오명": "독성-2", "보호대상 명칭": "미확인 시설"},
    ], "CALCULATED")
    first, second = p.get_field(iw.IMPACT_TABLE_KEY).value
    result = impact_map.render_scenario_map(p, first)
    assert result is not None
    assert result.mapped_candidates == 1
    other = impact_map.render_scenario_map(p, second)
    assert other is not None
    assert other.mapped_candidates == 0


def _receptor_boxes(table):
    """Find the original subtype choice by text, not logical grid position.

    Annex 12 merges its category label across multiple rows and some choice
    cells across columns, so table.cell(row, col) can address a neighbor.
    """
    options = {"school": "교육·연구시설", "factory": "공업시설", "river": "하천"}
    found = {}
    for key, label in options.items():
        matches = [
            cell.text for row in table.rows[5:15] for cell in cap._unique_cells(row)
            if cap.base._norm(cell.text.lstrip("□☐☒ ").strip()) == cap.base._norm(label)
        ]
        assert len(matches) == 1, (label, matches)
        found[key] = matches[0]
    return found


def test_form12_checks_each_scenario_only_for_actual_gis_overlap_not_500m_candidates():
    p, _ = setup_project()
    # Set the *incident-origin influence radius*, not the distinct off-site
    # distance. setup_project normally uses radii 100/200 and off-site 20/120.
    records = [dict(item) for item in p.get_field(iw.IMPACT_TABLE_KEY).value]
    records[0]["영향반경(m)"] = 20.0
    records[1]["영향반경(m)"] = 120.0
    p.set_field(iw.IMPACT_TABLE_KEY, "공간중첩 테스트 반경", records, "CALCULATED")
    surroundings.save_survey(p, [
        {"name": "지도 학교", "source": "공개 GIS",
         "geometry": mapping(Point(126.9007, 35.18))},
        {"name": "지도 공장", "source": "공개 GIS",
         "geometry": mapping(Point(126.9017, 35.18))},
        {"name": "지도 하천", "source": "공개 GIS",
         "geometry": mapping(Point(126.9001, 35.18))},
    ], center=(126.9, 35.18))
    p.set_field(f8.SITE_KEY, "제8호 주변 보호대상", [
        {"보호대상 명칭": "지도 학교", "보호대상 구분": "갑종",
         "세부유형": "교육·연구시설", "사업장 경계와 거리(m)": 75,
         "주소·위치": "지도 시험위치", "GIS/현장 근거": "GIS-학교"},
        {"보호대상 명칭": "지도 공장", "보호대상 구분": "을종",
         "세부유형": "공업시설", "사업장 경계와 거리(m)": 170,
         "주소·위치": "지도 시험위치", "GIS/현장 근거": "GIS-공장"},
        {"보호대상 명칭": "지도 하천", "보호대상 구분": "환경수용체",
         "세부유형": "하천", "사업장 경계와 거리(m)": 15,
         "주소·위치": "지도 시험위치", "GIS/현장 근거": "GIS-하천"},
    ], "PROPOSED")

    for builder in (cap.build_cap_baseline_draft, catalog.build_cap_draft):
        doc = Document(BytesIO(builder(p)))
        scenarios = _scenario_tables(doc)
        assert len(scenarios) == 2
        first, second = scenarios
        # First scenario has a 20 m radius, second has 120 m.
        assert _receptor_boxes(first)["river"].startswith("☒")
        assert _receptor_boxes(first)["school"].startswith("□")
        assert _receptor_boxes(second)["river"].startswith("☒")
        assert _receptor_boxes(second)["school"].startswith("☒")
        # A target listed within 500 m but outside either incident circle
        # is not a confirmed Form 12 inclusion.
        assert all(_receptor_boxes(t)["factory"].startswith("□") for t in scenarios)
        # Compare the exact official heading cells, including preserved
        # manual line breaks. Neither heading nor shading may be rewritten.
        official = Document(BytesIO(cap.load_cap_baseline_bytes()))
        source_table = official.tables[cap.form_table_index_for(official)["12"][0]]
        for row_no in (5, 9, 12):
            assert first.cell(row_no, 0).text == source_table.cell(row_no, 0).text
            assert second.cell(row_no, 0).text == source_table.cell(row_no, 0).text
        assert len(first.rows) == 18 and len(second.rows) == 18


def test_form12_checks_scenario_linked_user_verified_gis_targets_without_boundary_shortcuts():
    p, _ = setup_project()
    p.set_field(iw.TARGETS_KEY, "개별 영향범위 공간중첩 확인자료", [
        {"사고시나리오명": "독성-1", "보호대상 명칭": "확인한 학교",
         "보호대상 구분": "갑종", "세부유형": "교육·연구시설",
         "GIS 근거": "현장/GIS 중첩 확인서"},
        {"사고시나리오명": "독성-2", "보호대상 명칭": "확인한 공장",
         "보호대상 구분": "을종", "세부유형": "공업시설",
         "GIS 근거": "KORA GIS 중첩 확인서"},
        {"사고시나리오명": "독성-2", "보호대상 명칭": "미확인 하천",
         "보호대상 구분": "환경수용체", "세부유형": "하천",
         "GIS 근거": "단순 경계거리", "공간중첩 상태": "미검증 후보"},
    ], "USER_CONFIRMED")

    doc = Document(BytesIO(cap.build_cap_baseline_draft(p)))
    first, second = _scenario_tables(doc)
    assert _receptor_boxes(first)["school"].startswith("☒")
    assert _receptor_boxes(first)["factory"].startswith("□")
    assert _receptor_boxes(second)["school"].startswith("□")
    assert _receptor_boxes(second)["factory"].startswith("☒")
    assert _receptor_boxes(second)["river"].startswith("□")


def test_form12_does_not_check_calculated_boundary_only_or_stale_survey_targets():
    p, _ = setup_project()
    # The former automatic Form 8 500 m list was CALCULATED, not individually
    # assessed for each scenario; even a matching scenario name is insufficient.
    p.set_field(iw.TARGETS_KEY, "제8호 기준으로 자동 집계", [
        {"사고시나리오명": "독성-1", "보호대상 명칭": "거리기준 학교",
         "보호대상 구분": "갑종", "세부유형": "교육·연구시설",
         "GIS 근거": "500m 경계거리"},
    ], "CALCULATED", note="별지 제8호 목록에서 집계")
    doc = Document(BytesIO(cap.build_cap_baseline_draft(p)))
    assert all(_receptor_boxes(t)["school"].startswith("□") for t in _scenario_tables(doc))

    surroundings.save_survey(p, [
        {"name": "위치 하천", "source": "GIS",
         "geometry": mapping(Point(126.9001, 35.18))}
    ], center=(126.9, 35.18))
    p.set_field(f8.SITE_KEY, "환경수용체 후보", [{
        "보호대상 명칭": "위치 하천", "보호대상 구분": "환경수용체",
        "세부유형": "하천", "주소·위치": "시험",
        "사업장 경계와 거리(m)": 10, "GIS/현장 근거": "GIS",
    }], "PROPOSED")
    # Once the business address changes, the old survey geometry cannot be
    # treated as a current per-scenario GIS intersection.
    p.set_field("business.address", "사업장 주소", "바뀐 주소", "USER_CONFIRMED")
    doc = Document(BytesIO(cap.build_cap_baseline_draft(p)))
    assert all(_receptor_boxes(t)["river"].startswith("□") for t in _scenario_tables(doc))


def test_stage3_saved_gis_targets_reach_form12_scenario_list_and_checkboxes():
    """Step ③ PROPOSED rows can appear in the draft when GIS overlap exists."""
    p, _ = setup_project()
    records = [dict(item) for item in p.get_field(iw.IMPACT_TABLE_KEY).value]
    records[0]["영향반경(m)"] = 20
    records[1]["영향반경(m)"] = 120
    p.set_field(iw.IMPACT_TABLE_KEY, "시나리오별 피해범위", records, "CALCULATED")
    surroundings.save_survey(p, [
        {"name": "초안 학교", "source": "검토용 GIS", "geometry": mapping(Point(126.9007, 35.18))},
        {"name": "초안 하천", "source": "검토용 GIS", "geometry": mapping(Point(126.9001, 35.18))},
    ], center=(126.9, 35.18))
    f8.save(p, [
        {"보호대상 명칭": "초안 학교", "보호대상 구분": "갑종",
         "세부유형": "교육·연구시설", "주소·위치": "GIS 위치",
         "사업장 경계와 거리(m)": 75, "GIS/현장 근거": "GIS 후보"},
        {"보호대상 명칭": "초안 하천", "보호대상 구분": "환경수용체",
         "세부유형": "하천", "주소·위치": "GIS 위치",
         "사업장 경계와 거리(m)": 15, "GIS/현장 근거": "GIS 후보"},
    ], no_target=False, status="PROPOSED")

    for build in (cap.build_cap_baseline_draft, catalog.build_cap_draft):
        doc = Document(BytesIO(build(p)))
        scenarios = _scenario_tables(doc)
        assert len(scenarios) == 2
        assert _receptor_boxes(scenarios[0])["school"].startswith("□")
        assert _receptor_boxes(scenarios[1])["school"].startswith("☒")
        assert _receptor_boxes(scenarios[0])["river"].startswith("☒")
        assert _receptor_boxes(scenarios[1])["river"].startswith("☒")

        # Annex-12's individual target table is now populated by the same
        # current GIS overlap, even though the site candidates remain PROPOSED.
        all_tables = "\n".join(
            cell.text for table in doc.tables
            for row in table.rows for cell in cap._unique_cells(row)
        )
        assert "독성-1 / 초안 하천 [잠정: 사고원점" in all_tables
        assert "독성-2 / 초안 하천 [잠정: 사고원점" in all_tables
        assert "독성-2 / 초안 학교 [잠정: 사고원점" in all_tables
        assert "독성-1 / 초안 학교" not in all_tables


def test_form12_confirmed_target_in_one_scenario_does_not_hide_another_scenario_candidates():
    p, _ = setup_project()
    p.set_field(iw.TARGETS_KEY, "시나리오 1 확정 대상", [
        {"사고시나리오명": "독성-1", "보호대상 명칭": "확정 학교",
         "보호대상 구분": "갑종", "세부유형": "교육·연구시설",
         "사업장 경계와 거리(m)": 20, "GIS 근거": "KORA/GIS 확인"},
    ], "USER_CONFIRMED")
    p.set_field(iw.SCENARIO_TARGETS_KEY, "시나리오 2 잠정 대상", [
        {"사고시나리오명": "독성-2", "보호대상 명칭": "검토 하천",
         "보호대상 구분": "환경수용체", "보호대상 종류": "하천",
         "사업장 경계와 거리(m)": 60, "공간중첩 상태": "미검증 후보"},
    ], "CALCULATED")

    doc = Document(BytesIO(cap.build_cap_baseline_draft(p)))
    all_tables = "\n".join(
        cell.text for table in doc.tables
        for row in table.rows for cell in cap._unique_cells(row)
    )
    assert "독성-1 / 확정 학교" in all_tables
    assert "독성-2 / 검토 하천 [잠정: 경계거리 기반·공간중첩 미검증]" in all_tables
