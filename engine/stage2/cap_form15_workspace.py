from __future__ import annotations

"""별지 제15호(위험도 분석) authoring support.

점수 계산은 cap_risk_engine이 한다(별표 3). 이 모듈은 제12·14호 결과를 모아 보여 주고, 기술지침
4-3의 위험도 구간점수 증감요인(증가: 갑종 보호대상·환경수용체, 감소: 증빙 있는 완화장치)을 계산해
참고용 결과로 보여 준다. 최종 위험도는 화학물질안전원이 결정하므로 프로그램은 확정값으로 적지 않는다.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .cap_form14_workspace import ACTIVE_OPTIONS, PASSIVE_OPTIONS, FREQUENCY_KEY
from .cap_risk_engine import _pre_adjustment_grade, build_cap_form15_data
from .project import Stage2Project

TARGETS_KEY = "cap.offsite.population_and_protected_targets"
GRADE_ORDER = ("다", "나", "가")  # 위험 낮음 → 높음
MAX_STEP = 2                       # 증감요인은 -2 ~ +2점
GRADE_SCORE = {"다": 0, "나": 6, "가": 10}  # 등급이 시작되는 합계 점수


@dataclass(frozen=True)
class Adjustment:
    increase: int
    decrease: int
    reasons: tuple[str, ...]
    counted_mitigations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def net(self) -> int:
        return self.increase - self.decrease


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _targets(project: Stage2Project) -> list[dict[str, Any]]:
    record = project.get_field(TARGETS_KEY)
    if record is None or not isinstance(record.value, list):
        return []
    return [dict(r) for r in record.value if isinstance(r, Mapping)]


def adjustment(project: Stage2Project) -> Adjustment:
    """지침 4-3 ① 2)·3): 증가요인 최대 +2, 감소요인 최대 -2."""
    reasons: list[str] = []
    categories = {_clean(t.get("보호대상 구분")) for t in _targets(project)}
    increase = 0
    if "갑종" in categories:
        increase += 1
        reasons.append("총괄영향범위에 갑종 보호대상이 1개 이상 있어 +1점")
    if "환경수용체" in categories:
        increase += 1
        reasons.append("총괄영향범위에 환경수용체가 1개 이상 있어 +1점")

    counted: list[str] = []
    record = project.get_field(FREQUENCY_KEY)
    rows = record.value if record is not None and isinstance(record.value, list) else []
    for row in rows:
        if not isinstance(row, Mapping) or not _clean(row.get("안전성확보설비 증빙")):
            continue  # 증빙 없는 완화장치는 인정하지 않는다(작성 규정 제25조 ⑤)
        for column, options in (("수동적 완화장치", PASSIVE_OPTIONS), ("능동적 완화장치", ACTIVE_OPTIONS)):
            for item in _clean(row.get(column)).split(", "):
                if item in options:
                    counted.append(f"{_clean(row.get('사고시나리오명'))}: {item}")
    decrease = min(len(counted), MAX_STEP)
    if counted:
        reasons.append(f"증빙이 있는 완화장치 {len(counted)}개 → -{decrease}점(최대 -2)")
    return Adjustment(min(increase, MAX_STEP), decrease, tuple(reasons), tuple(counted))


def reference_grade(base_score: int, net: int, base_grade: str) -> tuple[str, int]:
    """증감 후 참고 등급과 적용 점수. 등급 변화는 한 단계까지만 허용한다(지침 4-3 ① 1))."""
    adjusted = base_score + max(-MAX_STEP, min(MAX_STEP, net))
    grade = _pre_adjustment_grade(adjusted)
    base_index = GRADE_ORDER.index(base_grade)
    index = max(base_index - 1, min(base_index + 1, GRADE_ORDER.index(grade)))
    return GRADE_ORDER[index], adjusted


@dataclass(frozen=True)
class RiskAnalysis:
    scenario_rows: tuple[dict[str, Any], ...]
    totals: Mapping[str, Any]
    scores: Mapping[str, Any]
    blockers: tuple[str, ...]
    messages: tuple[str, ...]
    no_offsite_scenario: bool
    adjustment: Adjustment
    reference_grade: str
    reference_score: int | None


def analysis(project: Stage2Project) -> RiskAnalysis:
    data = build_cap_form15_data(project)
    adj = adjustment(project)
    grade, score = "", None
    base_score = data.scores.get("위험도 판정표 점수(증감 전)") if data.scores else None
    if data.no_offsite_scenario:
        grade, score = "다", 0
    elif base_score is not None:
        grade, score = reference_grade(int(base_score), adj.net, str(data.scores["증감 전 위험도"]))
    return RiskAnalysis(data.scenario_rows, data.totals, data.scores, data.blockers, data.messages,
                        data.no_offsite_scenario, adj, grade, score)
