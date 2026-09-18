from __future__ import annotations

"""CAP Annex Forms 14–15 deterministic risk calculations.

The calculation is intentionally split from KORA/GIS generation:
- KORA / spatial analysis supplies confirmed off-site distance and people.
- The company/P&ID review supplies initiating-event counts.
- This module applies the statutory arithmetic and Appendix-3 interval scoring.

Final risk is *not* presented as an authority decision.  Under the current
review rule the National Institute of Chemical Safety determines final risk
after considering +/- risk factors.  The program therefore reports a
pre-adjustment result and leaves the authority-final field unresolved unless a
confirmed official result already exists.
"""

from dataclasses import dataclass
from collections.abc import Mapping
import math
import re
from typing import Any

from ..law_attachment_archive import approved_source_is_current
from .project import CONFIRMED_STATUSES, Stage2Project


CAP_LAW_SOURCE_KEY = "CAP_DRAFT"

# Statutory Form 14 initiating-event reference frequencies.  These values are
# version-controlled here and may be auto-used only while CAP_DRAFT is CURRENT.
# Any official attachment/version change makes approved_source_is_current()
# false until regulatory mapping is reviewed and re-approved.
INITIATING_EVENTS: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("고압용기파열", 1e-6, ("고압용기파열", "고압용기 파열")),
    ("배관파열", 1e-5, ("배관파열", "배관 파열")),
    ("배관누출", 1e-3, ("배관누출", "배관 누출")),
    ("상압 탱크 파열 및 누출", 1e-3, ("상압 탱크 파열 및 누출", "상압탱크 파열 및 누출", "상압탱크파열누출")),
    ("플랜지 등의 가스켓 파손", 1e-3, ("플랜지 등의 가스켓 파손", "플랜지 가스켓 파손", "가스켓파손")),
    ("펌프/컴프레서 누출", 1e-3, ("펌프/컴프레서 누출", "펌프 컴프레서 누출", "펌프컴프레서누출")),
    ("안전밸브 오작동 및 조기개방", 1e-2, ("안전밸브 오작동 및 조기개방", "안전밸브오작동조기개방")),
    ("냉각수 손실", 1e-1, ("냉각수 손실", "냉각수손실")),
    ("입/출하 시설 누출 사고", 1e-2, ("입/출하 시설 누출 사고", "입출하시설 누출 사고", "입출하시설누출")),
    ("외부화재", 1e-2, ("외부화재", "외부 화재")),
)

# Appendix-3 interval thresholds.  Score 0/1/2 applies below the successive
# threshold; score 3 applies at or above the last threshold.
APPENDIX3_THRESHOLDS = {
    "scenario_count": (4.0, 16.0, 64.0),
    "facility_frequency": (0.1, 1.0, 10.0),
    "offsite_distance_m": (10.0, 100.0, 1000.0),
    "population": (10.0, 100.0, 1000.0),
}


@dataclass(frozen=True)
class CAPForm14Data:
    scenario_rows: tuple[dict[str, Any], ...]
    event_rows: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.scenario_rows) and not self.blockers


@dataclass(frozen=True)
class CAPForm15Data:
    scenario_rows: tuple[dict[str, Any], ...]
    totals: dict[str, Any]
    scores: dict[str, Any]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    no_offsite_scenario: bool = False

    @property
    def ready(self) -> bool:
        return (self.no_offsite_scenario or bool(self.scenario_rows)) and not self.blockers


