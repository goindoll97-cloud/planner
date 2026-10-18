"""법령 개정에 대한 '프로그램 규칙 매핑 검토' 확인 기록.

실제 법령·고시가 개정되면 최신본 업데이트는 자동 승인하지 않고 멈춘다. 판정·작성 규칙이 새 조문과
맞는지는 프로그램이 스스로 증명할 수 없기 때문이다. 담당자가 개정 전후 조문을 보고 규칙을 확인했다면
그 사실을 여기에 남기고, 그 기록이 있는 **정확히 그 판**만 업데이트가 통과시킨다.

- 확인은 판 단위다: 일련번호·시행일·공포일·공포번호·첨부 해시가 하나라도 달라지면 기록은 무효가 된다.
  다음 개정은 다시 검토해야 한다.
- 확인자 이름이 없으면 기록하지 않는다.
- 이 모듈은 승인 자체를 하지 않는다. 승인(새 감시 기준선 저장)은 기존 업데이트 절차가 그대로 맡는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_FILE = PROJECT_ROOT / "data" / "runtime" / "rule_mapping_reviews.json"
SCHEMA = "rule-mapping-reviews-v1"
IDENTITY_FIELDS = ("serial", "effective_date", "issue_date", "issue_number")


def review_fingerprint(row: Mapping[str, Any]) -> str:
    """관찰된 법령판 하나를 가리키는 지문(메타데이터 + 첨부 해시)."""
    payload = {
        "key": str(row.get("key", "") or ""),
        **{field: str(row.get(field, "") or "").strip() for field in IDENTITY_FIELDS},
        "attachment_hashes": {str(k): str(v) for k, v in dict(row.get("attachment_hashes") or {}).items()},
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        if not Path(path).exists():
            return {}
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        reviews = value.get("reviews", {}) if isinstance(value, dict) else {}
        return reviews if isinstance(reviews, dict) else {}
    except Exception:
        return {}


def load_reviews(path: Path | None = None) -> dict[str, Any]:
    return _load(REVIEW_FILE if path is None else path)


def is_reviewed(row: Mapping[str, Any], path: Path | None = None) -> bool:
    key = str(row.get("key", "") or "")
    record = load_reviews(path).get(key)
    return bool(
        key
        and isinstance(record, Mapping)
        and str(record.get("reviewer", "")).strip()
        and record.get("fingerprint") == review_fingerprint(row)
    )


def review_record(row: Mapping[str, Any], path: Path | None = None) -> dict[str, Any] | None:
    return load_reviews(path).get(str(row.get("key", "") or "")) if is_reviewed(row, path) else None


def record_reviews(
    rows: Iterable[Mapping[str, Any]],
    *,
    reviewer: str,
    memo: str = "",
    path: Path | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """관찰된 판(rows)에 대한 검토 확인을 저장한다. 확인자 이름은 필수."""
    reviewer = str(reviewer or "").strip()
    selected = [dict(row) for row in rows]
    if not reviewer:
        return {"status": "REVIEWER_REQUIRED", "recorded": 0, "message": "확인자 이름을 입력해야 검토 확인을 기록할 수 있습니다."}
    if not selected:
        return {"status": "NOTHING_TO_RECORD", "recorded": 0, "message": "기록할 법령이 없습니다."}
    target = REVIEW_FILE if path is None else Path(path)
    reviews = _load(target)
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in selected:
        key = str(row.get("key", "") or "")
        if not key:
            continue
        reviews[key] = {
            "fingerprint": review_fingerprint(row),
            "title": str(row.get("title", "") or ""),
            "serial": str(row.get("serial", "") or ""),
            "effective_date": str(row.get("effective_date", "") or ""),
            "issue_date": str(row.get("issue_date", "") or ""),
            "issue_number": str(row.get("issue_number", "") or ""),
            "change_reason": [str(v) for v in (row.get("change_reason") or [])],
            "reviewer": reviewer,
            "memo": str(memo or "").strip(),
            "reviewed_at_utc": stamp,
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": SCHEMA, "reviews": reviews}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"status": "RECORDED", "recorded": len(selected), "message": f"{len(selected)}개 법령의 검토 확인을 기록했습니다."}
