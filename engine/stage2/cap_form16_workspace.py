from __future__ import annotations

"""별지 제16호(비상대응분야 요약서) authoring support.

일반정보·사고시나리오 물질·시나리오 표는 앞 서식에서 자동으로 오고(cap_form16_engine), 사람은
회사의 비상대응 서술만 적는다. 항목마다 넣을 내용은 작성 규정 제27~34조 원문(체크리스트)이고,
앞 서식 정보로 만들 수 있는 초안(응급의료 후보, 지역사회 고지 대상)은 비어 있을 때만 제안한다.
"""

from typing import Any, Mapping

from . import cap_form8_workspace as f8
from .cap_form16_engine import build_cap_form16_data
from .cap_workspace import load_form_schema
from .project import CONFIRMED_STATUSES, Stage2Project

TARGETS_KEY = "cap.offsite.population_and_protected_targets"


def items(group: str | None = None) -> list[dict[str, Any]]:
    entries = load_form_schema(16)["items"]
    return [item for item in entries if group is None or item["group"] == group]


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def current_text(project: Stage2Project, item: Mapping[str, Any]) -> str:
    record = project.get_field(item["key"])
    if record is None or record.status not in CONFIRMED_STATUSES or record.value is None:
        return ""
    return _clean(record.value)


def _medical_seed(project: Stage2Project) -> str:
    hospitals = [r for r in f8.saved_rows(project) if _clean(r.get("세부유형")) == "의료시설"]
    if not hospitals:
        return ""
    lines = [f"- {_clean(r.get('보호대상 명칭'))} (사업장 경계에서 약 {_clean(r.get('사업장 경계와 거리(m)'))}m)" for r in hospitals]
    return ("응급의료기관 후보(사업장 주변 의료시설, 실제 응급의료기관 여부·연락처·이동경로·이동시간을 확인해 고치세요):\n"
            + "\n".join(lines))


def _notice_seed(project: Stage2Project) -> str:
    record = project.get_field(TARGETS_KEY)
    rows = record.value if record is not None and isinstance(record.value, list) else []
    names = [_clean(r.get("보호대상 명칭")) for r in rows if isinstance(r, Mapping) and _clean(r.get("보호대상 명칭"))]
    if not names:
        return ""
    return ("고지대상: 총괄영향범위 내 보호대상 " + f"{len(names)}건 — " + ", ".join(names)
            + "\n고지방법: 화학물질종합정보시스템 등록(필수) + (시행규칙 제19조의4 제2항에 따른 방법 중 1가지 이상을 선택해 적으세요)")


def _contact_seed(project: Stage2Project) -> str:
    return ("사고 발견자 → 비상대응 연락 담당자 → 유관기관(소방 119, 경찰 112 등)·인근 사업장 순으로 전파하며, "
            "사고 발생 시 15분 이내 유관기관에 신고한다. (주간·야간·공휴일 신고체계와 담당자 연락처를 이어서 적으세요)")


SEEDS = {"contact": _contact_seed, "medical": _medical_seed, "notice": _notice_seed}


def seed(project: Stage2Project, item: Mapping[str, Any]) -> str:
    builder = SEEDS.get(item["id"])
    return builder(project) if builder else ""


def save_text(project: Stage2Project, item: Mapping[str, Any], text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    project.set_field(item["key"], item["label"], value, "USER_CONFIRMED",
                      note=f"CAP 작성대 별지 제16호에서 입력({item['law']})")
    return True


def external_required(project: Stage2Project) -> bool:
    return project.cap_group == "1군"


def missing(project: Stage2Project) -> list[str]:
    out = []
    for item in items():
        if item["group"] == "external" and not external_required(project):
            continue
        if not current_text(project, item):
            out.append(item["label"])
    return out


def status(project: Stage2Project):
    return build_cap_form16_data(project)
