"""작성본 최신화: 법령 개정 이후 기존 작성본에서 다시 확인할 부분을 찾고 새 작업본에 표시한다.

흐름
1. 버전 스냅샷에 기록된 법령판(``legal_baseline``)과 현재 승인된 법령판을 비교해 개정된 법령을 찾는다.
   법령판 기록이 없는 옛 버전은 '버전 저장 이후 시행된 개정'으로 판단한다.
2. ``data/stage2/legal_impact_map.json``으로 개정 법령이 걸리는 별지·칸을 찾는다.
3. 숫자·판정(별지 제1호 규정수량 비교)은 규칙 엔진이 현재 판정표로 다시 계산해 이전 결과와 비교한다.
4. 반영하면 기준 버전을 복제한 새 작업본에서 영향받는 확인 완료 칸을 '법령 개정 재확인'(HOLD)으로
   돌린다. 값은 지우지 않으며, 사람이 다시 확인해야 완료로 돌아간다.

원칙: 규칙 엔진은 숫자·판정만 다시 계산하고, 회사 입력값이나 서술 문장을 스스로 고치지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from . import legal_baseline_stamp as stamp
from . import versioning as ver
from .project import CONFIRMED_STATUSES, Stage2Project
from .storage import DEFAULT_ROOT

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMPACT_MAP_FILE = PROJECT_ROOT / "data" / "stage2" / "legal_impact_map.json"
REVIEW_NOTE_PREFIX = "[법령 개정 재확인]"
REWRITE_NOTE_PREFIX = "[법령 개정 재작성]"
REWRITE, CHECK = "REWRITE", "CHECK"
ACTION_LABEL = {REWRITE: "다시 작성 필요", CHECK: "내용 확인"}
IDENTITY_LABELS = {
    "serial": "일련번호",
    "effective_date": "시행일",
    "issue_date": "공포·발령일",
    "issue_number": "공포·발령번호",
}


@dataclass(frozen=True)
class LawChange:
    key: str
    title: str
    doc: str
    scope: str
    forms: tuple[str, ...]
    action: str
    details: tuple[str, ...]
    effective_date: str = ""
    inferred: bool = False  # 법령판 기록이 없어 시행일로 추정한 경우
    form_changed: bool = False  # 별지 서식을 담은 법령의 첨부원본(서식)이 바뀜 → 다시 작성
    changed_attachments: tuple[str, ...] = ()


@dataclass(frozen=True)
class AffectedField:
    key: str
    label: str
    status: str
    laws: tuple[str, ...]
    action: str = CHECK  # REWRITE(서식이 바뀌어 다시 작성) / CHECK(작성방법·조문 변경으로 내용 확인)

    @property
    def action_label(self) -> str:
        return ACTION_LABEL[self.action]


@dataclass(frozen=True)
class RecomputedRow:
    substance: str
    cas: str
    change: str  # CHANGED / ADDED / REMOVED
    before: Mapping[str, str]
    after: Mapping[str, str]


@dataclass
class RefreshPlan:
    version_id: str
    doc: str
    stamped: bool
    baseline_ready: bool
    law_changes: list[LawChange] = field(default_factory=list)
    affected_fields: list[AffectedField] = field(default_factory=list)
    recomputed: list[RecomputedRow] = field(default_factory=list)
    recompute_note: str = ""
    group_review: bool = False
    notices: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.law_changes)


def load_impact_map(path: Path = IMPACT_MAP_FILE) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = payload.get("sources", {}) if isinstance(payload, dict) else {}
    return {str(k): dict(v) for k, v in sources.items() if isinstance(v, Mapping)}


def _date_digits(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _fmt_date(value: str) -> str:
    d = _date_digits(value)
    return f"{d[:4]}.{d[4:6]}.{d[6:]}" if d else str(value or "-")


def compare_law_baselines(
    old: Mapping[str, Any] | None,
    new: Mapping[str, Any],
    impact_map: Mapping[str, Mapping[str, Any]],
    *,
    doc: str,
    version_created_at: str = "",
) -> tuple[list[LawChange], bool]:
    """(개정 목록, 법령판 기록 여부). 해당 문서(CAP/PSM)에 걸리는 법령만 본다."""
    old_laws = dict((old or {}).get("laws") or {})
    new_laws = dict(new.get("laws") or {})
    stamped = bool(old_laws)
    cutoff = _date_digits(version_created_at)
    changes: list[LawChange] = []
    for key in sorted(new_laws):
        meta = impact_map.get(key)
        if not meta or meta.get("doc") != doc:
            continue
        now = new_laws[key]
        details: list[str] = []
        inferred = False
        changed_attachments: tuple[str, ...] = ()
        attachment_changed = False
        if stamped:
            before = old_laws.get(key)
            if before is None:
                details.append("작성 당시 감시 기준선에 없던 법령입니다.")
            else:
                for f, label in IDENTITY_LABELS.items():
                    a, b = str(before.get(f, "") or ""), str(now.get(f, "") or "")
                    if a != b:
                        shown = (_fmt_date(a), _fmt_date(b)) if "date" in f else (a or "-", b or "-")
                        details.append(f"{label}: {shown[0]} → {shown[1]}")
                if before.get("attachment_fingerprint", "") != now.get("attachment_fingerprint", ""):
                    attachment_changed = True
                    changed_attachments = _changed_attachment_titles(before, now)
                    if changed_attachments:
                        details.append("바뀐 별표·별지: " + ", ".join(changed_attachments))
                    else:
                        details.append("별표·별지 첨부원본 내용 변경")
        else:
            eff = _date_digits(now.get("effective_date"))
            if eff and cutoff and eff > cutoff:
                inferred = True
                details.append(
                    f"이 버전 저장({_fmt_date(cutoff)}) 이후 시행: {_fmt_date(eff)} "
                    "(작성 당시 법령판 기록이 없어 시행일로 판단)"
                )
        if details:
            changes.append(LawChange(
                key=key,
                title=str(now.get("title") or meta.get("scope") or key),
                doc=doc,
                scope=str(meta.get("scope", "")),
                forms=tuple(meta.get("forms") or ()),
                action=str(meta.get("action", "")),
                details=tuple(details),
                effective_date=_fmt_date(now.get("effective_date", "")),
                inferred=inferred,
                form_changed=bool(meta.get("carries_forms")) and attachment_changed,
                changed_attachments=changed_attachments,
            ))
    return changes, stamped


def _changed_attachment_titles(before: Mapping[str, Any], now: Mapping[str, Any]) -> tuple[str, ...]:
    """첨부별 해시를 비교해 추가·삭제·변경된 별표·별지 제목. 옛 기록(첨부별 해시 없음)은 빈 값."""
    if "attachment_hashes" not in before:
        return ()  # 첨부별 해시를 남기기 전 기록
    old_h = dict(before.get("attachment_hashes") or {})
    new_h = dict(now.get("attachment_hashes") or {})
    titles = {**dict(before.get("attachment_titles") or {}), **dict(now.get("attachment_titles") or {})}
    rows: list[str] = []
    for key in sorted(set(old_h) | set(new_h)):
        if old_h.get(key) == new_h.get(key):
            continue
        name = str(titles.get(key) or key)
        if key not in old_h:
            rows.append(f"{name}(추가)")
        elif key not in new_h:
            rows.append(f"{name}(삭제)")
        else:
            rows.append(name)
    return tuple(dict.fromkeys(rows))


def affected_fields(
    fields: Mapping[str, Any],
    law_changes: list[LawChange],
    impact_map: Mapping[str, Mapping[str, Any]],
) -> list[AffectedField]:
    """개정 법령의 field_prefixes에 해당하는 확인 완료 칸."""
    hits: dict[str, list[str]] = {}
    rewrite: set[str] = set()
    for change in law_changes:
        prefixes = tuple(impact_map.get(change.key, {}).get("field_prefixes") or ())
        if not prefixes:
            continue
        for key in fields:
            if key.startswith(prefixes):
                hits.setdefault(key, []).append(change.title)
                if change.form_changed:
                    rewrite.add(key)
    rows: list[AffectedField] = []
    for key in sorted(hits):
        record = fields[key]
        if record.status not in CONFIRMED_STATUSES:
            continue  # 이미 미확인·초안인 칸은 원래대로 둔다
        rows.append(AffectedField(key, record.label or key, record.status, tuple(dict.fromkeys(hits[key])),
                                  REWRITE if key in rewrite else CHECK))
    # 다시 작성할 칸을 먼저 보여 준다.
    rows.sort(key=lambda r: (r.action != REWRITE, r.key))
    return rows


def _row_id(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("CAS No.", "")), str(row.get("물질명", "")), str(row.get("법령DB", "")))


def compare_form1(before: list[Mapping[str, Any]] | None, after: list[Mapping[str, Any]] | None) -> list[RecomputedRow]:
    before_map = {_row_id(r): r for r in before or []}
    after_map = {_row_id(r): r for r in after or []}
    rows: list[RecomputedRow] = []
    for rid in sorted(set(before_map) | set(after_map)):
        a, b = before_map.get(rid), after_map.get(rid)
        pick = lambda r: {c: str((r or {}).get(c, "")) for c in stamp.FORM1_COMPARE_COLUMNS}
        if a is None:
            rows.append(RecomputedRow(rid[1], rid[0], "ADDED", {}, pick(b)))
        elif b is None:
            rows.append(RecomputedRow(rid[1], rid[0], "REMOVED", pick(a), {}))
        elif pick(a) != pick(b):
            rows.append(RecomputedRow(rid[1], rid[0], "CHANGED", pick(a), pick(b)))
    return rows


def _project_from_snapshot(project: Stage2Project, fields: Mapping[str, Any]) -> Stage2Project:
    clone = Stage2Project.from_dict(project.to_dict())
    clone.fields = dict(fields)
    return clone


def build_refresh_plan(
    project: Stage2Project,
    version_id: str,
    *,
    root: Path = DEFAULT_ROOT,
    approved_sources: Mapping[str, Any] | None = None,
    impact_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> RefreshPlan:
    """저장된 버전 하나를 현재 법령판 기준으로 점검한 결과. 아무것도 저장하지 않는다."""
    snapshot = ver.load_version_snapshot(project.project_id, version_id, root)
    meta = dict(snapshot.get("meta") or {})
    doc = str(meta.get("doc") or "CAP")
    impact = load_impact_map() if impact_map is None else impact_map
    current = stamp.current_legal_baseline(approved_sources)
    plan = RefreshPlan(version_id=version_id, doc=doc, stamped=False, baseline_ready=bool(current["laws"]))
    if not plan.baseline_ready:
        plan.notices.append("승인된 법령 기준선이 없습니다. '규정 DB 관리'에서 최신본 업데이트를 먼저 실행하세요.")
        return plan

    changes, stamped = compare_law_baselines(
        snapshot.get("legal_baseline"), current, impact, doc=doc,
        version_created_at=str(meta.get("created_at") or ""),
    )
    plan.law_changes, plan.stamped = changes, stamped
    if not stamped:
        plan.notices.append(
            "이 버전은 법령판 기록 기능이 생기기 전에 저장되어, 버전 저장 이후 시행된 개정만 찾았습니다. "
            "공포만 되고 아직 시행 전인 개정은 잡히지 않을 수 있습니다."
        )
    if not changes:
        return plan

    fields = ver.load_version_fields(project.project_id, version_id, root)
    plan.affected_fields = affected_fields(fields, changes, impact)

    needs_form1 = doc == "CAP" and any("cap_form1" in (impact.get(c.key, {}).get("recompute") or ()) for c in changes)
    if needs_form1:
        before = (snapshot.get("derived") or {}).get("cap_form1")
        try:
            after = stamp.derived_results(_project_from_snapshot(project, fields), "CAP").get("cap_form1")
        except Exception:
            after = None
        if after is None:
            plan.recompute_note = "현재 판정표로 별지 제1호를 다시 계산하지 못했습니다(규정 DB 상태를 확인하세요)."
        elif before is None:
            plan.recompute_note = (
                "작성 당시 판정 결과 기록이 없어 비교할 수 없습니다. 별지 제1호 화면에서 현재 결과를 확인하세요."
            )
            plan.group_review = True
        else:
            plan.recomputed = compare_form1(before, after)
            plan.recompute_note = (
                f"현재 판정표로 다시 계산한 결과, 별지 제1호 규정수량 판정이 {len(plan.recomputed)}건 달라졌습니다."
                if plan.recomputed else "현재 판정표로 다시 계산해도 별지 제1호 규정수량 판정은 같습니다."
            )
            plan.group_review = any(
                r.before.get("규정수량 비교") != r.after.get("규정수량 비교") for r in plan.recomputed
            )
    if any(not impact.get(c.key, {}).get("field_prefixes") and not impact.get(c.key, {}).get("recompute")
           for c in changes):
        plan.notices.append("일부 개정은 특정 칸에 연결되지 않아 안내만 표시합니다. 개정 조문을 직접 확인하세요.")
    return plan


def apply_refresh(
    project: Stage2Project,
    plan: RefreshPlan,
    *,
    root: Path = DEFAULT_ROOT,
    now: str | None = None,
) -> int:
    """기준 버전을 현재 작업본으로 복제하고 영향받는 칸을 '법령 개정 재확인'으로 돌린다.

    호출부가 결과를 ``storage.save_project``로 저장해야 한다. 돌린 칸 수를 돌려준다.
    """
    ver.start_from_version(project, plan.version_id, doc=plan.doc, force=True, root=root)
    stamp_date = now or datetime.now().strftime("%Y-%m-%d")
    changed = 0
    for item in plan.affected_fields:
        record = project.fields.get(item.key)
        if record is None or record.status not in CONFIRMED_STATUSES:
            continue
        previous = record.status
        laws = ", ".join(item.laws)
        if item.action == REWRITE:
            reason = (f"{REWRITE_NOTE_PREFIX} {laws} 서식 개정 — 바뀐 서식에 맞게 다시 작성 필요 "
                      f"({stamp_date}, 이전 상태 {previous})")
        else:
            reason = f"{REVIEW_NOTE_PREFIX} {laws} 개정 후 다시 확인 필요 ({stamp_date}, 이전 상태 {previous})"
        record.note = f"{reason}\n{record.note}".strip() if record.note else reason
        record.status = "HOLD"
        record.updated_at = ver._utc_now()
        changed += 1
    project.notes.append(
        f"{stamp_date} {plan.version_id} 기준 작성본 최신화: 개정 법령 {len(plan.law_changes)}건, "
        f"재확인 칸 {changed}건" + (", 작성수준 재판정 필요" if plan.group_review else "")
    )
    project.touch()
    return changed


def change_log_candidate(plan: RefreshPlan, today: str | None = None) -> dict[str, str]:
    """별지 제2호 변경내역 관리대장에 넣을 수 있는 '정보 현행화' 행 후보(자동 저장하지 않음)."""
    titles = ", ".join(c.title for c in plan.law_changes)
    return {
        "일자": today or datetime.now().strftime("%Y-%m-%d"),
        "변경항목": " / ".join(dict.fromkeys(f for c in plan.law_changes for f in c.forms)),
        "변경의 종류": "㈓ 정보 현행화",
        "변경 내용(변경전 → 변경후)": f"{plan.version_id} 작성 기준 법령 → 개정 법령({titles}) 반영",
    }


def pending_refresh_fields(project: Stage2Project) -> list[AffectedField]:
    """작업본에 남아 있는 '법령 개정' 표시 칸(아직 담당자가 다시 확정하지 않은 칸)."""
    rows: list[AffectedField] = []
    for key, record in sorted(project.fields.items()):
        note = str(record.note or "")
        if record.status in CONFIRMED_STATUSES:
            continue
        if note.startswith(REWRITE_NOTE_PREFIX):
            action = REWRITE
        elif note.startswith(REVIEW_NOTE_PREFIX):
            action = CHECK
        else:
            continue
        first = note.splitlines()[0]
        rows.append(AffectedField(key, record.label or key, record.status, (first,), action))
    rows.sort(key=lambda r: (r.action != REWRITE, r.key))
    return rows
