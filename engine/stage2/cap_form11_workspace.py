from __future__ import annotations

"""별지 제11호(고정식 유해감지시설 명세) authoring support.

감지기 사양은 회사 사양서에서 오는 값이라 프로그램이 만들지 않는다. 대신 줄 골격
(구분기호·감지대상·설치위치)을 별지 제1호 시설·물질에서 제안하고, 사람은 설비마다
같은 값을 되풀이해 적지 않도록 선택 목록에서 고르고 사양만 채운다.
"""

from typing import Any, Mapping

from .cap_form11_engine import build_cap_form11_data
from .cap_shared_facts import workspace_facility_rows
from .project import Stage2Project

GAS_KEY = "cap.safety.gas_detection"
FIXED = "고정식"
MEASUREMENT_METHODS = ("전기화학식", "접촉연소식", "적외선식", "광이온화식(PID)", "반도체식", "기타")
YES_NO = ("예", "아니오")

# (column, label, kind, help)
COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("감지기 번호", "구분기호", "text", "고정식 유해감지시설의 고유 식별번호입니다(서식 주 ①). 예: GD-001"),
    ("검출대상 물질", "감지대상", "choice", "감지하려는 화학물질입니다(서식 주 ②). 화학물질 목록에서 고르거나, 일반 감지범주면 VOC·복합가스 등으로 적습니다."),
    ("설치위치", "설치위치", "choice", "감지기가 붙은 설비입니다. 별지 제1호에 적은 설비 기호 중에서 고릅니다."),
    ("작동시간", "작동시간", "text", "제조사 사양서의 응답(작동) 시간입니다. 수치와 단위를 함께 적습니다. 예: 30초 이내"),
    ("측정방식", "측정방식", "choice", "센서의 측정 원리입니다. 고정식·휴대식은 측정방식이 아니라 설치형태입니다."),
    ("경보 설정값", "경보 설정값", "text", "경보가 울리는 농도입니다. 수치와 단위를 함께 적습니다. 예: 0.5 ppm, 10% LEL"),
    ("경보 위치", "경보기 설치장소", "text", "경보기(경광등·사이렌)가 설치된 장소입니다."),
    ("연동여부", "연동여부", "choice", "경보 시 설비 정지·차단 같은 자동 조치와 연결돼 있으면 '예'입니다."),
    ("연동 설비·조치", "연동 설비·조치", "text", "연동이 '예'일 때 어떤 설비가 어떻게 작동하는지 적습니다."),
    ("정밀도", "정밀도", "text", "제조사 사양서의 정밀도(정확도)입니다. 예: ±3% F.S."),
    ("유지관리", "유지관리", "text", "점검·교정 주기입니다. 예: 월 1회 점검, 6개월 교정"),
    ("비고", "비고", "text", "참고할 내용을 적습니다."),
)
COLUMN_IDS = tuple(column for column, *_ in COLUMNS)


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def facility_tags(project: Stage2Project) -> list[str]:
    return [t for t in (_clean(r.get("설비번호")) for r in workspace_facility_rows(project)) if t]


def chemical_choices(project: Stage2Project) -> list[str]:
    from . import cap_chemical_workspace as chem

    _, rows = chem._rows(project)
    names = [_clean(r.get("물질명") or r.get("유해화학물질명")) for r in rows]
    return [n for n in dict.fromkeys(names) if n] + ["VOC", "복합가스"]


def saved_rows(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(GAS_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [dict(r) for r in record.value if isinstance(r, Mapping)]


def skeleton(project: Stage2Project) -> list[dict[str, Any]]:
    """Proposed rows (구분기호·감지대상·설치위치) for facilities that have no detector yet."""
    covered = {_clean(r.get("설치위치")).upper() for r in saved_rows(project)}
    start = len(saved_rows(project)) + 1
    out = []
    for facility in workspace_facility_rows(project):
        tag = _clean(facility.get("설비번호"))
        material = _clean(facility.get("취급물질"))
        if not tag or tag.upper() in covered or not material:
            continue
        out.append({"감지기 번호": f"GD-{start + len(out):03d}", "설치형태": FIXED,
                    "검출대상 물질": material, "설치위치": tag})
    return out


def save(project: Stage2Project, rows: list[Mapping[str, Any]]) -> int:
    cleaned = []
    for row in rows:
        item = {column: _clean(row.get(column)) for column in COLUMN_IDS}
        if not any(item.values()):
            continue
        item["설치형태"] = _clean(row.get("설치형태")) or FIXED
        cleaned.append(item)
    project.set_field(GAS_KEY, "고정식 유해감지시설 명세(별지 제11호 작성대)", cleaned, "USER_CONFIRMED",
                      note="CAP 작성대 별지 제11호에서 감지기 사양 입력")
    return len(cleaned)


def needs(project: Stage2Project) -> list[str]:
    return list(build_cap_form11_data(project).blockers)
