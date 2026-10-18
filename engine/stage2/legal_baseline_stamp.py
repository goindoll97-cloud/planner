"""작성본 버전에 '어느 법령판으로 썼는지'와 '그때의 규칙 판정 결과'를 남긴다.

버전 스냅샷(``versioning.freeze_version``)이 저장될 때 함께 기록된다. 나중에 법령이
개정되면 ``legal_refresh``가 이 기록과 현재 승인된 법령판·판정표를 비교해, 기존 작성본의
어느 부분을 다시 확인해야 하는지 찾는다.

이 모듈은 기록만 한다. 실패해도 버전 저장을 막지 않도록 모든 함수는 예외를 삼키고
빈 기록을 돌려준다(빈 기록은 '법령판 기록 없음'으로 다뤄진다).
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

STAMP_SCHEMA = "legal-baseline-stamp-v1"
DERIVED_SCHEMA = "legal-derived-results-v1"

# 법령판 동일성 판단에 쓰는 공식 메타데이터(law_monitor._official_metadata_changes와 같은 항목).
IDENTITY_FIELDS = ("serial", "effective_date", "issue_date", "issue_number")
# 별지 제1호 행에서 규정수량 판정과 직접 관계된 열만 비교한다(보유량은 회사 입력값이라 제외).
FORM1_COMPARE_COLUMNS = ("물질구분", "하위규정수량(ton)", "상위규정수량(ton)", "규정수량 비교", "법령DB", "법령항목")


def _hash_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(text.encode("utf-8")).hexdigest()


def approved_law_sources(approved_file: Path | None = None) -> dict[str, Any]:
    """현재 승인된 법령 감시 기준선(law_monitor_approved.json의 sources)."""
    try:
        if approved_file is None:
            from engine.law_monitor import APPROVED_FILE

            approved_file = APPROVED_FILE
        if not Path(approved_file).exists():
            return {}
        payload = json.loads(Path(approved_file).read_text(encoding="utf-8"))
        sources = payload.get("sources", {}) if isinstance(payload, dict) else {}
        return sources if isinstance(sources, dict) else {}
    except Exception:
        return {}


def law_identity(source: Mapping[str, Any]) -> dict[str, Any]:
    """법령 하나의 판 식별 정보. 첨부원본은 해시 목록 전체를 하나의 지문으로 줄인다."""
    row = {field: str(source.get(field, "") or "").strip() for field in IDENTITY_FIELDS}
    row["title"] = str(source.get("title", "") or "")
    row["regime"] = str(source.get("regime", "") or "")
    hashes = source.get("attachment_hashes") or {}
    row["attachment_fingerprint"] = _hash_json(hashes) if hashes else ""
    row["attachment_titles"] = dict(source.get("attachment_titles") or {})
    return row


def current_legal_baseline(approved_sources: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """지금 프로그램이 따르는 법령판 기록. 승인 기준선이 없으면 sources가 빈 기록."""
    sources = approved_law_sources() if approved_sources is None else approved_sources
    try:
        laws = {
            str(key): law_identity(value)
            for key, value in dict(sources).items()
            if isinstance(value, Mapping)
        }
    except Exception:
        laws = {}
    return {"schema_version": STAMP_SCHEMA, "laws": laws}


def _form1_rows(project) -> list[dict[str, Any]]:
    from .cap_form1_engine import build_cap_form1_data

    data = build_cap_form1_data(project)
    rows: list[dict[str, Any]] = []
    for row in data.chemical_rows:
        item = {
            "물질명": str(row.get("물질명", "") or ""),
            "CAS No.": str(row.get("CAS No.", "") or ""),
        }
        for column in FORM1_COMPARE_COLUMNS:
            item[column] = str(row.get(column, "") or "")
        rows.append(item)
    return rows


def derived_results(project, doc: str) -> dict[str, Any]:
    """규칙 엔진 판정 결과 중 법령 개정으로 바뀔 수 있는 값만 남긴다."""
    result: dict[str, Any] = {
        "schema_version": DERIVED_SCHEMA,
        "cap_group": str(getattr(project, "cap_group", "") or ""),
        "cap_required": getattr(project, "cap_required", None),
        "psm_required": getattr(project, "psm_required", None),
    }
    if doc == "CAP":
        try:
            result["cap_form1"] = _form1_rows(project)
        except Exception:
            result["cap_form1"] = None  # 계산 불가 — 비교 때 '이전 결과 없음'으로 처리
    return result
