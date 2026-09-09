from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LawSource:
    key: str
    regime: str
    title: str
    source_type: str
    effective_date: str
    source_url: str = ""
    attachment_required: bool = False


# v0.1 baseline. API identifiers/hash values are intentionally not guessed here.
# They will be populated only after the official Open API responses are wired in.
DEFAULT_SOURCES: tuple[LawSource, ...] = (
    LawSource("CAP_ACT", "화사계", "화학물질관리법 및 하위법령", "법령", "", attachment_required=False),
    LawSource("CAP_DRAFT", "화사계", "화학사고예방관리계획서 작성 등에 관한 규정", "행정규칙", "", attachment_required=True),
    LawSource("CAP_QTY", "화사계", "유해화학물질의 규정수량에 관한 규정", "행정규칙", "", attachment_required=True),
    LawSource("CAP_IMPL", "화사계", "화학사고예방관리계획서 이행 등에 관한 규정", "행정규칙", "", attachment_required=True),
    LawSource("PSM_ACT", "PSM", "산업안전보건법 및 하위법령", "법령", "", attachment_required=False),
    LawSource("PSM_APP13", "PSM", "산업안전보건법 시행령 별표 13", "법령 별표", "", attachment_required=True),
    LawSource("PSM_NOTICE", "PSM", "공정안전보고서 제출·심사·확인 및 이행상태평가 관련 고시", "행정규칙", "", attachment_required=True),
)


def file_sha256(path: str | Path) -> str:
    h = sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def bytes_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def source_rows(sources: Iterable[LawSource] = DEFAULT_SOURCES) -> list[dict[str, object]]:
    return [asdict(source) for source in sources]


def overall_sync_gate(status_rows: list[dict[str, object]] | None = None) -> dict[str, str]:
    """Conservative gate used until official API/PDF monitor is connected.

    The initial app deliberately reports MONITOR_NOT_CONNECTED instead of
    pretending that the embedded regulatory data are current.
    """
    if not status_rows:
        return {
            "status": "MONITOR_NOT_CONNECTED",
            "label": "법령 자동감시 미연결",
            "decision": "HOLD",
            "message": "법제처 Open API와 첨부 PDF 버전 감시가 아직 연결되지 않아 법적 확정판정을 보류합니다.",
        }

    bad = [row for row in status_rows if row.get("status") not in {"CURRENT", "VERIFIED"}]
    if bad:
        return {
            "status": "UPDATE_OR_UNVERIFIED",
            "label": "법령 변경/미검증 자료 있음",
            "decision": "HOLD",
            "message": "최신본과 프로그램 반영본이 일치하지 않는 자료가 있어 관련 판정을 보류합니다.",
        }
    return {
        "status": "CURRENT",
        "label": "법령 최신성 확인 완료",
        "decision": "ALLOW",
        "message": "감시대상 법령과 첨부자료가 검증된 최신본과 일치합니다.",
    }
