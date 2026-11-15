"""Regression tests for Form 8 (260409) first section: actual GIS map in statutory cell."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from docx import Document
from shapely.geometry import LineString, Point, mapping
from PIL import Image

from engine.stage2 import cap_form8_map as map8
from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_surroundings as geo
from engine.stage2.cap_baseline_docx import (
    build_cap_baseline_draft, form_table_index_for, load_cap_baseline_bytes,
)
from engine.stage2.project import Stage2Project


def _project():
    project = Stage2Project(
        project_id="FORM8-MAP-2026", company_name="가상 현장", cap_required=True,
        cap_group="2군", scope_confirmed=True, cap_selected=True
    )
    project.set_field("business.address", "사업장 주소", "울산광역시 남구 가상로 1", "VERIFIED")
    return project


def _with_site_boundary(project):
    shape = {
        "type": "Polygon",
        "coordinates": [[
            [129.2995, 35.4995], [129.3005, 35.4995],
            [129.3005, 35.5005], [129.2995, 35.5005],
            [129.2995, 35.4995]
        ]],
    }
    geo.save_boundary(project, shape, "회사 확인 부지 경계 2026-11-15", confirmed=True)
    return shape


def _source_objects():
    return [
        {
            "name": "가상 학교", "address": "울산",
            "geometry": mapping(Point(129.302, 35.500)),
            "source": "GIS 시험 도형",
        },
        {
            "name": "가상 하천", "address": "울산",
            "geometry": mapping(Point(129.304, 35.500)),
            "source": "GIS 시험 도형",
        },
    ]


def _rows():
    return [
        {
            "보호대상 명칭": "가상 학교", "보호대상 구분": "갑종",
            "세부유형": "교육·연구시설", "주소·위치": "울산",
            "사업장 경계와 거리(m)": 140, "GIS/현장 근거": "지도·현장 2026-11-15"
        },
        {
            "보호대상 명칭": "가상 하천", "보호대상 구분": "환경수용체",
            "세부유형": "하천", "주소·위치": "울산",
            "사업장 경계와 거리(m)": 320, "GIS/현장 근거": "지도·현장 2026-11-15"
        },
    ]


def _image_files(docx_bytes):
    with ZipFile(BytesIO(docx_bytes)) as archive:
        return [name for name in archive.namelist() if name.startswith("word/media/")]


def test_form8_first_section_inserts_real_map_inside_original_blank_cell():
    project = _project()
    _with_site_boundary(project)
    geo.save_survey(project, _source_objects(), center=(129.3, 35.5))
    f8.save(project, _rows(), no_target=False, scope_reviewed=True, status="USER_CONFIRMED")

    image = map8.render_site_map(project, list(_rows()))
    assert image is not None
    assert image.placed == 2
    assert image.missing == 0
    assert image.provisional == 0
    assert image.source == "회사 확인 부지 경계 2026-11-15"
    picture = Image.open(BytesIO(image.png))
    assert picture.format == "PNG"
    assert picture.size == (map8.WIDTH, map8.HEIGHT)

    output = build_cap_baseline_draft(project)
    doc = Document(BytesIO(output))
    idx = form_table_index_for(doc)["8"]
    context, list_table = doc.tables[idx[0]], doc.tables[idx[1]]
    assert len(doc.tables) == 38
    assert len(_image_files(output)) == 1
    map_cell = context.rows[1].cells[0]
    assert len(map_cell._tc.xpath(".//a:blip")) == 1
    assert "회사 확인 부지 경계" in map_cell.text
    assert "사업장 경계 외측 500m" in map_cell.text
    assert "도로·지적 배경지도 미포함" in map_cell.text
    # Numbers on the figure correspond to source rows, without changing the
    # statutory Form 8 list columns or their numbering.
    assert "가상 학교" in list_table.cell(1, 2).text
    assert "가상 하천" in list_table.cell(2, 2).text
    assert list_table.cell(1, 0).text == "1"
    assert list_table.cell(2, 0).text == "2"


def test_unconfirmed_candidates_display_only_hollow_unnumbered_map_markers():
    project = _project()
    _with_site_boundary(project)
    geo.save_survey(project, _source_objects(), center=(129.3, 35.5))
    f8.save(project, _rows(), no_target=False, scope_reviewed=False, status="HOLD")

    result = map8.render_site_map(project, [])
    assert result is not None
    assert result.placed == 0
    assert result.provisional == 2
    output = build_cap_baseline_draft(project)
    doc = Document(BytesIO(output))
    context, list_table = (doc.tables[i] for i in form_table_index_for(doc)["8"])
    assert len(_image_files(output)) == 1
    assert "검토 전 후보" in context.rows[1].cells[0].text
    assert "가상 학교" not in list_table.cell(1, 2).text
    assert "가상 하천" not in list_table.cell(2, 2).text


def test_no_confirmed_boundary_explains_empty_map_not_fake_geocode_point():
    project = _project()
    output = build_cap_baseline_draft(project)
    doc = Document(BytesIO(output))
    idx = form_table_index_for(doc)["8"][0]
    cell = doc.tables[idx].rows[1].cells[0]
    assert "사업장 경계 지도 미등록" in cell.text
    assert "③ 지도에서 실제 부지 경계" in cell.text
    assert not _image_files(output)


def test_confirmed_target_with_unknown_coordinates_not_invented_as_map_pin():
    project = _project()
    _with_site_boundary(project)
    geo.save_survey(project, _source_objects(), center=(129.3, 35.5))
    rows = _rows() + [{
        "보호대상 명칭": "위치를 모르는 시설",
        "보호대상 구분": "을종", "세부유형": "공업시설",
        "주소·위치": "위치 미확인",
        "사업장 경계와 거리(m)": 260,
        "GIS/현장 근거": "담당자 확인 예정",
    }]
    f8.save(project, rows, no_target=False, scope_reviewed=True, status="USER_CONFIRMED")
    result = map8.render_site_map(project, list(rows))
    assert result is not None
    assert result.placed == 2
    assert result.missing == 1
    output = build_cap_baseline_draft(project)
    doc = Document(BytesIO(output))
    cell = doc.tables[form_table_index_for(doc)["8"][0]].rows[1].cells[0]
    assert "위치도형이 없는 보호대상 1건" in cell.text


def test_long_river_line_crossing_buffer_gets_true_nearest_pin():
    project = _project()
    _with_site_boundary(project)
    # The midpoint of this long river line lies far outside the 500m buffer,
    # but its real river geometry starts inside the statutory vicinity.
    geo.save_survey(project, [{
        "name": "긴 하천", "source": "GIS 시험 선형",
        "geometry": mapping(LineString([(129.302, 35.5), (129.45, 35.5)])),
    }], center=(129.3, 35.5))
    rows = [{
        "보호대상 명칭": "긴 하천", "보호대상 구분": "환경수용체",
        "세부유형": "하천", "주소·위치": "울산",
        "사업장 경계와 거리(m)": 140, "GIS/현장 근거": "선형지리정보",
        "일련번호": 1,
    }]
    output = map8.render_site_map(project, rows)
    assert output is not None
    assert output.placed == 1
    assert output.missing == 0


def test_original_statutory_template_remains_byte_exact_before_rendering():
    from hashlib import sha256
    assert sha256(load_cap_baseline_bytes()).hexdigest() == (
        "6491a1648b37f96b482f4a529ee8dd0b7be93951324556fcdbce9e58d5c42aa8"
    )
