from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.legal_archive import evidence_rows, open_archive_folder


st.set_page_config(page_title="법령 근거자료", page_icon="📚", layout="wide")
st.title("법령 근거자료")
st.caption(
    "사전판정 결과에서 'PSM 별표 13', '화사계 별표 1·2·3' 같은 근거가 표시되면 "
    "여기서 같은 이름의 로컬 공식 PDF 보관폴더를 바로 열어 확인할 수 있습니다."
)

rows = evidence_rows()
df = pd.DataFrame(rows)
if df.empty:
    st.info("아직 로컬에 보관된 승인 근거자료가 없습니다. '규정DB 관리'에서 승인본 근거 PDF를 동기화하세요.")
else:
    shown = df.copy()
    if "SHA256" in shown.columns:
        shown["SHA256"] = shown["SHA256"].astype(str).map(lambda v: v[:16] + "…" if len(v) > 16 else v)
    for col in shown.columns:
        shown[col] = shown[col].astype(str)
    st.dataframe(shown, width="stretch", hide_index=True)

    available = df[df["보관상태"].eq("보관됨")]
    if available.empty:
        st.warning("승인 DB는 있어도 근거 PDF가 아직 로컬 보관소에 동기화되지 않았습니다. 규정DB 관리 페이지에서 동기화하세요.")
    else:
        st.markdown("### 근거별 로컬 폴더 바로 열기")
        for _, row in available.iterrows():
            key = str(row["key"])
            label = str(row["근거"])
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{label}**")
            c1.caption(str(row.get("로컬 PDF", "")))
            if c2.button("폴더 열기", key=f"evidence_open_{key}", width="stretch"):
                result = open_archive_folder(key)
                if result.get("status") == "OPENED":
                    st.toast(f"{label} 근거 폴더를 열었습니다.")
                else:
                    st.warning(str(result.get("message", "폴더를 열지 못했습니다.")))

st.divider()
st.info(
    "이 PDF는 판정 계산용 데이터가 아니라 사람이 법적 원문을 즉시 확인하기 위한 승인 근거 사본입니다. "
    "실제 계산은 같은 PDF에서 검토·승인한 구조화 Regulatory DB를 사용합니다."
)
st.caption("법제처 API는 최신성·개정 감시에 사용하고, 승인된 근거 PDF와 구조화 DB는 로컬에서 재현 가능하게 보관합니다.")
