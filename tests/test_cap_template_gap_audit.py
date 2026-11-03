from __future__ import annotations

import csv
from io import StringIO

from engine.stage2 import cap_template_gap_audit as audit
from engine.stage2.direct_template import create_direct_cap_project


def test_audit_separates_workbook_gis_calculation_and_layout():
    project = create_direct_cap_project("시험사업장", address="울산광역시 남구 1", cap_group="1군")
    data = audit.rows(project)
    assert data
    assert all(set(audit.COLUMNS) == set(row) for row in data)
    assert any(row["입력·생성 경로"] == "회사 작성용 엑셀" for row in data)
    assert any(row["입력·생성 경로"] == "지도·현장 조사" for row in data)
    assert any(row["입력·생성 경로"] == "자동 계산 엔진" for row in data)
    assert any(row["서식"] == "별지 제14호" and row["구분"] == "출력서식 구조 점검" for row in data)
    mapped_scenario = [row for row in data if row["항목"] == "사고원점"]
    assert mapped_scenario


def test_csv_is_utf8_bom_and_has_same_row_count():
    project = create_direct_cap_project("시험사업장", address="울산광역시 남구 1")
    raw = audit.csv_bytes(project)
    assert raw.startswith(b"\\xef\\xbb\\xbf")
    parsed = list(csv.DictReader(StringIO(raw.decode("utf-8-sig"))))
    assert len(parsed) == len(audit.rows(project))
