from __future__ import annotations

import streamlit as st


pages = [
    st.Page("ui/diagnosis_entry.py", title="1. 판정진단", icon="✅", default=True),
    st.Page("ui/regdb_page.py", title="2. 규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="3. 법령 근거", icon="📚"),
]

st.navigation(pages).run()
