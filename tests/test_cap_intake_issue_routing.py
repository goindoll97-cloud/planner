"""CAP intake stage: legal/GIS checks must not masquerade as Excel errors."""
from types import SimpleNamespace

from engine.stage2.cap_intake_issue_routing import (
    EXCEL, INFORMATION, LEGAL, MAP, count_routes, route_issue
)


def issue(message, legal_item="별지 제1호 사업장의 작성수준 구분", *,
          status="HOLD", keys=("inventory.facilities",)):
    return SimpleNamespace(
        message=message, legal_item=legal_item, status=status,
        field_keys=keys
    )


def test_20261110_exported_messages_are_routed_to_the_correct_step():
    # Representative actual training warnings from the uploaded CSV.
    examples = (
        ("별표 3 제42호 적용을 위해 '상온·상압 액체 여부'가 필요합니다.", EXCEL),
        ("별표 3 제44호 적용을 위해 '상온·상압 액체 여부'가 필요합니다.", EXCEL),
        ("별표 3→별표 2 직접 규칙에서 규정수량을 확정하지 못했습니다.", LEGAL),
        ("Stage 1 판정과 연결되지 않은 직접 시작 프로젝트입니다.", LEGAL),
        ("총괄영향범위 내 주민 여부를 확인할 자료가 없습니다.", MAP),
        ("현행 별표 2의 고유번호를 확정하지 못했습니다.", LEGAL),
        ("별표 2 직접 CAS 또는 별표 3 사고대비물질에서 별지 제6호 물질구분을 확정하지 못했습니다.", LEGAL),
        ("용액 적용조건 확인 전에는 고유번호·물질구분을 자동확정하지 않습니다.", LEGAL),
        ("KORA/GIS에서 확정된 사고시나리오별 영향평가 자료가 없습니다.", MAP),
        ("대표물질은 2종입니다. 현재 3종이 입력되어 있습니다.", EXCEL),
        ("TK-01: 취급량/최대보유량이 비어 있습니다.", EXCEL),
        ("GD-02: 감지대상을 회사 화학물질명과 연결하지 못했습니다.", EXCEL),
    )
    for message, expected in examples:
        assert route_issue(issue(message)) == expected, message


def test_actual_missing_company_facts_remain_actionable_in_excel():
    assert route_issue(issue(
        "TK-02: 설계용량·용량단위·비중(밀도)이 필요합니다."
    )) == EXCEL
    assert route_issue(issue(
        "제품 SDS 제9항의 상온·상압 액체 여부가 필요합니다.",
        keys=("inventory.chemicals",)
    )) == EXCEL
    assert route_issue(issue(
        "공정 안전밸브 설정압력은 설비 명세서로 확인해야 합니다.",
        legal_item="별지 제9호 장치·설비 목록"
    )) == EXCEL


def test_final_legal_and_spatial_issues_are_still_live_not_assumed_pass():
    a = issue("추가 위치 검증 필요", keys=("cap.offsite.overall_impact_summary",))
    b = issue("유해화학물질 고유번호 미확정", legal_item="별지 제6호", keys=("cap.chemical.details",))
    c = issue("법령 검토 완료", status="PASS")
    d = issue("최초 신규제출로 확인되어 변경내역 관리대장을 필수 작성항목으로 적용하지 않습니다.")
    assert route_issue(a) == MAP
    assert route_issue(b) == LEGAL
    assert route_issue(c) == INFORMATION
    assert route_issue(d) == INFORMATION
    assert count_routes((a, b, c, d)) == {EXCEL: 0, LEGAL: 1, MAP: 1, INFORMATION: 2}


def test_missing_impact_is_not_silenced_without_gis_or_evidence():
    missing_map = issue("별지 제12호 연계: KORA/GIS 확인자료 없음", legal_item="별지 제16호",
                        keys=("cap.basic.emergency_summary",))
    assert route_issue(missing_map) == MAP
