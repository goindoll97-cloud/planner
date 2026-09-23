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
from engine.stage2 import kosha_candidates
from engine.stage2 import storage
from ui import cap_frames as frames
from ui import chemical_upload_panel, judgement_panel


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
    core_ready = all(info.get(key) for key in ("사업장명", "사업장 주소", "업종 또는 주요 생산품"))
    with st.expander("사업장 정보", expanded=not core_ready):
        left, middle, right = st.columns(3)
        name = left.text_input(
            "사업장명", value=info["사업장명"], key=f"judge_biz_name_{pid}",
            help="사업자등록증에 적힌 사업장(회사) 이름입니다.", placeholder="(예시) 한국화학 울산공장",
        )
        address = middle.text_input(
            "사업장 주소", value=info["사업장 주소"], key=f"judge_biz_address_{pid}",
            help="사업장이 실제로 있는 도로명 주소입니다. 기상 정보와 주변 보호대상 조회에 쓰입니다.",
            placeholder="(예시) 울산광역시 남구 산업로 1",
        )
        industry = right.text_input(
            "업종 또는 주요 생산품", value=info["업종 또는 주요 생산품"], key=f"judge_biz_industry_{pid}",
            help="사업장에서 주로 하는 일이나 만드는 제품을 짧게 적습니다. 예: 합성수지 제조 / 접착제 생산.",
            placeholder="(예시) 기초화학물질 제조 / 염화비닐 생산",
        )
        st.caption("여기서 고친 내용은 이 사업장의 판정과 별지 작성에 바로 반영됩니다.")
        if st.button("사업장 정보 저장", key=f"judge_biz_save_{pid}"):
            # KSIC는 판정에 실제로 필요할 때 후속 질문으로 확인하며, 기존 저장값은 보존한다.
            judgement.save_business(project, name, address, industry)
            storage.save_project(project)
            _changed(pid, "사업장 정보를 저장했습니다. 별지 작성 화면에도 같은 내용이 보입니다.")


def _rows(project) -> list[dict]:
    _, rows = chem._rows(project)
    return rows


def _delete_chemical_rows(project, rows: list[dict]) -> None:
    """물질 목록 표에 삭제 칸을 두고, 고른 행을 지운다. 혼합물 성분·물질별 확인값도 같이 정리한다."""
    pid = project.project_id
    parts = judgement.components_by_row(project)
    gen_key = f"judge_chem_rows_gen_{pid}"
    generation = st.session_state.get(gen_key, 0)
    table = pd.DataFrame([{
        "삭제": False,
        "제품명": r.get("제품명") or r.get("물질명") or "",
        "구분": "혼합물" if judgement._mixture_yes(r.get("혼합물 여부")) else "단일물질",
        "CAS No.": judgement.cas_display(r, number, parts),
        "함량(%)": judgement.content_display(r, number, parts),
        "하루 최대 제조·사용량(ton)": r.get("최대 제조·사용량") or "",
        "최대 저장량(ton)": r.get("최대 저장량") or "",
    } for number, r in enumerate(rows, start=1)])
    disabled = [c for c in table.columns if c != "삭제"]
    edited = st.data_editor(frames.safe(table), width="stretch", hide_index=True, num_rows="fixed",
                            disabled=disabled, key=f"judge_chem_rows_{pid}_{generation}",
                            column_config={"삭제": st.column_config.CheckboxColumn("삭제", help="지울 물질을 고르세요.")})
    if parts:
        st.caption("혼합제품은 제품 자체의 CAS가 없으므로, CAS 칸에 제품 MSDS 제3항에서 옮긴 성분 CAS를 보여 줍니다. "
                   "판정은 이 성분 CAS와 함량으로 합니다.")
    picked = [number for number, checked in enumerate(edited["삭제"].tolist(), start=1) if checked]
    if picked:
        st.caption(f"{len(picked)}건을 선택했습니다.")
    # 라벨·도움말을 선택 개수에 따라 바꾸면 Streamlit이 매번 다른 위젯으로 봐서 클릭이 다음 실행에 반영되지 않는다.
    # 그래서 라벨은 고정하고 건수는 위의 캡션으로만 보여 준다.
    if st.button("선택한 물질 삭제", key=f"judge_chem_del_{pid}", disabled=not picked,
                help="법정 판정과 관련된 확인값·혼합물 성분도 함께 지웁니다. 되돌릴 수 없습니다."):
        removed = chem_upload.remove_rows(project, picked)
        storage.save_project(project)
        st.session_state[gen_key] = generation + 1
        _changed(pid, f"물질 {len(removed)}건을 지웠습니다: {', '.join(removed)}. "
                      "물질이 바뀌었으니 아래 '법정 대상 판정하기'(또는 '다시 판정하기')로 결과를 확인하세요.")


def _chemicals(project) -> None:
    pid = project.project_id
    rows = _rows(project)
    with st.expander(f"물질 목록 — {len(rows)}건", expanded=not rows):
        if rows:
            _delete_chemical_rows(project, rows)
        else:
            st.info("이 사업장에는 아직 물질이 없습니다. 아래에서 엑셀·CSV로 올려 주세요.")

        def add_uploaded(good, file_name, sha256):
            added, skipped = chem_upload.add_to_project(project, good, file_name=file_name, sha256=sha256, sds_confirmed=True)
            storage.save_project(project)
            st.session_state.pop(f"judge_out_{pid}", None)  # 물질이 바뀌면 예전 판정 결과는 더 이상 맞지 않는다
            return (f"{file_name}에서 물질 {added}건을 이 사업장에 추가했습니다(이미 있어 건너뜀 {skipped}건). "
                    "물질이 바뀌었으니 아래 '법정 대상 판정하기'(또는 '다시 판정하기')로 결과를 확인하세요.")

        chemical_upload_panel.render(f"judge_upload_{pid}", existing=chem_upload.existing_keys(project), add_rows=add_uploaded)
        if rows:
            _kosha_all(project)


