from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .project import EvidenceRef, Stage2Project


DEFAULT_ROOT = Path("data/runtime/stage2")


def _safe_component(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "").strip())
    text = text.strip("._")
    if not text:
        raise ValueError("빈 파일/프로젝트 식별자는 사용할 수 없습니다.")
    return text[:180]


def project_dir(project_id: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / "projects" / _safe_component(project_id)


def project_json_path(project_id: str, root: Path = DEFAULT_ROOT) -> Path:
    return project_dir(project_id, root) / "project.json"


def save_project(project: Stage2Project, root: Path = DEFAULT_ROOT) -> Path:
    target = project_json_path(project.project_id, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    project.touch()
    payload = json.dumps(project.to_dict(), ensure_ascii=False, indent=2, default=str)

    fd, tmp_name = tempfile.mkstemp(prefix="project_", suffix=".json", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return target


def load_project(project_id: str, root: Path = DEFAULT_ROOT) -> Stage2Project:
    path = project_json_path(project_id, root)
    if not path.exists():
        raise FileNotFoundError(f"Stage 2 프로젝트를 찾을 수 없습니다: {project_id}")
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return Stage2Project.from_dict(raw)


def list_projects(root: Path = DEFAULT_ROOT) -> list[dict[str, Any]]:
    base = root / "projects"
    if not base.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/project.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            rows.append({
                "project_id": str(raw.get("project_id") or path.parent.name),
                "company_name": str(raw.get("company_name") or ""),
                "site_name": str(raw.get("site_name") or ""),
                "psm_required": raw.get("psm_required"),
                "cap_required": raw.get("cap_required"),
                "cap_group": str(raw.get("cap_group") or ""),
                "created_at": str(raw.get("created_at") or ""),
                "updated_at": str(raw.get("updated_at") or ""),
            })
        except Exception:
            continue
    rows.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return rows


def delete_project(project_id: str, root: Path = DEFAULT_ROOT) -> bool:
    """Delete one Stage 2 project and every attachment stored under it.

    The project id is sanitized by ``project_dir`` before filesystem access, so
    deletion cannot escape the Stage 2 project root. Missing projects are a
    no-op and return ``False``.
    """
    target = project_dir(project_id, root)
    if not target.exists():
        return False
    if not target.is_dir():
        raise ValueError(f"프로젝트 저장경로가 폴더가 아닙니다: {project_id}")
    shutil.rmtree(target)
    return True


def save_attachment(
    project_id: str,
    file_name: str,
    file_bytes: bytes,
    root: Path = DEFAULT_ROOT,
    source_type: str = "COMPANY_EVIDENCE",
    note: str = "",
) -> EvidenceRef:
    digest = sha256(file_bytes).hexdigest()
    original = Path(file_name).name
    stem = _safe_component(Path(original).stem)
    suffix = re.sub(r"[^0-9A-Za-z.]", "", Path(original).suffix)[:16]
    stored_name = f"{stem}__{digest[:12]}{suffix}"
    folder = project_dir(project_id, root) / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / stored_name
    if not target.exists():
        target.write_bytes(file_bytes)
    return EvidenceRef(
        source_type=source_type,
        source_name=original,
        sha256=digest,
        location=str(target),
        note=note,
    )


def project_json_bytes(project: Stage2Project) -> bytes:
    return json.dumps(project.to_dict(), ensure_ascii=False, indent=2, default=str).encode("utf-8")
