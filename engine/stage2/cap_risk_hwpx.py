from __future__ import annotations

"""Byte-preserving renderers for current CAP Annex Forms 14 and 15.

The official law.go.kr HWPX remains the layout authority.  Form 14 is rendered
one accident scenario per official-form copy; the multi-form runtime duplicates
that official attachment when the project has multiple scenarios.  Form 15 may
grow only its existing scenario data rows by cloning a real template row.

Every semantic target is resolved from labels first.  Missing/ambiguous labels
produce warnings and do not fall back to guessed coordinates.
"""

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any, Mapping, Sequence
from zipfile import ZipFile

from hwpx.patch import paragraph_chunks, paragraph_patch
from hwpx.table_patch import apply_table_ops, fill_cells, resolve_cell_target, table_summary

from .cap_risk_engine import CAPForm14Data, CAPForm15Data


FORM14_ANCHOR = "사고시나리오별 시설빈도"
FORM15_ANCHOR = "위험도 분석"


PASSIVE_OPTIONS = (
    "방류벽", "지하 누출 배관 설비", "지중/지하 용기", "이중벽용기", "이중배관",
    "통기관", "내화설비", "고임목", "비산방지실드", "논씰펌프", "기타",
)
ACTIVE_OPTIONS = (
    "가스감지기와 자동차단밸브의 연동", "가스감지기와 펌프의 연동", "과류방지 밸브",
    "고정식소화설비", "릴리프밸브/파열판", "방호수막/물분무", "예비펌프",
    "중앙공급장치주입구", "이탈방지안전시스템", "기타",
)


@dataclass(frozen=True)
class CAPRiskHwpxRenderResult:
    data: bytes
    applied_count: int
    warnings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.warnings


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def _section_texts(data: bytes) -> dict[str, str]:
    with ZipFile(BytesIO(data), "r") as zf:
        out: dict[str, str] = {}
        for name in zf.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            raw = zf.read(name).decode("utf-8", errors="ignore")
            texts = re.findall(
                r"<(?:[A-Za-z_][\w.-]*:)?t(?:\s[^>]*)?>(.*?)</(?:[A-Za-z_][\w.-]*:)?t>",
                raw,
                flags=re.S,
            )
            out[name] = "".join(re.sub(r"<[^>]+>", "", text) for text in texts)
        return out


def _section_for_anchor(data: bytes, anchor: str) -> str:
    target = _norm(anchor)
    hits = [path for path, text in _section_texts(data).items() if target in _norm(text)]
    if len(hits) != 1:
        raise ValueError(f"원본 HWPX에서 '{anchor}' section을 고유하게 찾지 못했습니다.")
    return hits[0]


def _section_bytes(data: bytes, section_path: str) -> bytes:
    with ZipFile(BytesIO(data), "r") as zf:
        return zf.read(section_path)


def _paragraph_text(chunk: bytes) -> str:
    text = chunk.decode("utf-8", errors="ignore")
    values = re.findall(
        r"<(?:[A-Za-z_][\w.-]*:)?t(?:\s[^>]*)?>(.*?)</(?:[A-Za-z_][\w.-]*:)?t>",
        text,
        flags=re.S,
    )
    return "".join(re.sub(r"<[^>]+>", "", value) for value in values).strip()


def _patch_scenario_placeholders(data: bytes, section_path: str, scenario: str) -> tuple[bytes, int, list[str]]:
    chunks = paragraph_chunks(_section_bytes(data, section_path))
    patches: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        text = _paragraph_text(chunk)
        n = _norm(text)
        if n == "1사고시나리오":
            patches.append({
                "section_path": section_path,
                "paragraph_index": index,
                "text": f"1) ({scenario})",
            })
        elif n == "사고시나리오":
            patches.append({
                "section_path": section_path,
                "paragraph_index": index,
                "text": f"({scenario})",
            })

    if not patches:
        return data, 0, ["별지 제14호의 사고시나리오명 자리표시자를 고유하게 찾지 못했습니다."]

    result = paragraph_patch(data, patches)
    warnings = [f"별지 제14호 사고시나리오명: {item.reason}" for item in result.skipped]
    return result.data, len(result.applied), warnings


