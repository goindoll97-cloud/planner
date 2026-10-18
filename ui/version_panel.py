from __future__ import annotations

"""사업장 작성자료 버전 관리 패널(CAP·PSM 공용).

기존 입력 화면을 그대로 고쳐 쓰는 방식이다. 제출한 시점의 값을 버전으로 저장해 두면, 이후 바뀐 값이
저장된 버전과 자동 비교된다. 별도의 변경용 설문은 없다.
"""

import json
from typing import Any

import pandas as pd
import streamlit as st

from engine.stage2 import legal_refresh as lr
from engine.stage2 import versioning as ver
from engine.stage2 import storage

KINDS = ("신규", "변경", "재제출")
CAP_KINDS = ("신규제출", "변경제출", "재제출", "5년 재제출", "부적합 후 재제출", "이행점검 부적정 재제출")
CHANGE_TYPES = ("설비 변경", "취급물질 변경", "공정 변경", "조직·연락처 변경", "기타")
CHANGE_LABEL = {"ADDED": "추가", "REMOVED": "삭제", "CHANGED": "변경"}
DOC_NAME = {"CAP": "화학사고예방관리계획서", "PSM": "공정안전보고서"}
_MAX_CELL = 120


def _show(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= _MAX_CELL else text[:_MAX_CELL] + "…"


def changes_frame(changes: list[ver.FieldChange]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"항목": c.label or c.key, "구분": CHANGE_LABEL[c.change], "이전": _show(c.old), "이후": _show(c.new),
          "키": c.key} for c in changes],
        columns=["항목", "구분", "이전", "이후", "키"],
    )


def _latest(metas: list[ver.VersionMeta]) -> ver.VersionMeta | None:
    return max(metas, key=lambda m: ver._parse_version(m.version_id)) if metas else None


