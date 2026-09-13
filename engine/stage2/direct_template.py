from __future__ import annotations

from datetime import datetime
import uuid

from .project import Stage2Project
from .standalone_entry import DIRECT_ENTRY_MODE


def create_direct_entry_template_project(
    *,
    psm_selected: bool,
    cap_selected: bool,
    cap_group: str = "",
    project_id: str | None = None,
) -> Stage2Project:
    """Build an in-memory project used only to generate direct-entry workbooks.

    No Stage 1 legal applicability decision is created. The selected systems
    describe the author's intended Stage 2 document scope only.
    """
    if not psm_selected and not cap_selected:
        raise ValueError("작성할 문서를 하나 이상 선택하세요.")

    normalized_group = str(cap_group or "").strip()
    if cap_selected and normalized_group not in {"1군", "2군"}:
        raise ValueError("화학사고예방관리계획서를 선택한 경우 1군 또는 2군 작성수준을 선택하세요.")
    if not cap_selected:
        normalized_group = ""

    pid = str(project_id or "").strip()
    if not pid:
        pid = f"S2-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    project = Stage2Project(
        project_id=pid,
        company_name="미지정 사업장",
        psm_required=bool(psm_selected),
        cap_required=bool(cap_selected),
        cap_group=normalized_group,
        scope_confirmed=True,
        psm_selected=bool(psm_selected),
        cap_selected=bool(cap_selected),
        stage1_snapshot={
            "entry_mode": DIRECT_ENTRY_MODE,
            "legal_applicability_confirmed": False,
            "template_only": True,
            "decision": {},
            "business": {},
            "documents": {},
            "chemicals": [],
            "facilities": [],
        },
        notes=[
            "Stage 1 판정진단 없이 Stage 2를 직접 시작하기 위한 입력파일 생성용 임시 프로젝트입니다."
        ],
    )

    if cap_selected:
        project.set_field(
            "cap.business.writing_level",
            "작성수준",
            f"{normalized_group} 사업장",
            "USER_CONFIRMED",
            note="Stage 2 직접 시작 입력파일 생성 시 사용자가 선택한 작성수준",
        )

    return project
