from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from . import statutory_report as report
from .project import Stage2Project


FORM12_HEADERS = (
    "사업장명", "제출구분", "사업자등록번호", "대표자", "대상 유해·위험설비",
    "한국표준산업분류", "근로자수", "계약전력(kW)", "작성자 성명", "작성자 자격",
    "주요 원료", "주요 생산품", "사업개요", "사업장 소재지", "전화번호", "전송번호",
    "부지면적", "주요 건물", "총 사업기간", "착공예정일", "시운전기간",
)

FORM19_2_HEADERS = (
    "시나리오 구분", "풍속(m/s)", "대기안정도(A~F)", "대기온도(℃)", "습도(%)",
    "표면거칠기", "물질명", "물질의 상태", "설비명(또는 배관부위)",
    "운전압력(MPa)", "운전온도(℃)", "누출구의 크기(mm2)", "웅덩이 크기(m2)",
    "누출결과", "직접계산(kg/s or kg)", "웅덩이(kg/s)", "설비/배관(kg/s)",
    "화재-4 kW/m2", "화재-12.5 kW/m2", "화재-37.5 kW/m2",
    "폭발-7 kPa", "폭발-21 kPa", "폭발-70 kPa",
    "인화성-25% LEL", "인화성-LEL", "인화성-UEL",
    "독성-ERPG 1", "독성-ERPG 2", "독성-ERPG 3", "계산모델·결과 근거",
)

VALID_PROJECT_TYPES = {"설치이전", "변경", "기존설비"}
VALID_SCENARIOS = {"최악의사고시나리오", "대안의사고시나리오"}
VALID_SURFACE = {"시골", "도시", "물위"}
VALID_STATE = {"기체", "액체", "2상액체기체"}


@dataclass(frozen=True)
class PSMFormReadiness:
    form_no: str
    form_name: str
    rows: tuple[tuple[str, ...], ...]
    blockers: tuple[str, ...]
    messages: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


def _norm(value: object) -> str:
    return report._norm(value)


def _clean(value: object) -> str:
    if value in (None, "", report.MISSING):
        return ""
    return str(value).strip()


