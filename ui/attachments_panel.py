from __future__ import annotations

"""첨부 자료(도면·MSDS 등 파일이 본체인 자료) 올리기 화면 조각. 화학사고예방관리계획서·공정안전보고서 공용."""

import streamlit as st

from engine.stage2 import psm_attachments as attachments
from engine.stage2.storage import save_project


def render(project, slots, prefix: str) -> None:
    st.caption("표로 적을 수 없고 파일 자체가 자료인 것만 올립니다. 올린 파일은 지문(SHA-256)과 함께 기록되고 보고서의 첨부 칸에 연결됩니다. "
               "올렸다고 내용을 확인한 것은 아니므로, 직접 확인한 뒤 '내용을 확인했습니다'를 눌러 주세요.")
    for index, item in enumerate(attachments.status(project, tuple(slots))):
        slot = item["slot"]
        with st.expander(f"{slot.label} — {item['state']}", expanded=item["state"] == "올리지 않음" and index < 3):
            st.caption(slot.help)
            if item["file_name"]:
                st.write(f"현재 파일: {item['file_name']} {item['reference_no']} {item['revision']}".strip())
            upload = st.file_uploader("파일 선택", key=f"{prefix}_file_{slot.key}")
            left, right = st.columns(2)
            reference = left.text_input("도면번호(있으면)", key=f"{prefix}_ref_{slot.key}")
            revision = right.text_input("개정번호(있으면)", key=f"{prefix}_rev_{slot.key}")
            if upload is not None and st.button("이 파일 올리기", key=f"{prefix}_up_{slot.key}"):
                attachments.attach(project, slot.key, upload.name, upload.getvalue(), reference_no=reference,
                                   revision=revision)
                save_project(project)
                st.rerun()
            if item["state"] == "내용 확인 필요" and st.button("내용을 확인했습니다", key=f"{prefix}_ok_{slot.key}"):
                attachments.confirm(project, slot.key)
                save_project(project)
                st.rerun()
