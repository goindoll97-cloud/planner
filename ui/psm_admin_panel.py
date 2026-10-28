"""제출·이행 관리에서 사용하는 공정안전보고서 행정서식."""
import pandas as pd
import streamlit as st
from engine.stage2 import psm_admin_forms as admin_forms
from ui import cap_frames as frames

def render(project) -> None:
    st.caption("본문 별지 제12~21호와 별도로 제출·확인 단계에서 쓰는 행정서식입니다. 별지 제1호는 심사신청 단계, "
               "별지 제9호는 심사 후 확인요청 단계에서 씁니다. 사업장관리번호·신청일·확인요청 담당자 등은 "
               "공정안전보고서 사업개요 파일의 같은 이름 항목에서 읽습니다.")
    for title, values, readiness, build, filename, key in (
            ("별지 제1호 · 공정안전보고서 심사신청서", admin_forms.form1_values(project), admin_forms.form1_readiness(project),
             admin_forms.build_form1_docx, admin_forms.form1_filename, "psm_admin_form1_download"),
            ("별지 제9호 · 공정안전보고서확인요청서", admin_forms.form9_values(project), admin_forms.form9_readiness(project),
             admin_forms.build_form9_docx, admin_forms.form9_filename, "psm_admin_form9_download")):
        st.markdown(f"### {title}")
        frames.show(pd.DataFrame([{"칸": k, "값": v} for k, v in values.items()]), width="stretch", hide_index=True)
        if readiness.ready:
            st.download_button(f"{title.split(' · ')[0]} DOCX 초안 내려받기", data=build(project), file_name=filename(project),
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               key=key, width="stretch")
        else:
            st.info("파일에서 채우지 못한 것: " + " / ".join(readiness.blockers))
        with st.expander("제출 전 확인할 것"):
            for item in readiness.manual_items:
                st.write(f"• {item}")

