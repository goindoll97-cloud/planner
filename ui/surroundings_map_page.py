"""지도 그리기. 주소로 주변자료를 조사하고 사업장 경계를 지도에 그립니다(별지 제8호 연결)."""
import streamlit as st

from ui import cap_common, surroundings_map_panel

st.set_page_config(page_title="지도 그리기", page_icon="🗺️", layout="wide")
st.title("🗺️ 지도 그리기")
st.caption("사업장 경계를 지도에 그리면 주변 보호대상의 내부·외부가 구분되어 별지 제8호와 사고시나리오 영향 평가에 쓰입니다.")
surroundings_map_panel.render(cap_common.open_project())
