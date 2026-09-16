"""Core modules for the chemical safety planning assistant."""

from __future__ import annotations

import os


_KOSHA_LEGACY_BASE_URL = "https://apis.data.go.kr/B552468/msds_api"
_KOSHA_CURRENT_BASE_URL = "https://apis.data.go.kr/B552468/msdschem"


def _install_kosha_msds_endpoint_migration() -> None:
    """Migrate the retired KOSHA MSDS OpenAPI endpoints in existing .env files.

    The public-data service moved from ``/msds_api`` to ``/msdschem`` in 2026.
    Existing installations may still carry the retired URL in ``.env``.  This
    compatibility layer upgrades only missing values and the exact legacy
    defaults; deliberately customised endpoints are left untouched.
    """
    base = os.getenv("KOSHA_MSDS_BASE_URL", "").strip().rstrip("/")
    if not base or base == _KOSHA_LEGACY_BASE_URL:
        os.environ["KOSHA_MSDS_BASE_URL"] = _KOSHA_CURRENT_BASE_URL

    search = os.getenv("KOSHA_MSDS_SEARCH_URL", "").strip()
    if not search or search == f"{_KOSHA_LEGACY_BASE_URL}/msdslist":
        os.environ["KOSHA_MSDS_SEARCH_URL"] = f"{_KOSHA_CURRENT_BASE_URL}/getChemList"

    for number in range(1, 17):
        padded = f"{number:02d}"
        key = f"KOSHA_MSDS_SECTION_{padded}_URL"
        value = os.getenv(key, "").strip()
        legacy = f"{_KOSHA_LEGACY_BASE_URL}/chemdetail{padded}"
        if not value or value == legacy:
            os.environ[key] = f"{_KOSHA_CURRENT_BASE_URL}/getChemDetail{padded}"

    legacy_section2 = os.getenv("KOSHA_MSDS_SECTION2_URL", "").strip()
    if legacy_section2 == f"{_KOSHA_LEGACY_BASE_URL}/chemdetail02":
        os.environ.pop("KOSHA_MSDS_SECTION2_URL", None)


def _install_company_input_guide_hook() -> None:
    """Attach the canonical generated example/guide workbook to the main uploader.

    The workbook is generated from ``engine.template`` at download time instead
    of being stored as a separate static XLSX.  This keeps the guide structure
    identical to the example/input template and prevents future version drift.
    """
    try:
        import streamlit as st
    except Exception:
        return

    original = st.file_uploader
    if getattr(original, "_planner_company_guide_wrapped", False):
        return

    def guided_file_uploader(*args, **kwargs):
        label = kwargs.get("label")
        if label is None and args:
            label = args[0]
        label_text = str(label or "")

        if label_text.startswith("회사 입력파일 업로드"):
            from .template import build_legal_reference_workbook, build_minimal_input_workbook

            st.markdown("#### 처음 작성하시나요? 최신 작성예시·가이드 파일을 먼저 내려받아 보세요")
            st.caption(
                "판정진단에서 사용하는 최신 회사 입력 구조와 완전히 동일한 파일입니다. "
                "초록색 예시값을 참고하고, 노란색 빈 입력칸에는 귀사 정보를 입력하세요. "
                "선택형 항목이 적용되지 않으면 '해당없음', 아직 확인하지 못했으면 '모름'을 선택하세요."
            )
            st.download_button(
                "회사 입력 작성예시·가이드 파일 다운로드",
                data=build_minimal_input_workbook(),
                file_name="공정안전보고서_화학사고예방관리계획서_회사입력_작성예시_가이드_v1.0.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="company_input_guide_download_v10",
                width="stretch",
            )
            st.download_button(
                "공정안전보고서·화학사고예방관리계획서 법령 작성 참고파일 다운로드",
                data=build_legal_reference_workbook(),
                file_name="공정안전보고서_화학사고예방관리계획서_법령작성참고_v1.0.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="legal_reference_guide_download_v10",
                width="stretch",
            )
            st.caption("법령 참고파일은 입력용 파일이 아닙니다. 각 작성항목과 연결되는 법령·조문·별표만 확인하는 용도입니다.")

        return original(*args, **kwargs)

    guided_file_uploader._planner_company_guide_wrapped = True
    st.file_uploader = guided_file_uploader


_install_kosha_msds_endpoint_migration()

# Keep the initial company workbook synchronized with the facts that the final
# PSM/CAP statutory-form writers need, while leaving AI-draftable narrative and
# rule-engine calculations out of the company-direct input burden.
from .company_intake_contract import install_company_intake_contract

install_company_intake_contract()
_install_company_input_guide_hook()