def _resolve(
    data: bytes,
    table_anchor: str,
    labels: Sequence[str],
    *,
    directions: Sequence[str] = ("below",),
):
    section = _section_for_anchor(data, table_anchor)
    errors: list[str] = []
    for label in labels:
        for direction in directions:
            try:
                return resolve_cell_target(data, {
                    "section_path": section,
                    "table_anchor": table_anchor,
                    "cell_anchor": {"label": label, "direction": direction},
                })
            except Exception as exc:
                errors.append(f"{label}/{direction}: {exc}")
    raise ValueError(" / ".join(errors))


def _table_row_count(data: bytes, section_path: str, table_index: int) -> int:
    for item in table_summary(data):
        if item.get("sectionPath") == section_path and int(item.get("tableIndex", -1)) == table_index:
            return int(item.get("rows") or 0)
    raise ValueError("표 행 수를 확인할 수 없습니다.")


def _checkbox_text(selected_text: str, options: Sequence[str]) -> str:
    n = _norm(selected_text)
    values: list[str] = []
    for option in options:
        checked = _norm(option) in n if n else False
        values.append(f"{'☒' if checked else '☐'} {option}")
    return "  ".join(values)


def _count(value: object) -> int:
    try:
        return max(0, int(float(str(value or "0").replace(",", ""))))
    except Exception:
        return 0


def _protection_text(row: Mapping[str, Any]) -> str:
    a = _count(row.get("갑종 보호대상 수"))
    b = _count(row.get("을종 보호대상 수"))
    env = _count(row.get("환경수용체 수"))
    workers = _count(row.get("근로자수"))
    residents = _count(row.get("거주민수"))
    public_checked = a > 0 or b > 0
    return (
        f"{'☒' if public_checked else '☐'} 공공수용체 "
        f"({'☒' if a > 0 else '☐'} 갑종 ({a}개), {'☒' if b > 0 else '☐'} 을종 ({b}개))  "
        f"{'☒' if env > 0 else '☐'} 환경수용체 ({env}개)  "
        f"{'☒' if workers > 0 else '☐'} 근로자 ({workers}명)  "
        f"{'☒' if residents > 0 else '☐'} 거주민 ({residents}명)"
    )


def _fill_semantic_text(
    data: bytes,
    *,
    table_anchor: str,
    labels: Sequence[str],
    text: str,
    directions: Sequence[str] = ("below", "right"),
    max_lines: int = 8,
) -> tuple[bytes, int, list[str]]:
    if not str(text or "").strip():
        return data, 0, []
    try:
        target = _resolve(data, table_anchor, labels, directions=directions)
    except Exception as exc:
        return data, 0, [f"{table_anchor} / {'|'.join(labels)}: {exc}"]
    result = fill_cells(data, [{
        "section_path": target.section_path,
        "table_index": target.table_index,
        "row": target.logical_row,
        "col": target.logical_col,
        "text": text,
        "max_lines": max_lines,
    }], min_font_pt=6.0)
    warnings = [f"{table_anchor}: {skip.reason}" for skip in result.skipped]
    return result.data, len(result.applied), warnings


