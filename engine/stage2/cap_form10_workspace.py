from __future__ import annotations

"""별지 제10호(확산방지설비 현황) authoring support.

취급시설 목록은 별지 제1·9호에서 가져오고, 사람은 (1) 어느 설비에 확산방지설비가
적용되는지, (2) 필요용량 기준(설계용량 대비 비율과 근거)을 한 번, (3) 유효용량
(직접 확인값 또는 치수)만 적는다. 필요용량 비율은 프로그램이 임의로 정하지
않는다(법 제24조 기준을 사용자가 확인해 입력). 값은 기존 엔진이 읽는
cap.safety.dike_calculation 형식으로 저장한다.
"""

from typing import Any, Mapping

from . import cap_form9_workspace as f9
from .cap_form10_engine import build_cap_form10_data
from .cap_shared_facts import workspace_facility_rows
from .project import Stage2Project

DIKE_KEY = "cap.safety.dike_calculation"
RULE_KEY = "cap.workspace.dike_rule"
CONTAINMENT_TYPES = ("방류벽", "방지턱", "트렌치", "기타")
FACILITY_FORMS = ("제조", "사용", "저장", "보관", "입·출하")  # 별지 제10호 주 ①
APPLICABLE, NOT_APPLICABLE = "예", "해당 없음"

EDIT_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("적용여부", "확산방지설비 적용", "이 설비에 방류벽·방지턱·트렌치 같은 확산방지설비가 있으면 '예', 없으면 '해당 없음'입니다."),
    ("설비형태", "설비 형태", "제조, 사용, 저장, 보관, 입·출하 중 하나입니다(서식 주 ①). 저장탱크는 저장으로 제안합니다."),
    ("확산방지설비 종류", "확산방지설비 종류", "방류벽, 방지턱, 트렌치 등(서식 주 ②)입니다."),
    ("필요용량 직접입력(m3)", "필요용량 직접입력(m3)", "비율 대신 검토자료로 필요용량을 알고 있을 때만 적습니다. 비우면 위 비율로 계산합니다."),
    ("직접확인 유효용량(m3)", "유효용량(m3)", "설계도서로 이미 아는 유효용량입니다. 모르면 아래 치수로 계산합니다."),
    ("내부 길이(m)", "내부 길이(m)", "방류벽 안쪽 길이입니다."),
    ("내부 폭(m)", "내부 폭(m)", "방류벽 안쪽 폭입니다."),
    ("유효높이(m)", "유효높이(m)", "액체를 담을 수 있는 높이입니다."),
    ("내부 차감용적(m3)", "내부 차감용적(m3)", "벽 안의 탱크 기초 등이 차지하는 부피입니다. 차감이 없으면 0을 적습니다."),
    ("비고", "비고", "참고할 내용을 적습니다."),
)
COLUMN_IDS = tuple(column for column, _, _ in EDIT_COLUMNS)


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object) -> float | None:
    try:
        return float(_clean(value).replace(",", ""))
    except ValueError:
        return None


def rule(project: Stage2Project) -> dict[str, str]:
    record = project.get_field(RULE_KEY)
    value = record.value if record is not None and isinstance(record.value, Mapping) else {}
    return {"비율(%)": _clean(value.get("비율(%)")), "근거": _clean(value.get("근거"))}


def suggested_form(facility_type: str) -> str:
    return {"저장탱크": "저장", "보관시설": "보관", "제조·사용시설": "제조"}.get(facility_type, "")


def edit_rows(project: Stage2Project) -> list[dict[str, Any]]:
    """One row per facility, seeded with saved input; storage tanks are proposed as applicable."""
    saved = {}
    record = project.get_field(DIKE_KEY)
    if record is not None and isinstance(record.value, list):
        saved = {_clean(r.get("대상 설비번호")): r for r in record.value if isinstance(r, Mapping)}
    out = []
    for row in f9.rows(project):
        tag = row["구분기호"]
        facility = next((f for f in workspace_facility_rows(project) if _clean(f.get("설비번호")) == tag), {})
        old = saved.get(tag, {})
        applicable = _clean(old.get("적용여부")) or (
            APPLICABLE if facility.get("시설유형") == "저장탱크" and facility.get("물질성상") == "액체" else "")
        out.append({
            "구분기호": tag, "장치·설비명": row["장치·설비명"], "설계용량(m3)": row["설계용량(m3)"],
            "적용여부": applicable,
            "설비형태": _clean(old.get("설비형태")) or suggested_form(_clean(facility.get("시설유형"))),
            "확산방지설비 종류": _clean(old.get("확산방지설비 종류")),
            "필요용량 직접입력(m3)": _clean(old.get("필요용량 직접입력(m3)")),
            **{c: _clean(old.get(c)) for c in COLUMN_IDS[4:]},
        })
    return out


def save(project: Stage2Project, rows: list[Mapping[str, Any]], ratio: str, basis: str) -> int:
    """Store rule + per-facility rows in the engine's cap.safety.dike_calculation format."""
    project.set_field(RULE_KEY, "확산방지설비 필요용량 기준(별지 제10호 작성대)",
                      {"비율(%)": _clean(ratio), "근거": _clean(basis)}, "USER_CONFIRMED",
                      note="사용자가 확인한 법 제24조 기준의 비율·근거")
    percent = _number(ratio)
    stored = []
    for row in rows:
        applicable = _clean(row.get("적용여부"))
        if not applicable:
            continue
        item: dict[str, Any] = {
            "대상 설비번호": _clean(row.get("구분기호")), "적용여부": applicable,
            "설비형태": _clean(row.get("설비형태")), "비고": _clean(row.get("비고")),
        }
        if applicable == APPLICABLE:
            direct = _clean(row.get("필요용량 직접입력(m3)"))
            capacity = _number(row.get("설계용량(m3)"))
            if direct:
                item["필요용량(m3)"], item["필요용량 기준·근거"] = direct, _clean(basis) or "회사 확인 검토자료"
            elif percent and capacity:
                item["필요용량(m3)"] = f"{round(capacity * percent / 100.0, 6):g}"
                item["필요용량 기준·근거"] = f"설계용량 × {percent:g}% — {_clean(basis)}".rstrip(" —")
            item["필요용량 직접입력(m3)"] = direct
            item["확산방지설비 종류"] = _clean(row.get("확산방지설비 종류"))
            for column in COLUMN_IDS[4:9]:
                item[column] = _clean(row.get(column))
        stored.append(item)
    project.set_field(DIKE_KEY, "확산방지설비 계산자료(별지 제10호 작성대)", stored, "USER_CONFIRMED",
                      note="CAP 작성대 별지 제10호에서 적용 대상·유효용량 입력")
    return len(stored)


def needs(project: Stage2Project) -> list[str]:
    return list(build_cap_form10_data(project).blockers)
