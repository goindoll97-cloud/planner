from __future__ import annotations

"""Keep company-facing intake labels in full Korean legal/report names.

Internal field keys remain unchanged.  The first company workbook must not
expose developer abbreviations such as PSM/CAP, while older workbook labels are
accepted as compatibility aliases if encountered.
"""

from dataclasses import replace
from typing import Any, Mapping

from . import company_intake_contract as contract


LABEL_ALIASES: tuple[tuple[str, str], ...] = (
    ("PSM 사업 구분", "공정안전보고서 사업 구분"),
    ("PSM 심사대상 설비명", "공정안전보고서 심사대상 설비명"),
    ("PSM 부지면적(㎡)", "공정안전보고서 부지면적(㎡)"),
    ("PSM 주요건물(동/층/연면적)", "공정안전보고서 주요건물(동/층/연면적)"),
    ("PSM 보고서 작성자 성명", "공정안전보고서 작성자 성명"),
    ("PSM 보고서 작성자 자격", "공정안전보고서 작성자 자격"),
    ("PSM 총사업기간", "공정안전보고서 총사업기간"),
    ("PSM 착공예정일", "공정안전보고서 착공예정일"),
    ("PSM 시운전기간", "공정안전보고서 시운전기간"),
    ("CAP 단위공장명", "화학사고예방관리계획서 단위공장명"),
    ("CAP 산업단지명", "화학사고예방관리계획서 산업단지명"),
    ("CAP 제출구분", "화학사고예방관리계획서 제출구분"),
    ("CAP 공동비상대응계획 수립 여부", "화학사고예방관리계획서 공동비상대응계획 수립 여부"),
    ("CAP 유사제도 심사결과 활용 여부", "화학사고예방관리계획서 유사제도 심사결과 활용 여부"),
    ("CAP 최근 3년간 화학사고 발생 여부", "화학사고예방관리계획서 최근 3년간 화학사고 발생 여부"),
    ("CAP 작성자 성명", "화학사고예방관리계획서 작성자 성명"),
    ("CAP 담당자 연락처", "화학사고예방관리계획서 담당자 연락처"),
    ("CAP 담당자 이메일", "화학사고예방관리계획서 담당자 이메일"),
)


def _aliased_business(business: Mapping[str, Any]) -> dict[str, Any]:
    """Return both current full labels and pre-release abbreviation aliases."""
    values = dict(business)
    for old, current in LABEL_ALIASES:
        if current in values and old not in values:
            values[old] = values[current]
        elif old in values and current not in values:
            values[current] = values[old]
    return values


def install_company_intake_fullname_runtime() -> None:
    if getattr(contract, "_fullname_runtime_installed", False):
        return

    rename = dict(LABEL_ALIASES)
    contract.COMPANY_FACT_SPECS = tuple(
        replace(spec, label=rename.get(spec.label, spec.label))
        for spec in contract.COMPANY_FACT_SPECS
    )

    original_seed = contract.seed_company_facts

    def seed_company_facts_with_aliases(project: Any, business: Mapping[str, object]) -> None:
        original_seed(project, _aliased_business(business))

    contract.seed_company_facts = seed_company_facts_with_aliases
    contract._fullname_runtime_installed = True
