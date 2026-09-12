from __future__ import annotations

"""Central fail-closed gate before any CAP/PSM legal decision.

The law monitor answers whether the official current source still matches the
approved monitoring baseline.  This module adds the second half of the trust
chain: every decision DB must exist and must be traceable to a PDF hash that is
still present in the current official observation.
"""

import json
from pathlib import Path
from typing import Any, Iterable

from .law_monitor import overall_sync_gate
from .legal_archive import EVIDENCE_CONFIG, evidence_for_key


REQUIRED_REGULATORY_KEYS = tuple(EVIDENCE_CONFIG.keys())


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def regulatory_provenance_rows(keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Build provenance rows for the approved decision DBs.

    New approvals record ``source_pdf_sha256`` directly in the approval audit.
    Older PSM/CAP3 approvals can still be accepted only when the legal evidence
    archive has already verified the approved CSV against the current candidate
    and archived the exact supporting PDF.  That archived SHA then acts as the
    legacy provenance bridge.
    """
    wanted = tuple(keys) if keys is not None else REQUIRED_REGULATORY_KEYS
    rows: list[dict[str, Any]] = []
    for key in wanted:
        config = EVIDENCE_CONFIG.get(key)
        if config is None:
            rows.append(
                {
                    "key": key,
                    "law_key": "",
                    "approved_exists": False,
                    "audit_hash": "",
                    "evidence_hash": "",
                    "source_hash": "",
                    "provenance_mode": "UNKNOWN_CONFIG",
                }
            )
            continue

        approved = Path(config["approved"])
        audit = _read_json(Path(config["audit"]))
        audit_hash = str(audit.get("source_pdf_sha256") or "").strip()
        evidence = evidence_for_key(key) or {}
        evidence_hash = str(evidence.get("sha256") or "").strip()

        if audit_hash:
            source_hash = audit_hash
            mode = "APPROVAL_AUDIT"
        elif evidence_hash:
            source_hash = evidence_hash
            mode = "VERIFIED_ARCHIVE"
        else:
            source_hash = ""
            mode = "UNVERIFIED"

        rows.append(
            {
                "key": key,
                "law_key": str(config.get("law_key") or ""),
                "label": str(config.get("label") or key),
                "approved_file": str(approved),
                "approved_exists": approved.exists(),
                "audit_hash": audit_hash,
                "evidence_hash": evidence_hash,
                "source_hash": source_hash,
                "provenance_mode": mode,
            }
        )
    return rows


def evaluate_decision_readiness(
    law_rows: list[dict[str, Any]] | None,
    provenance_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure readiness evaluation used by the UI and unit tests."""
    law_gate = overall_sync_gate(law_rows)
    blockers: list[str] = []

    if law_gate.get("decision") != "ALLOW":
        blockers.append(str(law_gate.get("message") or "법령 최신성 확인이 필요합니다."))

    source_map = {
        str(row.get("key") or ""): row
        for row in (law_rows or [])
        if str(row.get("key") or "")
    }

    for row in provenance_rows:
        key = str(row.get("key") or "")
        label = str(row.get("label") or key)
        law_key = str(row.get("law_key") or "")

        if not bool(row.get("approved_exists")):
            blockers.append(f"{label}: 판정용 승인 DB가 없습니다.")
            continue

        source = source_map.get(law_key)
        if not source:
            blockers.append(f"{label}: 연결된 공식 법령자료({law_key})의 최신 관측값이 없습니다.")
            continue
        if source.get("monitor_status") != "CURRENT":
            blockers.append(f"{label}: 연결된 공식 법령자료({law_key})가 CURRENT 상태가 아닙니다.")
            continue

        official_hashes = {
            str(value).strip()
            for value in (source.get("attachment_hashes") or {}).values()
            if str(value).strip()
        }
        source_hash = str(row.get("source_hash") or "").strip()
        audit_hash = str(row.get("audit_hash") or "").strip()
        evidence_hash = str(row.get("evidence_hash") or "").strip()

        if not source_hash:
            blockers.append(
                f"{label}: 승인 DB가 어느 공식 PDF에서 만들어졌는지 SHA-256 근거를 확인할 수 없습니다. "
                "최신 PDF에서 다시 추출·검토·승인하거나 근거 PDF를 동기화하세요."
            )
            continue
        if not official_hashes:
            blockers.append(f"{label}: 현재 공식 PDF SHA-256을 확인할 수 없습니다.")
            continue
        if source_hash not in official_hashes:
            blockers.append(
                f"{label}: 승인 DB의 근거 PDF SHA-256이 현재 공식 PDF와 일치하지 않습니다."
            )
            continue
        if audit_hash and evidence_hash and audit_hash != evidence_hash:
            blockers.append(
                f"{label}: 승인 감사기록과 보관 근거 PDF의 SHA-256이 서로 다릅니다."
            )

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        return {
            "status": "HOLD",
            "label": "판정 준비상태 확인 필요",
            "decision": "HOLD",
            "message": "법령 최신성 또는 승인 규정 DB의 출처 연결이 완전히 검증되지 않아 판정을 시작하지 않습니다.",
            "blockers": blockers,
        }

    return {
        "status": "READY",
        "label": "법령·규정 DB 검증 완료",
        "decision": "ALLOW",
        "message": "현재 공식 법령/PDF와 판정용 승인 DB의 SHA-256 출처 연결이 확인되었습니다.",
        "blockers": [],
    }


def decision_readiness_gate(law_rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    return evaluate_decision_readiness(law_rows, regulatory_provenance_rows())
