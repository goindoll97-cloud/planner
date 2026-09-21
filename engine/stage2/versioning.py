"""사업장 작성자료의 버전 스냅샷과 필드 단위 변경점 비교.

project.json은 "현재 작업본"으로 그대로 두고, 제출 시점마다 불변 스냅샷을
``versions/`` 아래에 저장한다. 프로젝트 스키마를 바꾸지 않으므로 기존 데이터
마이그레이션이 필요 없다. 회사사실은 CAP·PSM이 공유하므로 스냅샷은 프로젝트
전체 필드를 담고, 문서 종류(CAP/PSM)는 버전 메타데이터로만 구분한다.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from .project import FieldRecord, Stage2Project
from .storage import DEFAULT_ROOT, _safe_component, project_dir

DOC_TYPES = ("CAP", "PSM")
# 새 주 버전(v2.0)을 여는 제출유형과, 부 버전(v1.1)만 올리는 제출유형.
MAJOR_KINDS = ("신규", "재제출")
MINOR_KINDS = ("변경",)
SNAPSHOT_SCHEMA = "stage2-version-snapshot-v1"


class UnfrozenChangesError(RuntimeError):
    """작업본에 아직 스냅샷으로 저장하지 않은 변경이 있어 덮어쓸 수 없다."""


@dataclass(frozen=True)
class VersionMeta:
    version_id: str
    doc: str
    kind: str
    label: str = ""
    note: str = ""
    parent_id: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class FieldChange:
    key: str
    label: str
    change: str  # ADDED / REMOVED / CHANGED
    old: Any = None
    new: Any = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def versions_dir(project_id: str, root: Path = DEFAULT_ROOT) -> Path:
    return project_dir(project_id, root) / "versions"


def _snapshot_path(project_id: str, version_id: str, root: Path) -> Path:
    return versions_dir(project_id, root) / f"{_safe_component(version_id)}.json"


def _write_json_atomic(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    fd, tmp_name = tempfile.mkstemp(prefix="version_", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _parse_version(version_id: str) -> tuple[int, int]:
    match = re.search(r"v(\d+)\.(\d+)$", version_id)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def list_versions(project_id: str, doc: str | None = None, root: Path = DEFAULT_ROOT) -> list[VersionMeta]:
    """저장된 버전을 오래된 순으로 돌려준다(같은 문서 안에서는 버전 번호순)."""
    folder = versions_dir(project_id, root)
    if not folder.exists():
        return []
    rows: list[VersionMeta] = []
    for path in folder.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            meta = VersionMeta(**raw["meta"])
        except Exception:
            continue
        if doc is None or meta.doc == doc:
            rows.append(meta)
    rows.sort(key=lambda m: (m.doc, _parse_version(m.version_id)))
    return rows


def next_version_id(project_id: str, doc: str, kind: str, root: Path = DEFAULT_ROOT) -> str:
    existing = list_versions(project_id, doc, root)
    if not existing:
        return f"{doc}-v1.0"
    major, minor = max(_parse_version(m.version_id) for m in existing)
    if kind in MINOR_KINDS:
        return f"{doc}-v{major}.{minor + 1}"
    return f"{doc}-v{major + 1}.0"


def _fields_payload(project: Stage2Project) -> dict[str, Any]:
    return {key: record.to_dict() for key, record in project.fields.items()}


def _value_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def diff_fields(
    old: Mapping[str, FieldRecord],
    new: Mapping[str, FieldRecord],
) -> list[FieldChange]:
    """값 기준 비교. 갱신시각·근거자료 메모만 바뀐 경우는 변경으로 보지 않는다."""
    changes: list[FieldChange] = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        if before is None:
            changes.append(FieldChange(key, after.label, "ADDED", None, after.value))
        elif after is None:
            changes.append(FieldChange(key, before.label, "REMOVED", before.value, None))
        elif _value_key(before.value) != _value_key(after.value):
            changes.append(FieldChange(key, after.label or before.label, "CHANGED", before.value, after.value))
    return changes


def freeze_version(
    project: Stage2Project,
    doc: str,
    kind: str,
    *,
    label: str = "",
    note: str = "",
    root: Path = DEFAULT_ROOT,
) -> VersionMeta:
    """현재 작업본을 새 불변 버전으로 저장한다."""
    if doc not in DOC_TYPES:
        raise ValueError(f"지원하지 않는 문서 종류입니다: {doc}")
    existing = list_versions(project.project_id, doc, root)
    version_id = next_version_id(project.project_id, doc, kind, root)
    parent = max(existing, key=lambda m: _parse_version(m.version_id)).version_id if existing else ""
    meta = VersionMeta(
        version_id=version_id, doc=doc, kind=kind, label=label, note=note,
        parent_id=parent, created_at=_utc_now(),
    )
    _write_json_atomic(
        _snapshot_path(project.project_id, version_id, root),
        {
            "schema_version": SNAPSHOT_SCHEMA,
            "meta": asdict(meta),
            "company_name": project.company_name,
            "site_name": project.site_name,
            "fields": _fields_payload(project),
        },
    )
    return meta


def load_version_fields(project_id: str, version_id: str, root: Path = DEFAULT_ROOT) -> dict[str, FieldRecord]:
    path = _snapshot_path(project_id, version_id, root)
    if not path.exists():
        raise FileNotFoundError(f"버전을 찾을 수 없습니다: {version_id}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): FieldRecord.from_dict(value) for key, value in dict(raw.get("fields") or {}).items()}


def diff_versions(
    project: Stage2Project,
    base_version_id: str,
    target_version_id: str | None = None,
    root: Path = DEFAULT_ROOT,
) -> list[FieldChange]:
    """base 버전 → target 버전(생략하면 현재 작업본) 변경점."""
    old = load_version_fields(project.project_id, base_version_id, root)
    new = project.fields if target_version_id is None else load_version_fields(
        project.project_id, target_version_id, root)
    return diff_fields(old, new)


def has_unfrozen_changes(project: Stage2Project, doc: str, root: Path = DEFAULT_ROOT) -> bool:
    """작업본이 해당 문서의 가장 최근 버전과 다르면 True(버전이 없으면 필드가 있을 때 True)."""
    existing = list_versions(project.project_id, doc, root)
    if not existing:
        return bool(project.fields)
    latest = max(existing, key=lambda m: _parse_version(m.version_id))
    return bool(diff_versions(project, latest.version_id, None, root))


def start_from_version(
    project: Stage2Project,
    version_id: str,
    *,
    doc: str,
    force: bool = False,
    root: Path = DEFAULT_ROOT,
) -> Stage2Project:
    """지정 버전의 필드로 작업본을 되돌려 새 버전 작성을 시작한다.

    저장하지 않은 변경이 있으면 작업 손실을 막기 위해 거부한다(force로 무시 가능).
    호출부가 결과를 ``save_project``로 저장해야 한다.
    """
    if not force and has_unfrozen_changes(project, doc, root):
        raise UnfrozenChangesError(
            "작업본에 아직 버전으로 저장하지 않은 변경이 있습니다. 먼저 버전으로 저장하거나 덮어쓰기를 확인하세요."
        )
    project.fields = copy.deepcopy(load_version_fields(project.project_id, version_id, root))
    project.touch()
    return project
