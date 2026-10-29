from __future__ import annotations

import streamlit as st

from engine.stage2.cap_final_form_runtime import install_cap_final_form_runtime


# Stage 2 final output is DOCX-only. Keep only the CAP DOCX formatting runtime
# for checkbox/choice rendering; HWPX template loading/conversion is not
# installed during ordinary app startup.
install_cap_final_form_runtime()

# 사람은 서식을 쓰지 않고 회사 파일을 올립니다(사업장 업무). 프로그램이 채운 초안은 자료 접수 ④ ‘작성·내려받기’에서 받고,
# 행정서식과 이행점검은 ‘제출·이행 관리’에서 다룹니다. 내용은 ui/cap_common.py의 GROUPS.
sections: dict[str, list] = {
    "사업장 업무": [st.Page("ui/evidence_workspace_page.py",title="자료 접수·확인할 일",icon="📂",default=True),
                st.Page("ui/attachment_guide_page.py", title="도면·SDS 첨부 안내", icon="🗺️"),
                # 사고시나리오는 파일로 프로그램이 계산하고, 사람은 지도에 사업장 경계만 그립니다.
                st.Page("ui/scenario_results_page.py", title="사고시나리오 결과", icon="🧭"),
                st.Page("ui/submission_management_page.py", title="제출·이행 관리", icon="📮")],
}

# 두 문서 모두 작성 화면의 "새 사업장으로 시작하기"에서 법정 대상 판정까지 끝낸다. 공정안전보고서는 화학사고예방관리계획서에서
# 이미 입력한 사실을 재사용하는 새 화면에서 작성한다. 예전 3~5단계(엑셀 왕복 방식)는 메뉴에서 뺐다.
sections["공정안전보고서"] = [st.Page("ui/psm_workspace_page.py", title="공정안전보고서 작성", icon="🏭")]

# 사업장 판정: 물질 목록(엑셀·CSV 가능)을 넣고 질문에 답하면 판정하고 작성으로 이어진다(예전 판정진단·작성범위 선택을 합친 화면).
sections["사업장 판정"] = [st.Page("ui/judgement_page.py", title="사업장 판정하기", icon="✅")]

sections["참고"] = [
    st.Page("ui/regdb_page.py", title="규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="법령·근거 라이브러리", icon="📚"),
]

st.navigation(sections).run()