def mixture_component_rows(project) -> list[dict]:
    """혼합제품의 성분 목록(제품명, 성분 CAS, 함량). 제품목록행번호로 물질 목록의 제품 이름을 찾는다."""
    rows = _rows(project)
    out = []
    for component in judgement.mixture_components(project):
        try:
            parent = int(float(component.get("제품목록행번호")))
        except (TypeError, ValueError):
            continue
        row = rows[parent - 1] if 1 <= parent <= len(rows) else {}
        cas = str(component.get("CAS No.") or "").strip()
        if cas:
            out.append({"제품명": str(row.get("제품명") or row.get("물질명") or f"{parent}행"), "CAS No.": cas,
                        "함량(%)": str(component.get("함량(%)") or "").strip(), "행": parent})
    return out


def _kosha_all(project) -> None:
    """물질 목록 전체의 MSDS 제2항 분류 후보를 KOSHA에서 한 번에 조회한다.

    단일물질은 판정 표가 그대로 쓰는 후보가 된다. 혼합제품은 제품 분류를 성분 분류로 대신할 수 없으므로, 성분 CAS는 조회해서
    '참고'로 보여 주기만 하고 판정 입력에는 넣지 않는다.
    """
    pid = project.project_id
    cand_key, gen_key = f"judge_kosha_{pid}", f"judge_chem_gen_{pid}"
    candidates: dict = st.session_state.get(cand_key, {})
    singles = chem.single_substance_cas(project)
    parts = mixture_component_rows(project)
    part_cas = [c for c in dict.fromkeys(p["CAS No."] for p in parts) if c not in singles]
    targets = [*singles, *part_cas]
    mixtures = len(_rows(project)) - len(singles)
    extra = (f"\n\n혼합제품 {mixtures}건은 제품 자체의 CAS가 없어 조회하지 않고, 성분 CAS만 참고용으로 조회합니다."
             if mixtures > 0 else "")
    st.markdown("**MSDS 제2항 분류 한 번에 조회 (KOSHA)**", help=judgement_panel.KOSHA_HELP + extra)
    todo = kosha_candidates.pending_cas(targets, candidates)
    label = ("조회 완료" if not todo else "KOSHA에서 전체 물질 MSDS 분류 조회" if len(todo) == len(targets)
             else "조회하지 못한 물질만 다시 조회")
    if st.button(label, key=f"judge_kosha_all_{pid}", disabled=not todo,
                 help="CAS 번호만 전송합니다. 회사·수량 정보는 보내지 않습니다."):
        with st.spinner(f"KOSHA에서 {len(todo)}개 물질을 조회하는 중입니다. 물질이 많으면 1분 넘게 걸릴 수 있습니다."):
            found = kosha_candidates.fetch(todo)
        st.session_state[cand_key] = {**candidates, **found}
        st.session_state[gen_key] = st.session_state.get(gen_key, 0) + 1
        st.rerun()
    if singles and candidates:
        have = [c for c in singles if candidates.get(c) is not None and candidates[c].usable]
        missing = [c for c in singles if c not in have and c in candidates]
        st.caption(f"조회 결과: 분류 후보 {len(have)}건 / 후보 없음·실패 {len(missing)}건 / 아직 조회 안 함 {len(singles) - len(have) - len(missing)}건")
        if missing:
            st.caption("후보를 얻지 못한 물질: " + ", ".join(
                f"{cas}({candidates[cas].message or candidates[cas].status})" for cas in missing[:6]) + (" 외" if len(missing) > 6 else "")
                + " — 이 물질은 제품 MSDS를 보고 직접 적어 주세요.")
    reference = [p for p in parts if candidates.get(p["CAS No."]) is not None]
    if reference:
        st.markdown("**혼합제품 성분별 참고 분류**")
        st.warning("성분 하나하나의 분류를 참고로 보여 드립니다. **혼합제품의 MSDS 제2항 분류는 제품 MSDS에 적힌 것을 그대로 옮겨 적어야 합니다.** "
                   "혼합물의 분류는 성분의 함량과 제품 자체의 물성으로 정해지므로 아래 값과 다를 수 있고, 이 값은 판정에 자동으로 반영되지 않습니다.")
        frames.show(pd.DataFrame([{
            "혼합제품": p["제품명"], "성분 CAS No.": p["CAS No."], "함량(%)": p["함량(%)"],
            "성분명(KOSHA)": candidates[p["CAS No."]].chemical_name,
            "성분 기준 분류(참고)": candidates[p["CAS No."]].text or f"({candidates[p['CAS No.']].message or candidates[p['CAS No.']].status})",
        } for p in reference]), width="stretch", hide_index=True)


def render(project) -> None:
    flash = st.session_state.pop(_flash_key(project.project_id), "")
    if flash:
        st.success(flash)
    _business(project)
    _chemicals(project)
