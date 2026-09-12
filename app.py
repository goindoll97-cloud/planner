from __future__ import annotations

import streamlit as st


pages = [
    st.Page("ui/diagnosis_entry.py", title="1. 판정진단", icon="✅", default=True),
    st.Page("ui/stage2_project_page.py", title="2. 작성 프로젝트", icon="📝"),
    st.Page("ui/regdb_page.py", title="3. 규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="4. 법령 근거", icon="📚"),
]

st.navigation(pages).run()
