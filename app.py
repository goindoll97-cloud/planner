from __future__ import annotations

import streamlit as st

from engine.stage2.cap_final_form_runtime import install_cap_final_form_runtime


# Stage 2 final output is DOCX-only. Keep only the CAP DOCX formatting runtime
# for checkbox/choice rendering; HWPX template loading/conversion is not
# installed during ordinary app startup.
install_cap_final_form_runtime()

# 화학사고예방관리계획서는 별지 순서대로 한 화면에서 작성한다. 엑셀 통합 작성자료 가져오기도 그 화면 안에 들어 있어
# 예전의 3~5단계 화면(엑셀 왕복 방식)은 화학사고예방관리계획서에는 더 이상 쓰이지 않는다.
sections: dict[str, list] = {
    "화학사고예방관리계획서": [
        st.Page("ui/cap_workspace_page.py", title="화학사고예방관리계획서 작성", icon="📝", default=True),
    ],
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
