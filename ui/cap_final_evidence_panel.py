from __future__ import annotations

"""화학사고예방관리계획서 최종 제출 확인: 타 제도 심사결과 활용·공동제출 여부와 증빙 파일 연결."""

import streamlit as st

from engine.stage2 import cap_final_evidence as evidence
from engine.stage2.storage import save_project


def _choice(project, key: str, options, label: str, help_text: str) -> str:
    current = evidence.answer(project, key)
    choices = ["선택하세요", *options]
    picked = st.selectbox(label, choices, index=choices.index(current) if current in choices else 0, help=help_text,
                          key=f"cap_final_{key}")
    return "" if picked == "선택하세요" else picked


def render(project) -> None:
    st.caption("제출 전에 확인해야 하는 두 가지입니다. 모두 '예/아니오'로 답하면 되고, 해당하는 경우에만 증빙 파일을 연결합니다.")
    other = _choice(project, evidence.OTHER_KEY, evidence.OTHER_OPTIONS, "타 제도 심사결과를 활용하나요?",
                    "공정안전보고서나 안전성향상계획 등 다른 제도의 심사결과를 이 계획서에 활용하면 '해당'입니다.")
    joint = _choice(project, evidence.JOINT_KEY, evidence.JOINT_OPTIONS, "공동으로 제출하나요?",
                    "인접한 사업장과 공동비상대응계획을 함께 제출하면 '공동제출', 혼자 제출하면 '단독제출'입니다.")
    if st.button("확인 사항 저장", key="cap_final_save"):
        evidence.save_answers(project, other, joint)
        save_project(project)
        st.rerun()
    for key, label in ((evidence.OTHER_KEY, "타 제도 심사결과 증빙파일"), (evidence.JOINT_KEY, "공동비상대응계획 증빙파일")):
        if not evidence.needs_evidence(project, key):
            continue
        names = evidence.evidence_names(project, key)
        if names:
            st.success(f"{label} 연결됨: " + ", ".join(names))
        upload = st.file_uploader(label, key=f"cap_final_upload_{key}",
                                  help="실제 회사가 보유한 증빙 파일을 연결합니다.")
        if upload is not None and st.button(f"{label} 연결", key=f"cap_final_link_{key}"):
            try:
                linked = evidence.link_evidence(project, key, upload.name, upload.getvalue())
            except ValueError as exc:
                st.error(str(exc))
            else:
                if linked:
                    save_project(project)
                    st.rerun()
                st.info("같은 파일이 이미 연결되어 있습니다.")
