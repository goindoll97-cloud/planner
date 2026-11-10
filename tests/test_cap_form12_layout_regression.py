"""Regression checks for statutory Form 12: no facts packed into 영향범위."""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document

from engine.stage2 import cap_baseline_docx as cap


def _sample_row(name: str, offsite: float) -> dict[str, object]:
    return {
        "사고시나리오명": name,
        "유해화학물질명": "가상 톨루엔",
        "대상 설비번호": "TK-01",
        "사고유형": "독성 누출",
        "장외거리(m)": offsite,
        "영향반경(m)": "",
        "거주민수": 12,
        "근로자수": 5,
        "산업단지 내 거주민수": 7,
        "산업단지 내 근로자수": 4,
        "산업단지 외 거주민수": 5,
        "산업단지 외 근로자수": 1,
        "사고원점 좌표": "35.1766585,126.9026910",
        "KORA/GIS 근거": "시험 근거서",
    }


def test_form12_places_named_scenario_offsite_and_coordinate_into_distinct_cells():
    doc = Document(BytesIO(cap.load_cap_baseline_bytes()))
    positions = cap.form_table_index_for(doc)["12"]
    scenario, targets = (doc.tables[index] for index in positions)
    data = SimpleNamespace(rows=(_sample_row("TK-01 가상 톨루엔 독성 누출", 9.8),), blockers=())
    with (
        patch.object(cap, "build_cap_form12_data", return_value=data),
        patch.object(cap.base, "_rows", return_value=[]),
    ):
        cap._fill_form12((scenario, targets), object())

    assert scenario.cell(0, 0).text == "(TK-01 가상 톨루엔 독성 누출) 사고시나리오"
    assert "장외 (9.8)m" in scenario.cell(1, 1).text
    assert "반경 (          )m" in scenario.cell(1, 1).text
    assert "근거" not in scenario.cell(1, 1).text
    assert "물질:" not in scenario.cell(1, 1).text
    assert "거주민(7)명, 근로자(4)명" == scenario.cell(3, 2).text
    assert "거주민(5)명, 근로자(1)명" == scenario.cell(4, 2).text
    assert "35.1766585,126.9026910" in scenario.cell(17, 0).text


def test_form12_uses_one_header_per_scenario_and_does_not_invent_missing_population():
    doc = Document(BytesIO(cap.load_cap_baseline_bytes()))
    positions = cap.form_table_index_for(doc)["12"]
    scenario, targets = (doc.tables[index] for index in positions)
    rows = (
        _sample_row("TK-01 가상 톨루엔 독성 누출", 9.8),
        _sample_row("CY-01 가상 암모니아 화재·폭발", 51.5),
    )
    rows[1].update({
        "영향반경(m)": 60.5,
        "산업단지 내 거주민수": "",
        "산업단지 내 근로자수": "",
        "산업단지 외 거주민수": "",
        "산업단지 외 근로자수": "",
    })
    data = SimpleNamespace(rows=rows, blockers=())
    with (
        patch.object(cap, "build_cap_form12_data", return_value=data),
        patch.object(cap.base, "_rows", return_value=[]),
    ):
        cap._fill_form12((scenario, targets), object())
    names = [
        table.cell(0, 0).text
        for table in doc.tables
        if table.rows and "사고시나리오" in table.cell(0, 0).text
        and "사고시나리오별" not in table.cell(0, 0).text
    ]
    assert "(TK-01 가상 톨루엔 독성 누출) 사고시나리오" in names
    assert "(CY-01 가상 암모니아 화재·폭발) 사고시나리오" in names
    second = next(table for table in doc.tables if table.cell(0, 0).text == "(CY-01 가상 암모니아 화재·폭발) 사고시나리오")
    assert "반경 (60.5)m, 장외 (51.5)m" in second.cell(1, 1).text
    assert "거주민(   )명" in second.cell(3, 2).text
