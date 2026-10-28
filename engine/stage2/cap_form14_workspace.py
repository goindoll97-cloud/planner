from __future__ import annotations

"""별지 제14호(사고시나리오별 시설빈도) authoring support.

시설빈도 = Σ(개시사건 기준빈도 × 개수). 기준빈도 10종은 별지 제14호 서식 원문에 인쇄된 값이다.
개수는 시나리오 구간(설비 인입측 플랜지 ~ 연결 설비 인입측 플랜지)의 P&ID 사실이라 사람이 확인해야
하지만, 설비 유형과 압력으로 알 수 있는 것(고압용기 파열, 상압 탱크, 입·출하 시설)은 제안한다.
완화장치는 KORA 5.2와 같은 선택 목록으로 받고, 증빙이 없으면 감소요인으로 인정하지 않는다.
"""

from typing import Any, Mapping

from .cap_risk_engine import INITIATING_EVENTS, build_cap_form14_data
from .cap_scenario_workspace import LORRY_KIND, _facility_rows, evaluate as evaluate_targets, saved_scenarios
from .cap_form9_engine import _pressure_mpa
from .project import Stage2Project

FREQUENCY_KEY = "cap.offsite.scenario_frequency"
IMPACT_TABLE_KEY = "cap.offsite.scenario_impact_table"
EVENT_NAMES = tuple(name for name, _, _ in INITIATING_EVENTS)
HIGH_PRESSURE_MPA = 10 * 0.0980665   # 지침이 '특수설비'로 보는 10 kgf/cm2
ATMOSPHERIC_TANK_MPA = 0.1

PASSIVE_OPTIONS = ("방류벽", "내화설비", "지하 누출 배관 설비", "지중/지하 용기", "이중벽용기", "이중배관",
                   "통기관", "비산방지쉴드", "논씰펌프", "기타")
ACTIVE_OPTIONS = ("가스감지기와 자동차단밸브의 연동", "가스감지기와 펌프의 연동", "예비펌프", "과류방지밸브",
                  "고정식소화설비", "릴리프밸브/파열판", "방호수막/물분무", "중앙공급장치주입구",
                  "이탈방지안전시스템", "기타")
MITIGATION_NOTE = ("안전성 확보 설비는 화학물질안전원이 위험도 저감기술 사례로 인정한 경우와 시행규칙 별표 5에 따라 "
                   "필수로 설치한 경우에는 능동적 완화장치로 보지 않습니다. 그 기준 이상으로 설치한 설비만 적습니다.")
BASIS_DEFAULT = "P&ID·설비목록 검토(CAP 작성대 입력)"


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def scenario_names(project: Stage2Project) -> list[str]:
    """장외로 영향이 나가는 사고시나리오(별지 제12호 반영 결과), 없으면 확정한 시나리오 목록."""
    record = project.get_field(IMPACT_TABLE_KEY)
    if record is not None and isinstance(record.value, list) and record.value:
        return [_clean(r.get("사고시나리오명")) for r in record.value if isinstance(r, Mapping) and _clean(r.get("사고시나리오명"))]
    return [_clean(s.get("사고시나리오명")) for s in saved_scenarios(project) if _clean(s.get("사고시나리오명"))]


def suggest_counts(project: Stage2Project, scenario_name: str) -> dict[str, tuple[int, str]]:
    """개시사건별 제안 개수와 이유. 설비 유형·압력으로 알 수 있는 것만 제안한다."""
    scenario = next((s for s in saved_scenarios(project) if _clean(s.get("사고시나리오명")) == scenario_name), {})
    tag = _clean(scenario.get("대상 설비번호"))
    target = next((t for t in evaluate_targets(project) if t.tag == tag), None)
    facility = next((f for f in _facility_rows(project) if _clean(f.get("설비번호")) == tag), None)
    if target is None or facility is None:
        return {}
    try:
        gauge = float(_pressure_mpa(facility.get("운전압력")) or "nan")
    except ValueError:
        gauge = float("nan")
    out: dict[str, tuple[int, str]] = {}
    if target.kind == LORRY_KIND:
        out["입/출하 시설 누출 사고"] = (1, "탱크로리 상·하차 시설이 시나리오 대상입니다")
    elif gauge == gauge:
        if gauge >= HIGH_PRESSURE_MPA:
            out["고압용기파열"] = (1, f"운전압력 {gauge:g} MPa로 10 kgf/cm² 이상인 압력 설비입니다")
        elif str(facility.get("시설유형") or "") == "저장탱크" and gauge < ATMOSPHERIC_TANK_MPA:
            out["상압 탱크 파열 및 누출"] = (1, f"운전압력 {gauge:g} MPa인 상압 저장탱크입니다")
    return out


def rows(project: Stage2Project) -> list[dict[str, Any]]:
    """One row per accident scenario: event counts (saved value, else blank), mitigation and evidence."""
    record = project.get_field(FREQUENCY_KEY)
    saved = {}
    if record is not None and isinstance(record.value, list):
        saved = {_clean(r.get("사고시나리오명")): dict(r) for r in record.value if isinstance(r, Mapping)}
    out = []
    for name in scenario_names(project):
        old = saved.get(name, {})
        row: dict[str, Any] = {"사고시나리오명": name}
        suggestions = suggest_counts(project, name)
        for event in EVENT_NAMES:
            row[event] = old.get(event, "")
        row["제안"] = "; ".join(f"{event} {count}개({why})" for event, (count, why) in suggestions.items())
        row["개수 산정근거"] = _clean(old.get("개수 산정근거"))
        row["수동적 완화장치"] = _clean(old.get("수동적 완화장치"))
        row["능동적 완화장치"] = _clean(old.get("능동적 완화장치"))
        row["안전성확보설비 증빙"] = _clean(old.get("안전성확보설비 증빙"))
        out.append(row)
    return out


def apply_suggestions(project: Stage2Project, edited: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fill blank counts with the suggestion (never overwrite an entered value)."""
    result = []
    for row in edited:
        item = dict(row)
        for event, (count, _) in suggest_counts(project, _clean(item.get("사고시나리오명"))).items():
            if _clean(item.get(event)) == "":
                item[event] = count
        result.append(item)
    return result


def save(project: Stage2Project, edited: list[Mapping[str, Any]]) -> int:
    cleaned = []
    for row in edited:
        name = _clean(row.get("사고시나리오명"))
        if not name:
            continue
        item: dict[str, Any] = {"사고시나리오명": name}
        for event in EVENT_NAMES:
            value = _clean(row.get(event))
            item[event] = value
        item["개수 산정근거"] = _clean(row.get("개수 산정근거")) or (BASIS_DEFAULT if any(item[e] != "" for e in EVENT_NAMES) else "")
        for column in ("수동적 완화장치", "능동적 완화장치", "안전성확보설비 증빙"):
            item[column] = _clean(row.get(column))
        cleaned.append(item)
    project.set_field(FREQUENCY_KEY, "사고시나리오별 개시사건 개수(별지 제14호 작성대)", cleaned, "USER_CONFIRMED",
                      note="CAP 작성대 별지 제14호에서 개시사건 개수·완화장치 입력(개수는 P&ID 사실)")
    return len(cleaned)


def needs(project: Stage2Project) -> list[str]:
    return list(build_cap_form14_data(project).blockers)