def render(project, doc: str) -> None:
    name = DOC_NAME[doc]
    pid = project.project_id
    metas = ver.list_versions(pid, doc)
    latest = _latest(metas)
    pending = ver.diff_versions(project, latest.version_id) if latest else []
    if latest is None:
        summary = f"{name} 버전 없음 · 제출하면 버전으로 저장해 두세요"
    elif pending:
        summary = f"{name} · 기준 {latest.version_id} · 저장하지 않은 변경 {len(pending)}건"
    else:
        summary = f"{name} · 기준 {latest.version_id} · 변경 없음"

    with st.expander(f"🕘 버전 관리 — {summary}", expanded=bool(pending)):
        st.caption("제출한 시점의 값을 버전으로 저장해 두면, 이후 아래 입력 화면을 그대로 고쳤을 때 무엇이 바뀌었는지 "
                   "이전 버전과 자동으로 비교됩니다. 첨부파일은 버전에 포함되지 않고 입력값만 저장됩니다.")

        if metas:
            st.dataframe(
                pd.DataFrame([{"버전": m.version_id, "제출유형": m.kind, "변경 유형": m.label, "사유·메모": m.note,
                               "저장 시각": m.created_at} for m in metas]),
                hide_index=True, width="stretch",
            )

        st.markdown("**현재 값을 버전으로 저장**")
        if doc == "CAP":
            kind_options = CAP_KINDS if metas else ("신규제출",)
        else:
            kind_options = KINDS if metas else ("신규",)
        c1, c2 = st.columns(2)
        kind = c1.selectbox("제출유형", kind_options, key=f"ver_kind_{doc}_{pid}",
                            help="변경제출은 v1.0 → v1.1처럼 부 버전이, 신규·재제출 계열은 v2.0처럼 새 주 버전이 열립니다.")
        is_change = kind in {"변경", "변경제출"}
        label = c2.selectbox("변경 유형", ("",) + CHANGE_TYPES, key=f"ver_type_{doc}_{pid}",
                             disabled=not is_change)
        note = st.text_input("변경 사유·메모", key=f"ver_note_{doc}_{pid}",
                             help="왜 바뀌었는지 적어 두면 변경내역을 정리할 때 그대로 쓸 수 있습니다.")
        if st.button("버전으로 저장", key=f"ver_save_{doc}_{pid}", type="primary"):
            if is_change and not (label or note.strip()):
                st.error("변경 버전은 변경 유형이나 사유를 하나 이상 적어 주세요.")
            elif latest is not None and not pending:
                st.error("이전 버전과 달라진 값이 없어 새 버전을 만들지 않았습니다.")
            else:
                if doc == "CAP":
                    project.set_field(
                        "cap.business.submission_type",
                        "화학사고예방관리계획서 제출구분",
                        kind,
                        "USER_CONFIRMED",
                        note="CAP 버전 저장 시 선택한 제출유형과 동기화",
                    )
                    storage.save_project(project)
                meta = ver.freeze_version(project, doc, kind, label=label if is_change else "", note=note.strip())
                st.success(f"{meta.version_id}로 저장했습니다.")
                st.rerun()

        if latest is not None:
            st.markdown("**변경점 보기**")
            choices = [m.version_id for m in metas]
            base = st.selectbox("비교 기준 버전", choices, index=choices.index(latest.version_id),
                                key=f"ver_base_{doc}_{pid}")
            changes = ver.diff_versions(project, base)
            if not changes:
                st.info(f"{base}과(와) 현재 값이 같습니다.")
            else:
                st.write(f"{base} 대비 현재 값의 변경 {len(changes)}건")
                st.dataframe(changes_frame(changes).drop(columns=["키"]), hide_index=True, width="stretch")

            st.markdown("**이전 제출본에서 새 작업 시작하기**")
            target = st.selectbox("기준으로 삼을 버전", choices, index=choices.index(latest.version_id),
                                  key=f"ver_restore_{doc}_{pid}")
            next_kind = None
            if doc == "CAP":
                next_kind = st.selectbox(
                    "새 작업의 제출유형",
                    CAP_KINDS,
                    index=1 if "변경제출" in CAP_KINDS else 0,
                    key=f"ver_next_kind_{doc}_{pid}",
                    help="기준 제출본을 복제한 직후 현재 작업본의 제출구분으로 저장됩니다.",
                )
            confirm = True
            if pending:
                st.warning(f"저장하지 않은 변경 {len(pending)}건이 있습니다. 되돌리면 이 변경은 사라집니다.")
                confirm = st.checkbox("사라져도 됩니다", key=f"ver_force_{doc}_{pid}")
            if st.button("이 버전에서 새 작업 시작", key=f"ver_do_restore_{doc}_{pid}", disabled=not confirm):
                ver.start_from_version(project, target, doc=doc, force=True)
                if doc == "CAP" and next_kind:
                    project.set_field(
                        "cap.business.submission_type",
                        "화학사고예방관리계획서 제출구분",
                        next_kind,
                        "USER_CONFIRMED",
                        note=f"{target}에서 새 작업 시작",
                    )
                storage.save_project(project)
                st.success(
                    f"{target}의 값을 현재 작업본으로 복제했습니다."
                    + (f" 제출구분은 '{next_kind}'로 설정했습니다." if next_kind else "")
                    + " 여기서 변경된 부분만 수정하세요."
                )
                st.rerun()

            render_legal_refresh(project, doc, choices, latest.version_id, pending)


RECOMPUTE_LABEL = {"CHANGED": "판정 변경", "ADDED": "새로 해당", "REMOVED": "해당 없어짐"}


def _plan_key(doc: str, pid: str) -> str:
    return f"legal_refresh_plan_{doc}_{pid}"


