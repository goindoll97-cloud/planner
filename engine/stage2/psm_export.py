from __future__ import annotations

"""공정안전보고서용 점검·내보내기. 실제 로직은 화학사고예방관리계획서와 공용인 report_export에 있다."""

from . import report_export as _shared
from .report_export import (  # noqa: F401  (호환용 재노출)
    DOCX_MIME, STATUS_LABELS, ExportState, Outputs, acknowledge_holds, confirm, downloads_allowed,
)
from .project import Stage2Project

SYSTEM = "PSM"


def evaluate(project: Stage2Project) -> ExportState:
    return _shared.evaluate(project, SYSTEM)


def build_outputs(project: Stage2Project, *, final_ready: bool) -> Outputs:
    return _shared.build_outputs(project, final_ready=final_ready, system=SYSTEM)
