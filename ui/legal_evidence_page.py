from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from engine.legal_archive import evidence_rows, open_archive_folder
from engine.stage2.intake import extract_form_references
from engine.stage2.requirements import cap_requirement_specs


st.set_page_config(page_title="법령 근거자료", page_icon="📚", layout="wide")
st.title("📚 7. 법령 근거")
st.caption(
    "판정 및 작성 지원에서 인용하는 법령·고시·별표·별지서식의 근거를 확인합니다. "
    "프로그램 입력양식과 법정 서식은 구분하여 표시합니다."
)

rows = evidence_rows()
# Legacy archive metadata may contain internal abbreviations. User-facing text is
# normalized to the full legal document names.
for row in rows:
    row["근거"] = (
        str(row.get("근거", ""))
        .replace("PSM", "공정안전보고서")
        .replace("화사계", "화학사고예방관리계획서")
    )

df = pd.DataFrame(rows)
if df.empty:
    st.info("아직 로컬에 보관된 승인 근거자료가 없습니다. ‘규정 DB 관리’에서 승인본 근거 PDF를 동기화하세요.")
else:
    shown = df.copy()
    if "SHA256" in shown.columns:
        shown["SHA256"] = shown["SHA256"].astype(str).map(lambda v: v[:16] + "…" if len(v) > 16 else v)
    for col in shown.columns:
        shown[col] = shown[col].astype(str)
    st.dataframe(shown, width="stretch", hide_index=True)

    available = df[df["보관상태"].eq("보관됨")]
    if available.empty:
        st.warning("승인 DB는 있어도 근거 PDF가 아직 로컬 보관소에 동기화되지 않았습니다. 규정 DB 관리에서 동기화하세요.")
    else:
        st.markdown("### 승인 근거 PDF")
        for _, row in available.iterrows():
            key = str(row["key"])
            label = str(row["근거"])
            raw_path = str(row.get("로컬 PDF", ""))
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(f"**{label}**")
            c1.caption(raw_path)
            if c2.button("폴더 열기", key=f"evidence_open_{key}", width="stretch"):
                result = open_archive_folder(key)
                if result.get("status") == "OPENED":
                    st.toast(f"{label} 근거 폴더를 열었습니다.")
                else:
                    st.warning(str(result.get("message", "폴더를 열지 못했습니다.")))
            local_path = Path(raw_path) if raw_path else None
            if local_path is not None and local_path.exists():
                c3.download_button(
                    "PDF 받기",
                    data=local_path.read_bytes(),
                    file_name=local_path.name,
                    mime="application/pdf",
                    key=f"evidence_download_{key}",
                    width="stretch",
                )

st.divider()
st.markdown("### 화학사고예방관리계획서 관련 법정 별지서식 참조")
form_map: dict[str, set[str]] = {}
for spec in cap_requirement_specs("1군"):
    for form in extract_form_references(spec.legal_basis):
        form_map.setdefault(form, set()).add(f"{spec.section} · {spec.label}")

if form_map:
    form_rows = []
    for form, items in sorted(form_map.items()):
        form_rows.append({
            "법정 서식": form,
            "관련 작성항목": " / ".join(sorted(items)),
            "구분": "법정 별지서식",
        })
    st.dataframe(pd.DataFrame(form_rows), width="stretch", hide_index=True)
    st.info(
        "위 표는 현재 작성 registry에서 확인되는 법정 별지서식의 참조목록입니다. "
        "법정 서식 원문은 현행 고시의 공식 첨부파일을 기준으로 확인해야 하며, 프로그램 입력양식을 법정 서식으로 대체하지 않습니다."
    )
else:
    st.info("현재 registry에서 별지서식 참조를 추출하지 못했습니다.")

st.divider()
st.info(
    "보관 PDF는 사람이 법적 원문을 확인하기 위한 승인 근거 사본입니다. 실제 판정 계산은 같은 공식 근거에서 검토·승인한 구조화 Regulatory DB를 사용합니다."
)
st.caption("법제처 API는 최신성·개정 감시에 사용하고, 승인된 근거 PDF와 구조화 DB는 로컬에서 재현 가능하게 보관합니다.")
