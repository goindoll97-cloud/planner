"""실제 API 키 없이 주변 지도·부지 경계·시설 묶음의 동작을 시험합니다."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from pyproj import Transformer
from shapely.geometry import Point, box, mapping
from shapely.ops import transform

from engine.stage2.cap_site_lookup import Candidate
from engine.stage2.project import Stage2Project
from engine.stage2 import cap_surroundings as survey
from ui.surroundings_map_panel import render


def make_demo_project():
    center = (129.35893422223296, 35.47790404772272)
    x, y = Transformer.from_crs(4326, 5179, always_xy=True).transform(*center)
    inverse = Transformer.from_crs(5179, 4326, always_xy=True).transform
    def geometry(a,b,c=None,d=None):
        geom = Point(x+a,y+b) if c is None else box(x+a,y+b,x+c,y+d)
        return mapping(transform(inverse,geom))
    rows = []
    for identifier,name,geom in [
        ("demo:inside","가상 회사 내부 창고",geometry(-45,-35,-10,20)),
        ("demo:outside-a","가상 외부 물류센터",geometry(180,0,220,40)),
        ("demo:outside-b","가상 외부 물류센터",geometry(245,0,280,40)),
        ("demo:crossing","가상 경계 검토 건물",geometry(80,-35,125,20)),
        ("demo:unknown","명칭 미제공 · 가상 건물",geometry(-220,0,-185,35)),
        ("demo:point","가상 시설 대표점",geometry(20,35)),
    ]:
        rows.append(Candidate(name,"","","가상 시험 위치",None,"가상 기능 시험자료",identifier,geom,
                              {"가상 자료":True,"식별번호":identifier}))
    project = Stage2Project("surroundings-demo","가상 지도 시험 회사",cap_required=True,cap_selected=True,
                            scope_confirmed=True,cap_group="2군")
    project.set_field("business.address","시험 위치","울산 남구 용연로 184","USER_CONFIRMED")
    survey.save_survey(project,rows,center=center,notices=["모든 시설·건물·부지 경계는 기능 시험을 위한 가상 자료입니다."])
    survey.save_boundary(project,geometry(-100,-100,100,100),"가상 예제 경계",confirmed=True)
    return project


if __name__ == "__main__":
    st.set_page_config(page_title="주변 지도 조사 예제",layout="wide")
    st.title("주변 지도 조사 · 가상 예제")
    st.warning("지도 위 건물과 사업장 경계는 모두 가상입니다. 실제 주변 현황이나 사고 영향을 나타내지 않습니다. 변경은 현재 예제 세션에서만 유지됩니다.")
    if "surroundings_demo_project" not in st.session_state:
        st.session_state["surroundings_demo_project"] = make_demo_project()
    if st.button("가상 예제 처음으로"):
        st.session_state.clear()
        st.rerun()
    project = st.session_state["surroundings_demo_project"]
    render(project,persist=lambda project:None,allow_query=False)