def render_form14_single_scenario(
    source: bytes,
    form14: CAPForm14Data,
    form15: CAPForm15Data | None = None,
) -> CAPRiskHwpxRenderResult:
    """Render one Form-14 official-form copy for exactly one scenario."""
    warnings: list[str] = []
    applied = 0

    if len(form14.scenario_rows) != 1:
        return CAPRiskHwpxRenderResult(
            source,
            0,
            (f"별지 제14호 원본 1부에는 사고시나리오 1건만 작성합니다. 현재 {len(form14.scenario_rows)}건입니다.",),
        )

    scenario_row = dict(form14.scenario_rows[0])
    scenario = str(scenario_row.get("사고시나리오명") or "").strip()
    events = [dict(row) for row in form14.event_rows if str(row.get("사고시나리오명") or "").strip() == scenario]
    if len(events) != 10:
        return CAPRiskHwpxRenderResult(source, 0, (f"{scenario}: 개시사건 10개 행을 확인하지 못했습니다.",))

    data = source
    try:
        section = _section_for_anchor(data, FORM14_ANCHOR)
        data, count, warn = _patch_scenario_placeholders(data, section, scenario)
        applied += count
        warnings.extend(warn)

        targets = {
            "event": _resolve(data, FORM14_ANCHOR, ("개시사건",)),
            "frequency": _resolve(data, FORM14_ANCHOR, ("빈도",)),
            "count": _resolve(data, FORM14_ANCHOR, ("개수",)),
            "accident": _resolve(data, FORM14_ANCHOR, ("사고빈도",)),
        }
        table_ids = {(t.section_path, t.table_index) for t in targets.values()}
        if len(table_ids) != 1:
            raise ValueError("개시사건/빈도/개수/사고빈도 열이 동일 표로 해석되지 않습니다.")

        fills: list[dict[str, Any]] = []
        for offset, row in enumerate(events):
            for key, value_key in (
                ("event", "개시사건"),
                ("frequency", "기준빈도(/연)"),
                ("count", "개수"),
                ("accident", "사고빈도(/연)"),
            ):
                target = targets[key]
                value = row.get(value_key)
                if value in (None, ""):
                    continue
                fills.append({
                    "section_path": target.section_path,
                    "table_index": target.table_index,
                    "row": target.logical_row + offset,
                    "col": target.logical_col,
                    "text": str(value),
                    "max_lines": 2,
                })

        accident = targets["accident"]
        row_count = _table_row_count(data, accident.section_path, accident.table_index)
        total_row = accident.logical_row + 10
        if total_row >= row_count:
            warnings.append("별지 제14호 개시사건 표에서 10개 사건 뒤 '합' 행을 확인하지 못했습니다.")
        else:
            fills.append({
                "section_path": accident.section_path,
                "table_index": accident.table_index,
                "row": total_row,
                "col": accident.logical_col,
                "text": str(scenario_row.get("시설빈도(/연)") or ""),
                "max_lines": 2,
            })

        result = fill_cells(data, fills, min_font_pt=6.0)
        data = result.data
        applied += len(result.applied)
        warnings.extend(f"별지 제14호: {skip.reason}" for skip in result.skipped)
    except Exception as exc:
        warnings.append(f"별지 제14호 개시사건 표: {exc}")

    passive = str(scenario_row.get("수동적 완화장치") or "")
    active = str(scenario_row.get("능동적 완화장치") or "")
    data, count, warn = _fill_semantic_text(
        data,
        table_anchor="안전성확보설비",
        labels=("수동적 완화장치 종류",),
        text=_checkbox_text(passive, PASSIVE_OPTIONS),
    )
    applied += count
    warnings.extend(warn)
    data, count, warn = _fill_semantic_text(
        data,
        table_anchor="안전성확보설비",
        labels=("능동적 완화장치의 종류", "능동적 완화장치 종류"),
        text=_checkbox_text(active, ACTIVE_OPTIONS),
    )
    applied += count
    warnings.extend(warn)

    impact = None
    if form15 is not None:
        impact = next(
            (row for row in form15.scenario_rows if str(row.get("사고시나리오 명") or "").strip() == scenario),
            None,
        )
    if impact is None:
        warnings.append(f"{scenario}: 별지 제14호 보호대상 명세에 사용할 영향평가 행을 찾지 못했습니다.")
    else:
        data, count, warn = _fill_semantic_text(
            data,
            table_anchor="보호대상 명세",
            labels=("보호대상 포함 여부",),
            text=_protection_text(impact),
            max_lines=6,
        )
        applied += count
        warnings.extend(warn)

    return CAPRiskHwpxRenderResult(data, applied, tuple(dict.fromkeys(warnings)))


def _ensure_scenario_rows(
    source: bytes,
    *,
    required_rows: int,
) -> tuple[bytes, int, list[str]]:
    if required_rows <= 0:
        return source, 0, []
    try:
        target = _resolve(source, FORM15_ANCHOR, ("사고시나리오 명", "사고시나리오명"))
        row_count = _table_row_count(source, target.section_path, target.table_index)
        capacity = max(0, row_count - target.logical_row)
        if required_rows <= capacity:
            return source, 0, []
        if capacity < 1:
            raise ValueError("복제할 기존 사고시나리오 입력행이 없습니다.")

        result = apply_table_ops(source, [{
            "op": "insert_row_by_clone",
            "section_path": target.section_path,
            "table_index": target.table_index,
            "ref_row": row_count - 1,
            "count": required_rows - capacity,
        }])
        warnings = [f"별지 제15호 행 확장: {skip.reason}" for skip in result.skipped]
        return result.data, len(result.transcript), warnings
    except Exception as exc:
        return source, 0, [f"별지 제15호 사고시나리오 행 확장: {exc}"]