def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _num(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
        if not match:
            return None
        number = float(match.group())
    return number if math.isfinite(number) else None


def _int_nonnegative(value: object) -> int | None:
    number = _num(value)
    if number is None or number < 0 or abs(number - round(number)) > 1e-9:
        return None
    return int(round(number))


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    if value == 0:
        return "0"
    if 0 < abs(value) < 0.001:
        return f"{value:.6g}"
    return f"{round(float(value), 8):g}"


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


def _confirmed_rows(project: Stage2Project, *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        if isinstance(rec.value, list):
            rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def _confirmed_text(project: Stage2Project, key: str) -> str:
    rec = project.get_field(key)
    if rec is None or rec.status not in CONFIRMED_STATUSES or rec.value in (None, ""):
        return ""
    return _clean(rec.value)


def _industrial_park_state(project: Stage2Project) -> bool | None:
    text = _confirmed_text(project, "cap.business.industrial_complex")
    if not text:
        return None
    n = _norm(text)
    if n in {"해당없음", "미해당", "없음", "아니오", "no", "na"}:
        return False
    return True


def _event_count(row: Mapping[str, Any], aliases: tuple[str, ...]) -> int | None:
    raw = _row_value(row, *aliases)
    if not _clean(raw):
        return 0
    return _int_nonnegative(raw)


def _score(value: float, thresholds: tuple[float, float, float]) -> int:
    if value < thresholds[0]:
        return 0
    if value < thresholds[1]:
        return 1
    if value < thresholds[2]:
        return 2
    return 3


def _pre_adjustment_grade(base_score: int) -> str:
    if base_score >= 10:
        return "가"
    if base_score >= 6:
        return "나"
    return "다"


def _scenario_key(row: Mapping[str, Any]) -> str:
    return _clean(_row_value(row, "사고시나리오명", "사고시나리오", "시나리오명", "시나리오"))


def build_cap_form14_data(project: Stage2Project) -> CAPForm14Data:
    source_rows = _confirmed_rows(project, "cap.offsite.scenario_frequency")
    if not source_rows:
        return CAPForm14Data(
            (), (),
            ("사고시나리오별 개시사건 개수 자료가 없어 별지 제14호 시설빈도를 계산할 수 없습니다.",),
            (),
        )

    blockers: list[str] = []
    messages: list[str] = []
    event_rows: list[dict[str, Any]] = []
    scenario_rows: list[dict[str, Any]] = []

    law_current = approved_source_is_current(CAP_LAW_SOURCE_KEY)
    if not law_current:
        blockers.append(
            "현행 CAP_DRAFT 공식 별표·별지 원본이 CURRENT로 확인되지 않아 "
            "프로그램 내 개시사건 기준빈도를 자동 적용하지 않습니다."
        )

    seen: set[str] = set()
    for source_index, row in enumerate(source_rows, start=1):
        scenario = _scenario_key(row)
        if not scenario:
            blockers.append(f"{source_index}행: 사고시나리오명이 비어 있습니다.")
            continue
        if scenario in seen:
            blockers.append(f"{scenario}: 같은 사고시나리오가 시설빈도 입력표에 중복되어 있습니다.")
            continue
        seen.add(scenario)

        total = 0.0
        scenario_events: list[dict[str, Any]] = []
        for event_name, frequency, aliases in INITIATING_EVENTS:
            count = _event_count(row, aliases)
            if count is None:
                blockers.append(f"{scenario}: '{event_name}' 개수는 0 이상의 정수로 입력해 주세요.")
                continue
            accident_frequency = frequency * count if law_current else None
            if accident_frequency is not None:
                total += accident_frequency
            event = {
                "사고시나리오명": scenario,
                "개시사건": event_name,
                "기준빈도(/연)": _fmt(frequency) if law_current else "",
                "개수": count,
                "사고빈도(/연)": _fmt(accident_frequency),
            }
            scenario_events.append(event)
            event_rows.append(event)

        source_basis = _clean(_row_value(row, "개수 산정근거", "P&ID·설비 산정근거", "근거"))
        if not source_basis:
            blockers.append(
                f"{scenario}: 개시사건 개수의 산정근거(P&ID, 설비목록, 플랜지/펌프 수량 검토 등)가 비어 있습니다."
            )

        passive = _clean(_row_value(row, "수동적 완화장치", "수동적 안전성확보설비"))
        active = _clean(_row_value(row, "능동적 완화장치", "능동적 안전성확보설비"))
        safety_evidence = _clean(_row_value(row, "안전성확보설비 증빙", "증빙자료"))

        scenario_rows.append({
            "사고시나리오명": scenario,
            "시설빈도(/연)": _fmt(total) if law_current else "",
            "수동적 완화장치": passive,
            "능동적 완화장치": active,
            "안전성확보설비 증빙": safety_evidence,
            "개수 산정근거": source_basis,
        })

        if (passive or active) and not safety_evidence:
            blockers.append(
                f"{scenario}: 안전성확보설비를 기재했지만 설치·도면 반영을 확인할 증빙자료가 없습니다."
            )

    if law_current:
        messages.append(
            "별지 제14호 시설빈도는 현행 승인 CAP 원본이 CURRENT인 동안에만 "
            "기준빈도×개수의 합으로 자동계산합니다."
        )
    messages.append(
        "개시사건의 '개수'는 회사 P&ID·설비자료에서 확인하는 사실값이며 AI가 임의 추정하지 않습니다."
    )

    return CAPForm14Data(
        scenario_rows=tuple(scenario_rows),
        event_rows=tuple(event_rows),
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )


def _impact_rows(project: Stage2Project) -> list[dict[str, Any]]:
    rows = _confirmed_rows(project, "cap.offsite.scenario_impact_table")
    if rows:
        return rows

    # Legacy structured impact result can be reused only if it is already a
    # list of mappings. Free text/KORA attachment names are not parsed as facts.
    return _confirmed_rows(project, "cap.offsite.impact_range_result")


def build_cap_form15_data(project: Stage2Project) -> CAPForm15Data:
    impact_rows = _impact_rows(project)
    form14 = build_cap_form14_data(project)
    blockers: list[str] = list(form14.blockers)
    messages: list[str] = list(form14.messages)

    explicit_no_scenario = _confirmed_text(project, "cap.offsite.no_offsite_scenario")
    if _norm(explicit_no_scenario) in {"예", "yes", "y", "true", "1", "없음", "해당"}:
        if impact_rows or form14.scenario_rows:
            blockers.append(
                "장외 사고시나리오 없음으로 확인했지만 사고시나리오 영향/시설빈도 자료가 함께 존재합니다."
            )
        else:
            return CAPForm15Data(
                scenario_rows=(),
                totals={
                    "사고시나리오 총 개수(A)": 0,
                    "사고시나리오 시설빈도의 합(B)": 0.0,
                    "사고시나리오 거리의 합(C)": 0.0,
                    "주민수 합(D)": 0,
                },
                scores={
                    "사고시나리오 개수 구간점수": 0,
                    "시설빈도 구간점수": 0,
                    "거리 구간점수": 0,
                    "주민수 구간점수": 0,
                    "사고빈도점수(A+B)": 0,
                    "사고영향점수(C+D)": 0,
                    "위험도 판정표 점수(증감 전)": 0,
                    "증감 전 위험도": "다",
                    "최종 위험도": "다",
                    "최종 위험도 근거": "현행 작성규정 제23조제10항: 장외 사고시나리오가 없는 경우",
                },
                blockers=(),
                messages=(
                    "장외 사고시나리오가 없다는 회사 확정값에 따라 제24·25조 분석을 생략하고 위험도 '다'를 적용합니다.",
                ),
                no_offsite_scenario=True,
            )

    if not impact_rows:
        blockers.append(
            "KORA/GIS에서 확정된 사고시나리오별 장외거리·주민수 자료가 없어 별지 제15호를 계산할 수 없습니다."
        )
        return CAPForm15Data((), {}, {}, tuple(dict.fromkeys(blockers)), tuple(dict.fromkeys(messages)), False)

    park_state = _industrial_park_state(project)
    if park_state is None:
        blockers.append(
            "사업장의 산업단지 입주 여부가 확정되지 않아 위험도 주민수에서 근로자를 포함/제외할 수 없습니다."
        )

    freq_by_scenario = {
        _clean(row.get("사고시나리오명")): _num(row.get("시설빈도(/연)"))
        for row in form14.scenario_rows
        if _clean(row.get("사고시나리오명"))
    }

    out: list[dict[str, Any]] = []
    distance_sum = 0.0
    population_sum = 0
    scenario_count = 0
    used_scenarios: set[str] = set()

    for index, row in enumerate(impact_rows, start=1):
        scenario = _scenario_key(row)
        if not scenario:
            blockers.append(f"영향평가 {index}행: 사고시나리오명이 비어 있습니다.")
            continue
        if scenario in used_scenarios:
            blockers.append(f"{scenario}: 영향평가 자료가 중복되어 있습니다.")
            continue
        used_scenarios.add(scenario)

        distance = _num(_row_value(row, "장외거리(m)", "사고시나리오 거리(장외)", "장외거리", "거리(장외)"))
        residents = _int_nonnegative(_row_value(row, "거주민수", "거주민 수"))
        workers = _int_nonnegative(_row_value(row, "근로자수", "근로자 수"))

        if distance is None or distance < 0:
            blockers.append(f"{scenario}: KORA 장외거리(m)를 0 이상의 숫자로 확인해 주세요.")
            distance = None
        if residents is None:
            blockers.append(f"{scenario}: 영향범위 내 거주민수를 0 이상의 정수로 확인해 주세요.")
        if workers is None:
            blockers.append(f"{scenario}: 영향범위 내 근로자수를 0 이상의 정수로 확인해 주세요.")

        frequency = freq_by_scenario.get(scenario)
        if frequency is None:
            blockers.append(f"{scenario}: 별지 제14호에서 계산된 사고시나리오 시설빈도가 없습니다.")

        risk_population: int | None = None
        if residents is not None and workers is not None and park_state is not None:
            risk_population = residents if park_state else residents + workers

        if distance is not None and distance > 0:
            scenario_count += 1
            distance_sum += distance
            if risk_population is not None:
                population_sum += risk_population

        out.append({
            "연번": len(out) + 1,
            "사고시나리오 명": scenario,
            "사고시나리오 시설빈도": _fmt(frequency),
            "사고시나리오 거리(장외)": _fmt(distance),
            "거주민수": "" if residents is None else residents,
            "근로자수": "" if workers is None else workers,
            "위험도 주민수": "" if risk_population is None else risk_population,
            "갑종 보호대상 수": _clean(_row_value(row, "갑종 보호대상 수", "갑종수")),
            "을종 보호대상 수": _clean(_row_value(row, "을종 보호대상 수", "을종수")),
            "환경수용체 수": _clean(_row_value(row, "환경수용체 수", "환경수용체수")),
            "KORA/GIS 근거": _clean(_row_value(row, "KORA/GIS 근거", "KORA 결과근거", "근거자료")),
        })

        if not out[-1]["KORA/GIS 근거"]:
            blockers.append(f"{scenario}: 장외거리·주민수의 KORA/GIS 근거자료 식별자가 비어 있습니다.")

    frequency_values = [value for value in freq_by_scenario.values() if value is not None]
    facility_frequency_sum = sum(frequency_values) if frequency_values else 0.0

    totals = {
        "사고시나리오 총 개수(A)": scenario_count,
        "사고시나리오 시설빈도의 합(B)": facility_frequency_sum,
        "사고시나리오 거리의 합(C)": distance_sum,
        "주민수 합(D)": population_sum,
    }

    scores: dict[str, Any] = {}
    if not blockers:
        a_score = _score(float(scenario_count), APPENDIX3_THRESHOLDS["scenario_count"])
        b_score = _score(facility_frequency_sum, APPENDIX3_THRESHOLDS["facility_frequency"])
        c_score = _score(distance_sum, APPENDIX3_THRESHOLDS["offsite_distance_m"])
        d_score = _score(float(population_sum), APPENDIX3_THRESHOLDS["population"])
        frequency_score = a_score + b_score
        impact_score = c_score + d_score
        base_score = frequency_score + impact_score
        scores = {
            "사고시나리오 개수 구간점수": a_score,
            "시설빈도 구간점수": b_score,
            "거리 구간점수": c_score,
            "주민수 구간점수": d_score,
            "사고빈도점수(A+B)": frequency_score,
            "사고영향점수(C+D)": impact_score,
            "위험도 판정표 점수(증감 전)": base_score,
            "증감 전 위험도": _pre_adjustment_grade(base_score),
            "최종 위험도": "안전원 최종결정 전",
            "최종 위험도 근거": "현행 검토규정에 따른 위험도 증감요인 검토 후 안전원 결정",
        }
        messages.append(
            "증감 전 위험도는 별표 3 구간점수의 산술결과이며, 안전성확보설비·갑종 보호대상·환경수용체 "
            "증감요인을 반영한 최종 위험도는 화학물질안전원 결정사항으로 확정하지 않습니다."
        )

    return CAPForm15Data(
        scenario_rows=tuple(out),
        totals=totals,
        scores=scores,
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
        no_offsite_scenario=False,
    )
