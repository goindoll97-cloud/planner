"""사업장 업무에 올린 자료에서 읽은 값으로 별지 제12호 사고시나리오 표의 계산 입력을 채웁니다.

설비번호가 같은 확인 완료 사실만 쓰고, 담당자가 표에 이미 적은 값은 덮어쓰지 않습니다.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import cap_release_workspace as rw
from . import evidence_workspace as ew

# 자료 항목 → 별지 제12호 시나리오 표의 열
COLUMNS = {"liquid_head": rw.HEAD_COLUMN, "boundary_distance": rw.BOUNDARY_COLUMN, "leak_pipe": rw.LEAK_PIPE_COLUMN,
           "combustion_heat": rw.HEAT_COLUMN, "boiling_point": rw.BOILING_COLUMN, "liquid_cp_kj": rw.LIQUID_CP_KJ_COLUMN,
           "vaporization_heat": rw.VAPORIZATION_COLUMN, "latent_heat": rw.LATENT_HEAT_COLUMN,
           "liquid_cp": rw.LIQUID_CP_COLUMN, "vapor_density": rw.VAPOR_DENSITY_COLUMN}
GRADE_FIELDS = {"leak_detection": "누출 감지 등급", "leak_isolation": "누출 차단 등급"}


def _text(value: Any) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _slots(project, tag: str, fields) -> list[dict]:
    entity = "facility:" + str(tag).strip()
    return [s for s in ew.slots(project) if s["entity"] == entity and s["field"] in fields and s["chosen"]]


def inputs_for(project, tag: str) -> dict[str, str]:
    """설비번호의 확인 완료 값을 시나리오 표 열 이름으로 돌려줍니다."""
    return {COLUMNS[s["field"]]: _text(s["chosen"]["value"]) for s in _slots(project, tag, COLUMNS)}


def sources_for(project, tag: str) -> list[dict]:
    """채운 값의 출처(파일·위치·자동/확인 구분)."""
    rows = []
    for s in _slots(project, tag, COLUMNS):
        fact = s["chosen"]
        rows.append({"설비": tag, "항목": COLUMNS[s["field"]], "값": _text(fact["value"]), "파일": fact["document"],
                     "위치": fact["location"], "확정": "자동 기입" if s["method"] == "AUTO" else "담당자 확인"})
    return rows


def autofill(project, rows: list[Mapping[str, Any]]) -> tuple[list[dict], list[dict]]:
    """빈 칸만 자료의 값으로 채운 행과, 채운 값의 출처를 돌려줍니다."""
    filled, sources = [], []
    for row in rows:
        row = dict(row)
        tag = str(row.get("대상 설비번호", "")).strip()
        if tag:
            for column, value in inputs_for(project, tag).items():
                if not str(row.get(column, "") or "").strip():
                    row[column] = value
            sources.extend(s for s in sources_for(project, tag) if str(row.get(s["항목"], "")) == s["값"])
        filled.append(row)
    return filled, sources


def grade_defaults(project, tags) -> dict[str, str]:
    """대상 설비 모두에서 같게 확인된 감지·차단 등급. 설비마다 다르면 보수적으로 고르게 비워 둡니다."""
    result = {}
    for field, label in GRADE_FIELDS.items():
        values = {s["chosen"]["value"] for tag in tags for s in _slots(project, tag, (field,))}
        found = [_slots(project, tag, (field,)) for tag in tags]
        if len(values) == 1 and all(found):
            result[field] = values.pop()
    return result


def frequency_for(project, tag: str) -> dict[str, str]:
    """별지 제14호 열 이름(개시사건 개수·개수 산정근거·완화장치·증빙)으로 돌려줍니다."""
    labels = {**ew.EVENT_FIELDS, **ew.FORM14_TEXT_LABELS}
    return {labels[s["field"]]: _text(s["chosen"]["value"]) for s in _slots(project, tag, labels)}


def frequency_sources(project, tag: str) -> list[dict]:
    labels = {**ew.EVENT_FIELDS, **ew.FORM14_TEXT_LABELS}
    return [{"설비": tag, "항목": labels[s["field"]], "값": _text(s["chosen"]["value"]), "파일": s["chosen"]["document"],
             "위치": s["chosen"]["location"], "확정": "자동 기입" if s["method"] == "AUTO" else "담당자 확인"}
            for s in _slots(project, tag, labels)]
