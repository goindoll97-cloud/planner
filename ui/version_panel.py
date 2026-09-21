from __future__ import annotations

"""사업장 작성자료 버전 관리 패널(CAP·PSM 공용).

기존 입력 화면을 그대로 고쳐 쓰는 방식이다. 제출한 시점의 값을 버전으로 저장해 두면, 이후 바뀐 값이
저장된 버전과 자동 비교된다. 별도의 변경용 설문은 없다.
"""

import json
from typing import Any

import pandas as pd
import streamlit as st

from engine.stage2 import versioning as ver
from engine.stage2 import storage

KINDS = ("신규", "변경", "재제출")
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
        kind_options = KINDS if metas else ("신규",)
        c1, c2 = st.columns(2)
        kind = c1.selectbox("제출유형", kind_options, key=f"ver_kind_{doc}_{pid}",
                            help="변경은 v1.0 → v1.1처럼 부 버전이, 신규·재제출은 v2.0처럼 새 주 버전이 열립니다.")
        label = c2.selectbox("변경 유형", ("",) + CHANGE_TYPES, key=f"ver_type_{doc}_{pid}",
                             disabled=kind != "변경")
        note = st.text_input("변경 사유·메모", key=f"ver_note_{doc}_{pid}",
                             help="왜 바뀌었는지 적어 두면 변경내역을 정리할 때 그대로 쓸 수 있습니다.")
        if st.button("버전으로 저장", key=f"ver_save_{doc}_{pid}", type="primary"):
            if kind == "변경" and not (label or note.strip()):
                st.error("변경 버전은 변경 유형이나 사유를 하나 이상 적어 주세요.")
            elif latest is not None and not pending:
                st.error("이전 버전과 달라진 값이 없어 새 버전을 만들지 않았습니다.")
            else:
                meta = ver.freeze_version(project, doc, kind, label=label if kind == "변경" else "", note=note.strip())
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

            st.markdown("**이전 버전 값으로 되돌리기**")
            target = st.selectbox("되돌릴 버전", choices, index=choices.index(latest.version_id),
                                  key=f"ver_restore_{doc}_{pid}")
            confirm = True
            if pending:
                st.warning(f"저장하지 않은 변경 {len(pending)}건이 있습니다. 되돌리면 이 변경은 사라집니다.")
                confirm = st.checkbox("사라져도 됩니다", key=f"ver_force_{doc}_{pid}")
            if st.button("이 버전 값으로 되돌리기", key=f"ver_do_restore_{doc}_{pid}", disabled=not confirm):
                ver.start_from_version(project, target, doc=doc, force=True)
                storage.save_project(project)
                st.success(f"{target} 값으로 되돌렸습니다.")
                st.rerun()