def render_legal_refresh(project, doc: str, choices: list[str], default_id: str, pending: list) -> None:
    """법령 개정 후 저장된 작성본을 점검하고, 영향받는 칸을 표시한 새 작업본으로 반영한다."""
    pid = project.project_id
    st.markdown("**법령 개정 반영 (작성본 최신화)**")
    st.caption("'규정 DB 관리'에서 최신본 업데이트로 승인된 법령판과, 버전을 저장할 때의 법령판을 비교합니다. "
               "판정·계산은 현재 판정표로 다시 계산하고, 개정 법령이 걸리는 칸은 다시 확인하도록 표시합니다. "
               "회사 입력값과 서술 문장은 자동으로 고치지 않습니다.")
    target = st.selectbox("점검할 버전", choices, index=choices.index(default_id), key=f"lr_target_{doc}_{pid}")
    if st.button("개정 법령 점검", key=f"lr_check_{doc}_{pid}"):
        try:
            st.session_state[_plan_key(doc, pid)] = lr.build_refresh_plan(project, target)
        except Exception as exc:  # 스냅샷 손상 등 — 화면 전체가 멈추지 않게
            st.session_state.pop(_plan_key(doc, pid), None)
            st.error(f"점검하지 못했습니다: {exc}")

    plan = st.session_state.get(_plan_key(doc, pid))
    if plan is None or plan.version_id != target:
        return
    for notice in plan.notices:
        st.info(notice)
    if not plan.baseline_ready:
        return
    if not plan.has_changes:
        st.success(f"{plan.version_id} 작성 이후 이 문서에 걸리는 법령 개정이 없습니다.")
        return

    st.warning(f"{plan.version_id} 작성 이후 개정된 법령 {len(plan.law_changes)}건")
    st.dataframe(
        pd.DataFrame([{"법령": c.title, "현재 시행일": c.effective_date, "바뀐 점": " / ".join(c.details),
                       "영향 서식": ", ".join(c.forms), "확인할 일": c.action} for c in plan.law_changes]),
        hide_index=True, width="stretch",
    )

    if plan.recompute_note:
        st.write(plan.recompute_note)
    if plan.recomputed:
        st.dataframe(
            pd.DataFrame([{"물질": r.substance, "CAS No.": r.cas, "구분": RECOMPUTE_LABEL[r.change],
                           "이전 규정수량(하위/상위)": f"{r.before.get('하위규정수량(ton)', '')} / {r.before.get('상위규정수량(ton)', '')}"
                           if r.before else "",
                           "현재 규정수량(하위/상위)": f"{r.after.get('하위규정수량(ton)', '')} / {r.after.get('상위규정수량(ton)', '')}"
                           if r.after else "",
                           "이전 비교": r.before.get("규정수량 비교", ""), "현재 비교": r.after.get("규정수량 비교", "")}
                          for r in plan.recomputed]),
            hide_index=True, width="stretch",
        )
    if plan.group_review:
        st.error("규정수량 비교 결과가 달라졌습니다. '사업장 판정하기'에서 작성수준(1군·2군)을 다시 판정하세요.")

    if plan.affected_fields:
        st.write(f"다시 확인할 칸 {len(plan.affected_fields)}개 — 반영하면 '법령 개정 재확인'(미확인)으로 바뀌고, "
                 "값은 그대로 남습니다.")
        st.dataframe(
            pd.DataFrame([{"항목": f.label, "현재 상태": f.status, "관련 개정": ", ".join(f.laws), "키": f.key}
                          for f in plan.affected_fields]).drop(columns=["키"]),
            hide_index=True, width="stretch",
        )
    else:
        st.write("특정 칸에 연결된 개정은 없습니다. 위의 '확인할 일'을 참고하세요.")

    if doc == "CAP":
        st.caption("별지 제2호 변경내역 관리대장에 적을 수 있는 행 후보(자동 저장하지 않음)")
        st.dataframe(pd.DataFrame([lr.change_log_candidate(plan)]), hide_index=True, width="stretch")

    confirm = True
    if pending:
        st.warning(f"저장하지 않은 변경 {len(pending)}건이 있습니다. 반영하면 {plan.version_id} 값으로 덮어써집니다.")
        confirm = st.checkbox("사라져도 됩니다", key=f"lr_force_{doc}_{pid}")
    if st.button(f"{plan.version_id}에서 최신화 작업본 만들기", key=f"lr_apply_{doc}_{pid}",
                 type="primary", disabled=not confirm):
        changed = lr.apply_refresh(project, plan)
        storage.save_project(project)
        st.session_state.pop(_plan_key(doc, pid), None)
        st.success(f"{plan.version_id}을(를) 작업본으로 복제하고 {changed}개 칸을 '법령 개정 재확인'으로 표시했습니다. "
                   "각 별지에서 개정 내용을 확인한 뒤 다시 확정하고, 새 버전으로 저장하세요.")
        st.rerun()
