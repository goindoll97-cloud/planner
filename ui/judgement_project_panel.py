"""선택한 사업장의 정보와 물질 목록을 판정 화면에서 바로 고치는 화면 조각.

'새 사업장으로 시작하기'는 새 사업장을 만드는 입구다. 이미 있는 사업장을 골라 두었다면 사업장 정보와 물질 목록(엑셀·CSV 업로드 포함)은
이 조각에서 그 사업장에 바로 반영한다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_chemical_upload as chem_upload
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_judgement as judgement
from engine.stage2 import storage
from ui import cap_frames as frames
from ui import chemical_upload_panel


def _flash_key(pid: str) -> str:
    return f"judge_proj_flash_{pid}"


def _changed(pid: str, message: str) -> None:
    """판정에 쓰는 입력이 바뀌었으니 예전 판정 결과 화면을 지우고, 안내를 남긴 뒤 다시 그린다."""
    st.session_state.pop(f"judge_out_{pid}", None)
    st.session_state[_flash_key(pid)] = message
    st.rerun()


def _business(project) -> None:
    pid = project.project_id
    info = judgement.business_info(project)
    with st.expander("사업장 정보", expanded=not all(info.values())):
        left, middle, right = st.columns(3)
        name = left.text_input("사업장명", value=info["사업장명"], key=f"judge_biz_name_{pid}",
                               help="사업자등록증에 적힌 사업장(회사) 이름입니다.", placeholder="(예시) 한국화학 울산공장")
        address = middle.text_input("사업장 주소", value=info["사업장 주소"], key=f"judge_biz_address_{pid}",
                                    help="사업장이 실제로 있는 도로명 주소입니다. 기상 정보와 주변 보호대상 조회에 쓰입니다.",
                                    placeholder="(예시) 울산광역시 남구 산업로 1")
        industry = right.text_input("업종 또는 주요 생산품", value=info["업종 또는 주요 생산품"], key=f"judge_biz_industry_{pid}",
                                    help="사업장에서 하는 일과 만드는 제품을 짧게 적습니다. 판정 계산에는 쓰이지 않고, "
                                         "공정안전보고서 별지 제12호의 주요 생산품 칸에 다시 쓰입니다.",
                                    placeholder="(예시) 기초화학물질 제조 / 염화비닐 생산")
        st.caption("여기서 고친 내용은 이 사업장의 판정과 별지 작성에 바로 반영됩니다. 비워서 저장하면 기존 값은 지워지지 않습니다.")
        if st.button("사업장 정보 저장", key=f"judge_biz_save_{pid}"):
            judgement.save_business(project, name, address, industry)
            storage.save_project(project)
            _changed(pid, "사업장 정보를 저장했습니다. 별지 작성 화면에도 같은 내용이 보입니다.")


def _rows(project) -> list[dict]:
    _, rows = chem._rows(project)
    return rows


def _chemicals(project) -> None:
    pid = project.project_id
    rows = _rows(project)
    with st.expander(f"물질 목록 — {len(rows)}건", expanded=not rows):
        if rows:
            frames.show(pd.DataFrame([{
                "제품명": r.get("제품명") or r.get("물질명") or "",
                "CAS No.": r.get("CAS No.") or r.get("CAS 번호") or "",
                "하루 최대 제조·사용량(ton)": r.get("최대 제조·사용량") or "",
                "최대 저장량(ton)": r.get("최대 저장량") or "",
            } for r in rows]), width="stretch", hide_index=True)
        else:
            st.info("이 사업장에는 아직 물질이 없습니다. 아래에서 엑셀·CSV로 올려 주세요.")

        def add_uploaded(good, file_name, sha256):
            added, skipped = chem_upload.add_to_project(project, good, file_name=file_name, sha256=sha256)
            storage.save_project(project)
            st.session_state.pop(f"judge_out_{pid}", None)  # 물질이 바뀌면 예전 판정 결과는 더 이상 맞지 않는다
            return (f"{file_name}에서 물질 {added}건을 이 사업장에 추가했습니다(이미 있어 건너뜀 {skipped}건). "
                    "물질이 바뀌었으니 아래 '법정 대상 판정하기'(또는 '다시 판정하기')로 결과를 확인하세요.")

        chemical_upload_panel.render(f"judge_upload_{pid}", existing=chem_upload.existing_keys(project), add_rows=add_uploaded)


def render(project) -> None:
    flash = st.session_state.pop(_flash_key(project.project_id), "")
    if flash:
        st.success(flash)
    _business(project)
    _chemicals(project)
