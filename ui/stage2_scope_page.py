from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from engine.stage2.project import create_project_from_stage1_snapshot
from engine.stage2.standalone_entry import (
    create_project_from_standalone_workbook,
    inspect_standalone_workbook,
    is_standalone_stage2_project,
)
from engine.stage2.storage import (
    delete_project,
    list_projects,
    load_project,
    save_attachment,
    save_project,
)


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
SNAPSHOT_KEY = "_stage2_stage1_snapshot"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
FLASH_KEY = "_stage2_project_flash"
KST = ZoneInfo("Asia/Seoul")


st.set_page_config(page_title="작성범위 선택", page_icon="🧭", layout="wide")
st.title("🧭 2. 작성범위 선택")
st.caption(
    "일반적으로는 Stage 1 판정결과를 이어서 사용합니다. 이미 작성한 통합 작성자료가 있다면 Stage 1을 다시 업로드하지 않고 "
    "Stage 2 작성·검토를 직접 시작할 수도 있습니다."
)

flash = st.session_state.pop(FLASH_KEY, "")
if flash:
    st.success(flash)


def _legal_status(value: bool | None) -> str:
    if value is True:
        return "대상"
    if value is False:
        return "비대상"
    return "미확정"


def _format_datetime(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "기록 없음"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _direct_stage2_start(projects: list[dict]) -> None:
    with st.expander("Stage 2 통합 작성자료로 직접 시작", expanded=not projects):
        st.caption(
            "이미 작성한 프로그램용 '통합 작성자료.xlsx'가 있으면 여기에서 바로 작성 프로젝트를 만들 수 있습니다. "
            "이 경로는 법적 대상 여부를 새로 판정하지 않고, 파일에 기록된 작성범위와 회사 사실을 작성·검토용으로 불러옵니다."
        )
        upload = st.file_uploader(
            "작성 완료한 통합 작성자료 Excel",
            type=["xlsx"],
            key="stage2_direct_start_workbook",
        )
        if upload is None:
            return

        raw = upload.getvalue()
        try:
            preview = inspect_standalone_workbook(raw)
        except Exception as exc:
            st.error(f"통합 작성자료를 확인하지 못했습니다: {type(exc).__name__}: {exc}")
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("회사", preview.company_name)
        c2.metric("작성범위", " + ".join(preview.scope_labels))
        c3.metric(
            "화학사고예방관리계획서 작성수준",
            preview.cap_group if preview.cap_selected else "작성 안 함",
        )
        if preview.address:
            st.caption(f"사업장 소재지 · {preview.address}")

        existing_ids = {row["project_id"] for row in projects}
        if preview.project_id in existing_ids:
            st.warning(
                f"이 통합 작성자료의 작성 프로젝트({preview.project_id})가 이미 저장되어 있습니다. "
                "기존 프로젝트를 선택하면 같은 자료를 이어서 사용할 수 있습니다."
            )
            if st.button("기존 작성 프로젝트 선택", width="stretch", key="select_existing_direct_project"):
                st.session_state[ACTIVE_PROJECT_KEY] = preview.project_id
                st.session_state[FLASH_KEY] = f"기존 작성 프로젝트를 선택했습니다: {preview.project_id}"
                st.rerun()
            return

        acknowledged = st.checkbox(
            "이 직접 시작 기능은 Stage 1 법적 대상 여부를 판정하지 않으며, 업로드 파일의 작성범위를 기준으로 검토용 작성 작업을 시작한다는 점을 확인했습니다.",
            key="stage2_direct_start_ack",
        )
        if st.button(
            "이 통합 작성자료로 Stage 2 시작",
            type="primary",
            width="stretch",
            disabled=not acknowledged,
            key="stage2_direct_start_button",
        ):
            try:
                workbook_ref = save_attachment(
                    preview.project_id,
                    upload.name,
                    raw,
                    source_type="STAGE2_INTEGRATED_WORKBOOK",
                    note="Stage 1 판정진단 없이 직접 시작한 회사 작성 통합 작성자료",
                )
                project, result, _ = create_project_from_standalone_workbook(
                    raw,
                    workbook_evidence=workbook_ref,
                )
                save_project(project)
            except Exception as exc:
                # The project id did not exist before this operation, so an
                # incomplete direct-start folder can be removed safely.
                try:
                    delete_project(preview.project_id)
                except Exception:
                    pass
                st.error(f"Stage 2 작성 프로젝트를 만들지 못했습니다: {type(exc).__name__}: {exc}")
            else:
                st.session_state[ACTIVE_PROJECT_KEY] = project.project_id
                st.session_state[FLASH_KEY] = (
                    f"통합 작성자료에서 Stage 2 작성 프로젝트를 만들었습니다: {project.project_id} · "
                    f"입력·확인 {result.updated_fields}개, 구조화 표 {result.table_fields}개"
                )
                st.rerun()


def _project_selector() -> str | None:
    projects = list_projects()
    snapshot = st.session_state.get(SNAPSHOT_KEY)

    with st.container(border=True):
        st.markdown("### 작성 프로젝트")
        if snapshot:
            decision = snapshot.get("decision", {})
            st.caption(
                f"최근 Stage 1 결과 · {PSM_FULL}: {decision.get('psm_status', '')} / "
                f"{CAP_FULL}: {decision.get('cap_status', '')}"
            )
            if st.button("최근 판정결과로 새 작성 프로젝트 만들기", type="primary", width="stretch"):
                project = create_project_from_stage1_snapshot(snapshot)
                save_project(project)
                st.session_state[ACTIVE_PROJECT_KEY] = project.project_id
                st.session_state[FLASH_KEY] = f"새 작성 프로젝트를 생성했습니다: {project.project_id}"
                st.rerun()

        _direct_stage2_start(projects)

        projects = list_projects()
        if not projects:
            st.info(
                "저장된 작성 프로젝트가 없습니다. 1. 판정진단을 완료하거나, 위의 'Stage 2 통합 작성자료로 직접 시작'에서 이미 작성한 파일을 업로드하세요."
            )
            return None

        by_id = {row["project_id"]: row for row in projects}
        labels = {
            row["project_id"]: (
                f"{row['company_name']}"
                + (f" / {row['site_name']}" if row.get("site_name") else "")
                + f" · 생성 {_format_datetime(row.get('created_at'))}"
                + f" · {row['project_id']}"
            )
            for row in projects
        }
        ids = [row["project_id"] for row in projects]
        current = st.session_state.get(ACTIVE_PROJECT_KEY)
        index = ids.index(current) if current in ids else 0
        selected = st.selectbox(
            "작성 프로젝트",
            ids,
            index=index,
            format_func=lambda pid: labels.get(pid, pid),
        )
        st.session_state[ACTIVE_PROJECT_KEY] = selected

        selected_meta = by_id[selected]
        c1, c2 = st.columns(2)
        c1.caption(f"생성일시 · {_format_datetime(selected_meta.get('created_at'))} (한국시간)")
        c2.caption(f"최근 수정일시 · {_format_datetime(selected_meta.get('updated_at'))} (한국시간)")

        with st.expander("프로젝트 관리", expanded=False):
            st.warning(
                "프로젝트를 삭제하면 이 프로젝트에 저장된 통합 작성자료 정보와 첨부자료가 함께 삭제됩니다. "
                "Stage 1 판정결과 자체를 비대상으로 변경하거나 법적 판정을 수정하는 기능은 아닙니다."
            )
            confirm = st.checkbox(
                f"{selected} 프로젝트와 저장된 첨부자료를 삭제합니다.",
                key=f"delete_confirm_{selected}",
            )
            if st.button(
                "선택한 작성 프로젝트 삭제",
                type="secondary",
                width="stretch",
                disabled=not confirm,
                key=f"delete_project_{selected}",
            ):
                try:
                    removed = delete_project(selected)
                except Exception as exc:
                    st.error(f"프로젝트를 삭제하지 못했습니다: {type(exc).__name__}: {exc}")
                else:
                    if removed:
                        st.session_state.pop(ACTIVE_PROJECT_KEY, None)
                        st.session_state[FLASH_KEY] = f"작성 프로젝트를 삭제했습니다: {selected}"
                        st.rerun()
                    else:
                        st.warning("이미 삭제되었거나 저장된 프로젝트를 찾을 수 없습니다.")

        return selected


project_id = _project_selector()
if not project_id:
    st.stop()

try:
    project = load_project(project_id)
except Exception as exc:
    st.error(f"프로젝트를 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

direct_mode = is_standalone_stage2_project(project)
if direct_mode:
    st.markdown("### 작성범위 확인")
    st.warning(
        "이 프로젝트는 Stage 1 판정진단을 연결하지 않고 통합 작성자료에서 직접 시작했습니다. "
        "아래 범위는 법적 제출 대상 판정이 아니라 작성·검토를 위한 범위입니다. 최종 제출 전에는 별도의 법적 대상 확인이 필요합니다."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.metric(PSM_FULL, "작성" if project.psm_required is True else "작성 안 함")
    with c2:
        cap_value = "작성" if project.cap_required is True else "작성 안 함"
        if project.cap_required is True and project.cap_group:
            cap_value += f" · {project.cap_group}"
        st.metric(CAP_FULL, cap_value)
else:
    st.markdown("### Stage 1 법적 판정결과")
    c1, c2 = st.columns(2)
    with c1:
        st.metric(PSM_FULL, _legal_status(project.psm_required))
        psm_status = project.stage1_snapshot.get("decision", {}).get("psm_status", "")
        if psm_status:
            st.caption(str(psm_status))
    with c2:
        cap_value = _legal_status(project.cap_required)
        if project.cap_group:
            cap_value += f" · {project.cap_group}"
        st.metric(CAP_FULL, cap_value)
        cap_status = project.stage1_snapshot.get("decision", {}).get("cap_status", "")
        if cap_status:
            st.caption(str(cap_status))

st.markdown("### 이번 프로젝트에서 작성할 문서")
if direct_mode:
    st.info(
        "통합 작성자료에 기록된 작성범위를 불러왔습니다. 이 선택은 작성 지원 범위이며 법적 대상 여부를 새로 판단하지 않습니다."
    )
else:
    st.info(
        "아래 선택은 작성 지원 범위만 정합니다. 법적 제출 대상 여부를 다시 판단하거나 변경하지 않습니다. "
        "두 문서를 모두 선택하면 다음 단계의 통합 작성자료에서 공통정보는 한 번만 입력합니다."
    )

psm_default = project.psm_selected if project.scope_confirmed else False
cap_default = project.cap_selected if project.scope_confirmed else False

psm_selected = st.checkbox(
    f"{PSM_FULL} 작성 지원",
    value=psm_default,
    disabled=project.psm_required is not True,
    help=(
        "통합 작성자료에 기록된 작성범위입니다. 법적 제출대상 판정은 이 화면에서 수행하지 않습니다."
        if direct_mode else
        "Stage 1에서 제출 대상으로 확정된 경우에만 선택할 수 있습니다."
    ),
)
cap_selected = st.checkbox(
    f"{CAP_FULL} 작성 지원",
    value=cap_default,
    disabled=project.cap_required is not True,
    help=(
        "통합 작성자료에 기록된 작성범위와 작성수준을 사용합니다. 법적 제출대상 판정은 이 화면에서 수행하지 않습니다."
        if direct_mode else
        "Stage 1에서 작성·제출 대상으로 확정된 경우에만 선택할 수 있습니다."
    ),
)

if project.psm_required is True and not psm_selected:
    if direct_mode:
        st.warning(f"{PSM_FULL}가 직접 시작 파일의 작성범위에서 제외됩니다.")
    else:
        st.warning(
            f"{PSM_FULL}는 Stage 1 판정상 제출 대상입니다. 선택하지 않으면 이번 작성 프로젝트의 지원 범위에서만 제외되며, "
            "법적 대상 판정은 그대로 유지됩니다."
        )
if project.cap_required is True and not cap_selected:
    if direct_mode:
        st.warning(f"{CAP_FULL}가 직접 시작 파일의 작성범위에서 제외됩니다.")
    else:
        st.warning(
            f"{CAP_FULL}는 Stage 1 판정상 작성·제출 대상입니다. 선택하지 않으면 이번 작성 프로젝트의 지원 범위에서만 제외되며, "
            "법적 대상 판정은 그대로 유지됩니다."
        )

if project.psm_required is not True and project.cap_required is not True:
    st.info("작성범위로 선택된 문서가 없어 다음 단계로 진행할 수 없습니다.")
else:
    if st.button("작성범위 저장", type="primary", width="stretch"):
        try:
            project.set_authoring_scope(
                psm_selected=bool(psm_selected),
                cap_selected=bool(cap_selected),
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            save_project(project)
            st.success("작성범위를 저장했습니다. 다음 단계에서 통합 작성자료와 첨부자료를 확인할 수 있습니다.")
            st.rerun()

if project.scope_confirmed:
    selected_labels = []
    if project.psm_in_scope:
        selected_labels.append(PSM_FULL)
    if project.cap_in_scope:
        selected_labels.append(CAP_FULL)
    st.success("현재 작성범위: " + ", ".join(selected_labels))
    st.page_link("ui/stage2_intake_page.py", label="3. 통합 작성자료로 이동", icon="📥")
