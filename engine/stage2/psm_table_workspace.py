from __future__ import annotations

"""PSM 표 서식(별지 제14호 등)을 화면 표로 작성한다. 서식마다 데이터 정의만 다르고 저장·점검 방식은 같다.

저장 키와 열 이름은 서식 출력 코드(statutory_report)가 읽는 이름과 같게 둔다. 이 화면이 그 표의 유일한 입력 창구이므로
저장할 때 표 전체를 교체하고, 완전히 빈 행은 버린다.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from .project import Stage2Project


@dataclass(frozen=True)
class Column:
    id: str
    label: str
    help: str
    required: bool = True
    kind: str = "text"            # text / number
    options: tuple[str, ...] = ()  # 자주 쓰는 선택지(직접 입력도 가능)


@dataclass(frozen=True)
class TableSpec:
    form_no: str
    key: str
    title: str
    summary: str
    columns: tuple[Column, ...]
    unique: str = ""  # 중복되면 안 되는 열

    def column_ids(self) -> list[str]:
        return [c.id for c in self.columns]


MACHINERY = TableSpec(
    "14", "psm.psi.machinery_list", "동력기계 목록",
    "펌프·압축기·교반기·송풍기처럼 전동기로 돌아가는 기계를 한 줄에 하나씩 적습니다. 기계 사양서와 P&ID에서 확인합니다.",
    (
        Column("기계번호", "동력기계 번호", "도면(P&ID)에 붙은 기계 기호입니다. 예: P-101"),
        Column("기계명", "동력기계명", "기계의 이름입니다. 예: 염소 이송 펌프, 배기 팬"),
        Column("명세", "명세", "종류와 용량입니다. 예: 원심펌프 10 m3/h, 양정 30 m"),
        Column("주요재질", "주요재질", "물질과 닿는 부분의 주된 재질입니다. 예: SUS316, 카본강"),
        Column("전동기용량", "전동기용량(kW)", "전동기의 용량(kW)입니다. 명판이나 사양서에서 확인합니다."),
        Column("방호·보호장치 종류", "방호·보호장치의 종류",
               "법으로 정한 안전·방호장치와 모터보호장치(THT＼R, EOCR, EMPR 등)를 적습니다.",
               options=("THT＼R", "EOCR", "EMPR", "안전커버", "과부하 계전기")),
        Column("비고", "비고", "인버터나 기동방식(직입, Y-Δ 등)을 적습니다. 없으면 비워 둡니다.", required=False),
    ),
    unique="기계번호",
)

SPECS: dict[str, TableSpec] = {spec.form_no: spec for spec in (MACHINERY,)}


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def rows(project: Stage2Project, form_no: str) -> list[dict[str, str]]:
    spec = SPECS[form_no]
    record = project.get_field(spec.key)
    if record is None or not isinstance(record.value, list):
        return []
    return [{c: _clean(row.get(c)) for c in spec.column_ids()} for row in record.value if isinstance(row, Mapping)]


def save(project: Stage2Project, form_no: str, new_rows: list[Mapping[str, Any]]) -> int:
    spec = SPECS[form_no]
    cleaned = [{c: _clean(row.get(c)) for c in spec.column_ids()} for row in new_rows]
    cleaned = [row for row in cleaned if any(row.values())]
    project.set_field(spec.key, f"{spec.title}(작성대)", cleaned, "USER_CONFIRMED")
    return len(cleaned)


def needs(project: Stage2Project, form_no: str) -> list[str]:
    spec = SPECS[form_no]
    current = rows(project, form_no)
    if not current:
        return [f"{spec.title}에 적은 행이 없습니다."]
    out = []
    for index, row in enumerate(current, start=1):
        missing = [c.label for c in spec.columns if c.required and not row[c.id]]
        if missing:
            out.append(f"{index}행: {', '.join(missing)}이(가) 비어 있습니다.")
    if spec.unique:
        seen: set[str] = set()
        for row in current:
            value = "".join(row[spec.unique].split()).lower()
            if value and value in seen:
                out.append(f"{row[spec.unique]}이(가) 두 번 이상 적혀 있습니다.")
            seen.add(value)
    return out