def render_form15_risk(source: bytes, form15: CAPForm15Data) -> CAPRiskHwpxRenderResult:
    warnings: list[str] = []
    applied = 0
    if form15.no_offsite_scenario:
        return CAPRiskHwpxRenderResult(source, 0, ())

    data, count, warn = _ensure_scenario_rows(source, required_rows=len(form15.scenario_rows))
    applied += count
    warnings.extend(warn)

    try:
        targets = {
            "name": _resolve(data, FORM15_ANCHOR, ("사고시나리오 명", "사고시나리오명")),
            "freq": _resolve(data, FORM15_ANCHOR, ("사고시나리오 시설빈도", "사고시나리오 시설 빈도")),
            "distance": _resolve(data, FORM15_ANCHOR, ("사고시나리오 거리(장외)", "사고시나리오 거리")),
            "people": _resolve(data, FORM15_ANCHOR, ("주민수", "주민 수")),
        }
        table_ids = {(t.section_path, t.table_index) for t in targets.values()}
        if len(table_ids) != 1:
            raise ValueError("위험도 판단요소 열이 동일 표로 해석되지 않습니다.")

        fills: list[dict[str, Any]] = []
        for offset, row in enumerate(form15.scenario_rows):
            values = {
                "name": row.get("사고시나리오 명"),
                "freq": row.get("사고시나리오 시설빈도"),
                "distance": row.get("사고시나리오 거리(장외)"),
                "people": row.get("위험도 주민수"),
            }
            for key, value in values.items():
                if value in (None, ""):
                    continue
                target = targets[key]
                fills.append({
                    "section_path": target.section_path,
                    "table_index": target.table_index,
                    "row": target.logical_row + offset,
                    "col": target.logical_col,
                    "text": str(value),
                    "max_lines": 3,
                })
        result = fill_cells(data, fills, min_font_pt=6.0)
        data = result.data
        applied += len(result.applied)
        warnings.extend(f"별지 제15호 판단요소표: {skip.reason}" for skip in result.skipped)
    except Exception as exc:
        warnings.append(f"별지 제15호 판단요소표: {exc}")

    total_labels = (
        ("사고시나리오 총 개수(A)", ("사고시나리오 총 개수 (A)", "사고시나리오 총 개수(A)"),
         "사고시나리오 총 개수(A)", "사고시나리오 개수 구간점수"),
        ("사고시나리오 시설빈도의 합(B)", ("사고시나리오 시설 빈도의 합 (B)", "사고시나리오 시설빈도의 합(B)"),
         "사고시나리오 시설빈도의 합(B)", "시설빈도 구간점수"),
        ("사고시나리오 거리의 합(C)", ("사고시나리오 거리의 합(C)", "사고시나리오 거리의 합 (C)"),
         "사고시나리오 거리의 합(C)", "거리 구간점수"),
        ("주민수 합(D)", ("주민수 합 (D)", "주민수 합(D)"),
         "주민수 합(D)", "주민수 구간점수"),
    )
    for display, labels, total_key, score_key in total_labels:
        try:
            target = _resolve(data, FORM15_ANCHOR, labels)
            row_count = _table_row_count(data, target.section_path, target.table_index)
            if target.logical_row + 1 >= row_count:
                raise ValueError("계/구간점수 2개 행을 확인하지 못했습니다.")
            fills = [
                {
                    "section_path": target.section_path,
                    "table_index": target.table_index,
                    "row": target.logical_row,
                    "col": target.logical_col,
                    "text": str(form15.totals.get(total_key, "")),
                    "max_lines": 2,
                },
                {
                    "section_path": target.section_path,
                    "table_index": target.table_index,
                    "row": target.logical_row + 1,
                    "col": target.logical_col,
                    "text": str(form15.scores.get(score_key, "")),
                    "max_lines": 2,
                },
            ]
            result = fill_cells(data, fills, min_font_pt=6.0)
            data = result.data
            applied += len(result.applied)
            warnings.extend(f"별지 제15호 {display}: {skip.reason}" for skip in result.skipped)
        except Exception as exc:
            warnings.append(f"별지 제15호 {display}: {exc}")

    for labels, score_key in (
        (("사고빈도점수(A+B)", "사고빈도점수 (A+B)"), "사고빈도점수(A+B)"),
        (("사고영향점수(C+D)", "사고영향점수 (C+D)"), "사고영향점수(C+D)"),
    ):
        data, count, warn = _fill_semantic_text(
            data,
            table_anchor=FORM15_ANCHOR,
            labels=labels,
            text=str(form15.scores.get(score_key, "")),
            directions=("below", "right"),
            max_lines=2,
        )
        applied += count
        warnings.extend(warn)

    return CAPRiskHwpxRenderResult(data, applied, tuple(dict.fromkeys(warnings)))
