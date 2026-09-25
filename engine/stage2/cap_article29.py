"""Data-driven, conservative Article 29 follow-up suggestions for CAP form 02."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

RULES_FILE = Path(__file__).resolve().parents[2] / 'data' / 'stage2' / 'cap_article29_rules.json'
FACT_LABELS = {
    'same_site': '동일 사업장 내 변경 여부',
    'cap_submission': '변경된 화학사고예방관리계획서 제출 필요 여부',
    'boundary_or_other': '부지 경계로의 위치 변경 또는 그 밖의 제2호다목 시설 변경 해당 여부',
    'scenario_amount': '변경 후 취급량의 사고시나리오 규정량 이상 여부',
    'impact_expanded': '총괄영향범위 확대 여부',
    'transport': '운반업 해당 여부',
    'trial': '제2호나목 시범생산 해당 여부',
    'quantity_band': '물질별 변경 후 취급량의 규정수량 구간',
    'holding_band': '물질별 변경 후 최대보유량의 규정수량 구간',
    'capacity_threshold_applies': '운반시설 용량 누적 50% 증가에 따른 제1호가목 적용 여부',
    'storage_kind': '시설 종류(보관·저장시설인지 운반시설인지)',
    'storage_ratio': '최초 허가·신고 또는 최근 변경허가·변경신고 이후 시설용량 누적 증가율',
    'holding_ratio': '최초 허가·신고 또는 최근 변경허가·변경신고 이후 최대보유량 합계 누적 증가율',
    'market_unrelated': '시장출시와 직접적인 관계가 없는지',
    'trial_days': '시범생산 기간(일)',
    'temporary_material': '취급물질의 일시 변경 여부',
}


def load_rules() -> dict[str, Any]:
    data = json.loads(RULES_FILE.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError('제29조 규칙 데이터 버전을 확인하세요.')
    return data


def law_ready(data: Mapping[str, Any], observation: Mapping[str, Any] | None, approved_current: bool) -> bool:
    """Approval alone cannot enable a newer version than the one mapped in JSON."""
    return bool(observation and approved_current and observation.get('observation_valid')
                and str(observation.get('serial')) == str(data['serial'])
                and ''.join(c for c in str(observation.get('effective_date', '')) if c.isdigit()) == data['effective_date'])


def cumulative_ratio(baseline: float | None, current: float | None) -> float | None:
    if baseline is None or current is None or baseline <= 0 or current < 0:
        return None
    return (current - baseline) / baseline


def _check(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        operator, threshold = next(iter(expected.items()))
        return {'gte': lambda: actual >= threshold, 'lte': lambda: actual <= threshold,
                'lt': lambda: actual < threshold}[operator]()
    return type(actual) is type(expected) and actual == expected


def assess(status: str, events: list[str], facts: Mapping[str, Any], *,
           data: Mapping[str, Any] | None = None, law_current: bool = False) -> dict[str, Any]:
    data = data or load_rules()
    if not law_current:
        return {'state': '법령 변경 확인 필요', 'candidates': [], 'missing': ['현행 제29조와 구조화 규칙의 재대조·승인']}
    if status not in ('영업허가', '영업신고'):
        return {'state': '확인 필요', 'candidates': [], 'missing': ['유해화학물질 영업 상태(영업허가·영업신고)']}
    if not events:
        return {'state': '확인 필요', 'candidates': [], 'missing': ['변경사항 유형']}
    candidates, missing = [], []
    for event in events:
        matches = [r for r in data['rules'] if r['status'] == status and r['event'] == event]
        if not matches:
            missing.append(f'{event}: 제29조 해당 여부 및 영업 형태 변경 여부 별도 검토')
            continue
        for rule in matches:
            unknown = []
            rejected = False
            for field, expected in rule['conditions'].items():
                actual = facts.get(field)
                if actual is None or actual == '미확인':
                    unknown.append(FACT_LABELS[field])
                elif not _check(actual, expected):
                    rejected = True
                    break
            if rejected:
                continue
            if unknown:
                missing.extend(unknown)
            else:
                candidates.append(rule)
        # A changed site can move a 신고 business into the 허가 regime (Article 29(8)).
        if status == '영업신고' and event in ('site', 'material', 'storage_capacity', 'holding_total'):
            if facts.get('permit_transition') is None:
                missing.append('시행규칙 제27조제1항 영업허가 전환 해당 여부(제29조제8항)')
            elif facts.get('permit_transition'):
                missing.append('제29조제8항: 변경 전 영업허가 필요 여부 관할기관 확인')
    missing = list(dict.fromkeys(missing))
    return {'state': '확인 필요' if missing else ('후보 제안' if candidates else '별도 검토'),
            'candidates': candidates, 'missing': missing}