def _rows(project: Stage2Project, key: str, headers: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    output: list[tuple[str, ...]] = []
    for row in report._rows(project, key):
        if not isinstance(row, Mapping):
            continue
        output.append(tuple(_clean(report._row_value(row, header)) for header in headers))
    return tuple(output)


def build_psm_form12_readiness(project: Stage2Project) -> PSMFormReadiness:
    rows = _rows(project, "psm.business.form12_details", FORM12_HEADERS)
    blockers: list[str] = []

    if not rows:
        blockers.append("별지 제12호서식 사업개요를 작성할 구조화 회사자료가 없습니다.")
    elif len(rows) != 1:
        blockers.append(
            f"별지 제12호서식 사업개요는 사업장 기준 1행이어야 하나 {len(rows)}행이 입력되었습니다."
        )
    else:
        row = rows[0]
        missing = [header for header, value in zip(FORM12_HEADERS, row) if not value]
        if missing:
            blockers.append(
                "별지 제12호서식에서 "
                + ", ".join(missing)
                + " 값이 확인되지 않았습니다. 적용되지 않는 항목은 빈칸 대신 '해당 없음'으로 회사 확인해 주세요."
            )

        project_type = _norm(row[1])
        if row[1] and project_type not in VALID_PROJECT_TYPES:
            blockers.append(
                "별지 제12호서식 제출구분은 '설치·이전', '변경', '기존설비' 중 하나로 확인해 주세요."
            )

        stage1_name = _clean(project.company_name)
        entered_name = _clean(row[0])
        if stage1_name and entered_name and _norm(stage1_name) != _norm(entered_name):
            blockers.append(
                "별지 제12호서식의 사업장명이 Stage 1 판정자료의 회사명과 다릅니다. "
                "판정자료가 변경된 경우 Stage 1을 먼저 다시 수행해 주세요."
            )

        address_record = project.get_field("business.address")
        stage1_address = _clean(address_record.value) if address_record is not None else ""
        entered_address = _clean(row[13])
        if stage1_address and entered_address and _norm(stage1_address) != _norm(entered_address):
            blockers.append(
                "별지 제12호서식의 사업장 소재지가 Stage 1 판정자료의 주소와 다릅니다. "
                "판정자료가 변경된 경우 Stage 1을 먼저 다시 수행해 주세요."
            )

    return PSMFormReadiness(
        form_no="12",
        form_name="사업개요",
        rows=rows,
        blockers=tuple(blockers),
        messages=("별지 제12호서식 사업개요의 필수 작성칸과 Stage 1 식별정보 일치를 확인했습니다.",)
        if not blockers else (),
    )


def _applicability(project: Stage2Project) -> tuple[str, str]:
    for row in report._rows(project, "psm.psi.form_applicability"):
        if not isinstance(row, Mapping):
            continue
        form_no = _clean(report._row_value(row, "서식번호", "form_no"))
        if form_no != "19-2":
            continue
        raw = _clean(report._row_value(row, "적용여부", "적용 여부", "applicability"))
        basis = _clean(report._row_value(row, "확인근거", "근거", "basis"))
        normalized = _norm(raw)
        if normalized in {"적용", "예", "해당"}:
            return "적용", basis
        if normalized in {"해당없음", "미적용", "아니오", "없음"}:
            return "해당 없음", basis
        return raw, basis
    return "", ""


def build_psm_form19_2_readiness(project: Stage2Project) -> PSMFormReadiness:
    applicability, basis = _applicability(project)
    blockers: list[str] = []

    if not applicability:
        blockers.append(
            "별지 제19호의2서식 사고피해예측의 적용 여부가 확인되지 않았습니다. "
            "PSM 조건부 서식 적용여부 표에서 '적용' 또는 '해당 없음'을 확인해 주세요."
        )
    elif applicability not in {"적용", "해당 없음"}:
        blockers.append(
            f"별지 제19호의2서식 적용여부 값 '{applicability}'을 해석할 수 없습니다."
        )

    if applicability in {"적용", "해당 없음"} and not basis:
        blockers.append("별지 제19호의2서식 적용여부의 확인근거가 없습니다.")

    if applicability == "해당 없음" and not blockers:
        return PSMFormReadiness(
            form_no="19-2",
            form_name="시나리오 및 피해예측 결과",
            rows=(),
            blockers=(),
            messages=(
                "별지 제19호의2서식은 회사가 '해당 없음'으로 확인했습니다. "
                f"확인근거: {basis}",
            ),
        )

    raw_rows = [
        row for row in report._rows(project, "psm.risk.consequence_table")
        if isinstance(row, Mapping)
    ]
    rows = _rows(project, "psm.risk.consequence_table", FORM19_2_HEADERS)

    if applicability == "적용":
        if not rows:
            blockers.append("별지 제19호의2서식 사고피해예측 수치표가 없습니다.")
        else:
            groups: dict[tuple[str, str], dict[str, list[int]]] = {}
            seen_names: set[str] = set()
            for index, (row, raw) in enumerate(zip(rows, raw_rows), start=1):
                scenario = _norm(row[0])
                unit_plant = _clean(report._row_value(raw, "단위공장", "단위공장·공정"))
                accident_type = _clean(report._row_value(raw, "사고유형"))
                scenario_name = _clean(report._row_value(raw, "시나리오명", "사고시나리오명"))

                if not unit_plant:
                    blockers.append(f"별지 제19호의2서식 {index}행의 단위공장이 확인되지 않았습니다.")
                if not accident_type:
                    blockers.append(f"별지 제19호의2서식 {index}행의 사고유형이 확인되지 않았습니다.")
                if not scenario_name:
                    blockers.append(f"별지 제19호의2서식 {index}행의 시나리오명이 확인되지 않았습니다.")
                elif _norm(scenario_name) in seen_names:
                    blockers.append(f"별지 제19호의2서식의 시나리오명 '{scenario_name}'이 중복 입력되었습니다.")
                else:
                    seen_names.add(_norm(scenario_name))

                if scenario not in VALID_SCENARIOS:
                    blockers.append(
                        f"별지 제19호의2서식 {index}행의 시나리오 구분은 "
                        "'최악의 사고 시나리오' 또는 '대안의 사고 시나리오'여야 합니다."
                    )

                key = (_norm(unit_plant), _norm(accident_type))
                if all(key):
                    bucket = groups.setdefault(key, {"worst": [], "alternative": []})
                    if scenario == "최악의사고시나리오":
                        bucket["worst"].append(index)
                    elif scenario == "대안의사고시나리오":
                        bucket["alternative"].append(index)

                missing = [header for header, value in zip(FORM19_2_HEADERS, row) if not value]
                if missing:
                    blockers.append(
                        f"별지 제19호의2서식 {index}행에서 "
                        + ", ".join(missing)
                        + " 값이 확인되지 않았습니다. 해당하지 않는 결과는 빈칸 대신 '해당 없음'으로 확인해 주세요."
                    )

                if row[5] and _norm(row[5]) not in VALID_SURFACE:
                    blockers.append(
                        f"별지 제19호의2서식 {index}행 표면거칠기는 '시골', '도시', '물위' 중 하나여야 합니다."
                    )
                if row[7] and _norm(row[7]) not in VALID_STATE:
                    blockers.append(
                        f"별지 제19호의2서식 {index}행 물질상태는 '기체', '액체', '2상(액체+기체)' 중 하나여야 합니다."
                    )

            for (unit_norm, accident_norm), bucket in groups.items():
                label_row = raw_rows[bucket["worst"][0] - 1] if bucket["worst"] else raw_rows[bucket["alternative"][0] - 1]
                unit_label = _clean(report._row_value(label_row, "단위공장", "단위공장·공정")) or unit_norm
                accident_label = _clean(report._row_value(label_row, "사고유형")) or accident_norm
                if len(bucket["worst"]) != 1:
                    blockers.append(
                        f"{unit_label} / {accident_label}은 최악의 사고 시나리오가 정확히 1건이어야 합니다 "
                        f"(현재 {len(bucket['worst'])}건)."
                    )
                if len(bucket["alternative"]) < 1:
                    blockers.append(
                        f"{unit_label} / {accident_label}은 대안의 사고 시나리오가 1건 이상 필요합니다."
                    )

    return PSMFormReadiness(
        form_no="19-2",
        form_name="시나리오 및 피해예측 결과",
        rows=rows,
        blockers=tuple(blockers),
        messages=(
            "별지 제19호의2서식의 적용여부와 단위공장·사고유형별 최악 1건/대안 1건 이상을 확인했습니다. "
            f"확인근거: {basis}",
        ) if not blockers else (),
    )
