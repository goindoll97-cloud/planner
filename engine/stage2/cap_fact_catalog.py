"""화학사고예방관리계획서 사실 카탈로그 읽기.

사실 하나 = 회사 파일에서 한 번 읽어 여러 별지 칸에 쓰는 값 하나입니다.
내용은 data/stage2/cap_fact_catalog.json에만 있고, 이 모듈은 그 파일을 읽어 검사하고 찾기 쉽게 돌려줍니다.
전문가가 JSON을 고치면 화면(사실 표)·업로드 양식·파일 읽기가 함께 바뀝니다.

source가 company(회사 자료)나 project(사업장 등록)인 사실은 ‘회사가 올리는 사실’이고,
computed(프로그램 계산)·legal(법령 조회·판정)·survey(지도·현장 조사)는 따로 보여 줍니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Iterable

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_fact_catalog.json"
SCHEMA_VERSION = "cap-fact-catalog-v1"

KINDS = ("site", "narrative", "facility", "material", "detector", "target", "computed", "legal")
SOURCES = ("company", "project", "survey", "computed", "legal")
COMPANY_SOURCES = ("company", "project")
ENTITY_KINDS = ("facility", "material", "detector")      # 표의 한 줄이 대상 하나인 사실
SITE_KINDS = ("site", "narrative")                       # 사업장에 하나뿐인 사실
FORMATS = ("text", "number", "choice")
GROUPS = ("1군", "2군")


def header_key(value: object) -> str:
    """머리글 비교용 표기. evidence_workspace.norm과 같은 규칙입니다(시험으로 확인)."""
    return re.sub(r"[\s().·_-]", "", str(value)).lower()


@dataclass(frozen=True)
class Use:
    form: int
    cell: str


@dataclass(frozen=True)
class Fact:
    id: str
    name: str
    kind: str
    source: str
    format: str = "text"
    unit: str = ""
    options: tuple[str, ...] = ()
    field_key: str = ""
    column: str = ""
    targets: tuple[tuple[str, str], ...] = ()
    evidence_field: str = ""
    identifier: bool = False
    headers: tuple[str, ...] = ()
    file: str = ""
    groups: tuple[str, ...] = GROUPS
    used_in: tuple[Use, ...] = ()
    required: bool = True
    condition: str = ""
    note: str = ""

    @property
    def from_company(self) -> bool:
        """회사가 올리는 파일에서 오는 사실인지(계산·법령 조회·지도 조사와 구분)."""
        return self.source in COMPANY_SOURCES

    @property
    def readable(self) -> bool:
        """파일 머리글·항목 이름으로 알아볼 수 있는 사실인지."""
        return bool(self.headers) and (bool(self.evidence_field) or self.identifier)

    @property
    def label(self) -> str:
        return f"{self.name}({self.unit})" if self.unit else self.name

    @property
    def template_header(self) -> str:
        """업로드 양식에 쓰는 열 이름(파일 읽기가 알아보는 첫 번째 표기)."""
        return self.headers[0] if self.headers else self.name

    @property
    def forms(self) -> tuple[int, ...]:
        return tuple(sorted({use.form for use in self.used_in}))

    @property
    def used_in_text(self) -> str:
        return forms_text(self.forms)


BODY_FORM = 0          # used_in의 form 0: 계획서 본문의 서술형 장(사전관리방침·비상대응계획)


def forms_text(forms: Iterable[int]) -> str:
    """(3, 4, 16) → ‘별지 제3·4·16호’, (0, 16) → ‘본문 서술형, 별지 제16호’."""
    numbers = sorted(set(int(f) for f in forms))
    parts = ["본문 서술형"] if BODY_FORM in numbers else []
    annex = [n for n in numbers if n != BODY_FORM]
    if annex:
        parts.append("별지 제" + "·".join(str(n) for n in annex) + "호")
    return ", ".join(parts)


def _fact(raw: dict[str, Any]) -> Fact:
    return Fact(
        id=str(raw["id"]), name=str(raw["name"]), kind=str(raw["kind"]), source=str(raw["source"]),
        format=str(raw.get("format") or "text"), unit=str(raw.get("unit") or ""),
        options=tuple(str(v) for v in raw.get("options") or ()),
        field_key=str(raw.get("field_key") or ""), column=str(raw.get("column") or ""),
        targets=tuple((str(t["key"]), str(t["column"])) for t in raw.get("targets") or ()),
        evidence_field=str(raw.get("evidence_field") or ""), identifier=bool(raw.get("identifier")),
        headers=tuple(str(h) for h in raw.get("headers") or ()), file=str(raw.get("file") or ""),
        groups=tuple(str(g) for g in raw.get("groups") or GROUPS),
        used_in=tuple(Use(int(u["form"]), str(u["cell"])) for u in raw.get("used_in") or ()),
        required=bool(raw.get("required", True)), condition=str(raw.get("condition") or ""),
        note=str(raw.get("note") or ""),
    )


@lru_cache(maxsize=1)
def load_raw() -> dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("지원하지 않는 사실 카탈로그 버전입니다.")
    return raw


@lru_cache(maxsize=1)
def all_facts() -> tuple[Fact, ...]:
    facts = tuple(_fact(item) for item in load_raw()["facts"])
    problems = validate(facts, load_raw())
    if problems:
        raise ValueError("사실 카탈로그를 확인하세요: " + " / ".join(problems[:5]))
    return facts


def get(fact_id: str) -> Fact:
    for item in all_facts():
        if item.id == fact_id:
            return item
    raise KeyError(fact_id)


def facts(*, group: str = "", kinds: Iterable[str] = (), forms: Iterable[int] = (), company: bool | None = None) -> list[Fact]:
    """조건에 맞는 사실(카탈로그 순서). group=‘1군’·‘2군’, company=True면 회사 자료만, False면 계산·조회만."""
    kinds, forms = set(kinds), set(forms)
    out = []
    for item in all_facts():
        if group and group not in item.groups:
            continue
        if kinds and item.kind not in kinds:
            continue
        if forms and not forms & set(item.forms):
            continue
        if company is not None and item.from_company != company:
            continue
        out.append(item)
    return out


def kind_label(kind: str) -> str:
    return str(load_raw()["kinds"].get(kind, kind))


def source_label(source: str) -> str:
    return str(load_raw()["sources"].get(source, source))


def file_types() -> dict[str, dict[str, Any]]:
    return dict(load_raw().get("files") or {})


def file_label(file_id: str) -> str:
    return str(file_types().get(file_id, {}).get("name") or file_id)


def ignored_headers() -> frozenset[str]:
    """파일 읽기에서 모르는 열로 알리지 않는 일반적인 머리글(비고·연번 등)."""
    return frozenset(header_key(h) for h in load_raw().get("ignored_headers") or ())


def excluded_keys() -> dict[str, str]:
    """사실로 두지 않는 작성자료 키와 그 이유(도면·예전 이름 등)."""
    return dict(load_raw().get("excluded_keys") or {})


def header_map(kind: str) -> dict[str, str]:
    """이 종류의 표에서 머리글 표기 → 읽은 값을 담을 항목(evidence_field). 식별자 열은 넣지 않습니다."""
    out: dict[str, str] = {}
    for item in all_facts():
        if item.kind == kind or (kind == "site" and item.kind in SITE_KINDS) or (kind == "site" and item.kind == "legal"):
            if item.identifier or not item.evidence_field:
                continue
            for header in item.headers:
                out.setdefault(header_key(header), item.evidence_field)
    return out


def identifier_headers(kind: str) -> frozenset[str]:
    return frozenset(header_key(h) for item in all_facts() if item.kind == kind and item.identifier for h in item.headers)


def by_evidence_field(kind: str) -> dict[str, Fact]:
    """(종류별) 읽은 항목 → 사실. 사업장 종류에는 서술형과 작성수준(판정과 비교용)이 함께 들어갑니다."""
    kinds = {kind} | (set(SITE_KINDS) | {"legal"} if kind == "site" else set())
    return {item.evidence_field: item for item in all_facts() if item.kind in kinds and item.evidence_field}


def evidence_labels() -> dict[str, str]:
    """카탈로그가 더하는 읽기 항목의 화면 이름(단위 포함). 같은 항목은 처음 나온 이름을 씁니다."""
    out: dict[str, str] = {}
    for item in all_facts():
        if item.evidence_field:
            out.setdefault(item.evidence_field, item.label)
    return out


def validate(items: Iterable[Fact], raw: dict[str, Any] | None = None) -> list[str]:
    """카탈로그를 고친 사람이 실수했을 때 알려 줄 문제 목록(비어 있으면 정상)."""
    raw = raw or {}
    items = list(items)
    problems: list[str] = []
    seen_ids: set[str] = set()
    files = set((raw.get("files") or {}).keys())
    by_kind_header: dict[tuple[str, str], str] = {}
    for item in items:
        where = item.id
        if item.id in seen_ids:
            problems.append(f"{where}: id가 겹칩니다")
        seen_ids.add(item.id)
        if not item.name:
            problems.append(f"{where}: 이름이 없습니다")
        if item.kind not in KINDS:
            problems.append(f"{where}: 알 수 없는 종류 {item.kind}")
        if item.source not in SOURCES:
            problems.append(f"{where}: 알 수 없는 출처 {item.source}")
        if item.format not in FORMATS:
            problems.append(f"{where}: 알 수 없는 형식 {item.format}")
        if item.format == "choice" and not item.options:
            problems.append(f"{where}: 선택지가 없습니다")
        if not item.used_in:
            problems.append(f"{where}: 쓰이는 별지(used_in)가 없습니다")
        for use in item.used_in:
            if not BODY_FORM <= use.form <= 16 or not use.cell:
                problems.append(f"{where}: 쓰이는 칸이 잘못됐습니다 ({use.form}, {use.cell})")
        if not set(item.groups) or not set(item.groups) <= set(GROUPS):
            problems.append(f"{where}: 작성수준(1군·2군)이 잘못됐습니다")
        if files and item.file and item.file not in files:
            problems.append(f"{where}: 알 수 없는 파일 종류 {item.file}")
        if item.source == "company":
            if not item.headers:
                problems.append(f"{where}: 회사 자료인데 알아볼 머리글(headers)이 없습니다")
            if not item.file:
                problems.append(f"{where}: 올릴 파일 종류(file)가 없습니다")
            if not item.field_key:
                problems.append(f"{where}: 작성자료 키(field_key)가 없습니다")
            if not (item.evidence_field or item.identifier):
                problems.append(f"{where}: 읽은 값을 담을 항목(evidence_field)이 없습니다")
        if item.kind in ENTITY_KINDS and item.from_company and not item.column:
            problems.append(f"{where}: 표 열 이름(column)이 없습니다")
        group_kind = "site" if item.kind in SITE_KINDS or item.kind == "legal" else item.kind
        for header in item.headers:
            key = (group_kind, header_key(header))
            owner = by_kind_header.get(key)
            target = item.evidence_field or ("#id:" + item.id)
            if owner is not None and owner != target:
                problems.append(f"{where}: 머리글 ‘{header}’를 다른 사실도 씁니다")
            by_kind_header[key] = target
    for kind in ENTITY_KINDS:
        if not any(i.kind == kind and i.identifier for i in items):
            problems.append(f"{kind}: 대상을 구별할 식별자 사실이 없습니다")
    return problems
