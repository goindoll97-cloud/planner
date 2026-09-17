from __future__ import annotations

"""Fill the official CAP annex HWPX without redrawing its layout.

The legal form file itself is the presentation template. The engine changes
only cells that can be addressed deterministically by a form title and a cell
label. Ambiguous/missing labels are never guessed. Structured rows are filled
only where the official template already contains blank rows; a shortage is
reported for human review instead of rebuilding the table.
"""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
import platform
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from zipfile import BadZipFile, ZipFile

from hwpx.table_patch import fill_cells, resolve_cell_target

from ..law_attachment_archive import approved_source_files, approved_source_is_current
from .project import CONFIRMED_STATUSES, EvidenceRef, Stage2Project


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "data" / "stage2" / "cap_hwpx_template_policy.json"
TEMPLATE_FIELD_KEY = "reference.cap.official_hwpx_template"
CAP_LAW_SOURCE_KEY = "CAP_DRAFT"


@dataclass(frozen=True)
class CAPTemplateValidation:
    ok: bool
    sha256: str
    found_markers: tuple[str, ...]
    missing_markers: tuple[str, ...]
    section_paths: tuple[str, ...]


@dataclass(frozen=True)
class CAPHwpxBuildResult:
    data: bytes
    applied_count: int
    warnings: tuple[str, ...]
    template_sha256: str


def _policy() -> dict[str, Any]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "cap-hwpx-template-policy-v1":
        raise ValueError("CAP HWPX template policy schema mismatch")
    return payload


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def _hwpx_text_by_section(data: bytes) -> dict[str, str]:
    try:
        with ZipFile(BytesIO(data), "r") as zf:
            names = [name for name in zf.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)]
            if not names:
                raise ValueError("HWPX 본문 section XML을 찾을 수 없습니다.")
            out: dict[str, str] = {}
            for name in sorted(names):
                raw = zf.read(name).decode("utf-8", errors="ignore")
                texts = re.findall(r"<(?:[A-Za-z_][\w.-]*:)?t(?:\s[^>]*)?>(.*?)</(?:[A-Za-z_][\w.-]*:)?t>", raw, flags=re.S)
                clean = "".join(re.sub(r"<[^>]+>", "", value) for value in texts)
                out[name] = clean
            return out
    except BadZipFile as exc:
        raise ValueError("유효한 HWPX 패키지가 아닙니다.") from exc


def validate_cap_hwpx_template(data: bytes) -> CAPTemplateValidation:
    policy = _policy()
    section_text = _hwpx_text_by_section(data)
    whole = _norm("\n".join(section_text.values()))
    required = tuple(str(v) for v in policy.get("required_form_markers", []))
    found = tuple(marker for marker in required if _norm(marker) in whole)
    missing = tuple(marker for marker in required if marker not in found)
    return CAPTemplateValidation(
        ok=not missing,
        sha256=sha256(data).hexdigest(),
        found_markers=found,
        missing_markers=missing,
        section_paths=tuple(section_text),
    )


def convert_hwp_to_hwpx(file_bytes: bytes, file_name: str) -> bytes:
    """Convert legacy HWP with local Hancom Office through pyhwpx.

    This path is intentionally optional and Windows-only. The preferred input
    is the National Law Information Center's original HWPX.
    """
    if platform.system() != "Windows":
        raise RuntimeError("HWP 원본 변환은 Windows + 한컴오피스 환경에서만 지원합니다. 가능하면 법제처 HWPX 원본을 사용해 주세요.")
    try:
        from pyhwpx import Hwp  # type: ignore
    except Exception as exc:  # pragma: no cover - Windows-only optional path
        raise RuntimeError("HWP 변환을 위해 pyhwpx와 한컴오피스가 필요합니다.") from exc

    suffix = Path(file_name).suffix.lower()
    if suffix != ".hwp":
        raise ValueError("HWP 변환에는 .hwp 파일만 사용할 수 있습니다.")

    with tempfile.TemporaryDirectory(prefix="cap_hwp_convert_") as tmp:
        src = Path(tmp) / "official_form.hwp"
        dst = Path(tmp) / "official_form.hwpx"
        src.write_bytes(file_bytes)
        hwp = None
        # pyhwpx prints its FilePathCheckerModule DLL path during COM setup.
        # It is diagnostic noise, not a user prompt or AI message.
        sink = StringIO()
        try:  # pragma: no cover - requires Hancom COM
            with redirect_stdout(sink), redirect_stderr(sink):
                try:
                    hwp = Hwp(visible=False)
                except TypeError:
                    hwp = Hwp()
                hwp.open(str(src))
                hwp.save_as(str(dst))
        finally:
            if hwp is not None:
                try:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        hwp.quit()
                except Exception:
                    pass
        if not dst.exists() or dst.stat().st_size == 0:
            raise RuntimeError("한컴오피스에서 HWP→HWPX 변환 결과를 만들지 못했습니다.")
        return dst.read_bytes()


def normalize_cap_template_upload(file_name: str, file_bytes: bytes) -> tuple[bytes, str]:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".hwpx":
        data = file_bytes
        source_format = "HWPX"
    elif suffix == ".hwp":
        data = convert_hwp_to_hwpx(file_bytes, file_name)
        source_format = "HWP→HWPX"
    else:
        raise ValueError("법제처 원본서식은 .hwpx 또는 .hwp 파일만 사용할 수 있습니다.")
    validation = validate_cap_hwpx_template(data)
    if not validation.ok:
        missing = ", ".join(validation.missing_markers[:6])
        raise ValueError(f"현재 CAP 별지서식 원본으로 확인되지 않습니다. 누락 표식: {missing}")
    return data, source_format


def register_cap_template(
    project: Stage2Project,
    *,
    evidence: EvidenceRef,
    hwpx_bytes: bytes,
    source_format: str,
) -> CAPTemplateValidation:
    validation = validate_cap_hwpx_template(hwpx_bytes)
    if not validation.ok:
        raise ValueError("필수 CAP 별지서식이 모두 포함된 법제처 원본 HWPX가 아닙니다.")
    project.set_field(
        TEMPLATE_FIELD_KEY,
        "화학사고예방관리계획서 법제처 원본 HWPX 서식",
        {
            "file_name": evidence.source_name,
            "stored_path": evidence.location,
            "sha256": validation.sha256,
            "source_format": source_format,
            "form_markers": list(validation.found_markers),
            "template_source": "PROJECT_UPLOAD",
        },
        "USER_CONFIRMED",
        evidence=[evidence],
        note=(
            "법정 결과물의 레이아웃 기준. 프로그램이 표를 새로 그리지 않고 이 HWPX의 기존 셀/서식을 채운다. "
            "내용 근거는 현행 규정·NICS-GP2026-8·회사 확인자료를 따른다."
        ),
    )
    return validation


def _approved_current_cap_template_meta() -> Mapping[str, Any] | None:
    """Resolve the current approved law.go.kr CAP form attachment.

    The automatic source is available only when the latest law monitor result is
    CURRENT. An UPDATE_PENDING/UNVERIFIED source therefore cannot silently feed
    a stale statutory form into report generation.
    """
    hwpx_files = approved_source_files(CAP_LAW_SOURCE_KEY, {".hwpx"}, require_current=True)
    valid_hwpx: list[tuple[Path, CAPTemplateValidation]] = []
    for path in hwpx_files:
        try:
            validation = validate_cap_hwpx_template(path.read_bytes())
        except Exception:
            continue
        if validation.ok:
            valid_hwpx.append((path, validation))
    if len(valid_hwpx) == 1:
        path, validation = valid_hwpx[0]
        return {
            "file_name": path.name,
            "stored_path": str(path),
            "sha256": validation.sha256,
            "source_format": "법제처 자동동기화 HWPX",
            "form_markers": list(validation.found_markers),
            "template_source": "APPROVED_LAW_ARCHIVE",
        }
    if len(valid_hwpx) > 1:
        return None

    # Legacy HWP cannot be structurally validated without Hancom conversion, but
    # a single CURRENT approved HWP can be offered on Windows and is validated
    # immediately after conversion in load_registered_cap_template_bytes().
    hwp_files = approved_source_files(CAP_LAW_SOURCE_KEY, {".hwp"}, require_current=True)
    if len(hwp_files) == 1 and platform.system() == "Windows":
        path = hwp_files[0]
        return {
            "file_name": path.name,
            "stored_path": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "source_format": "법제처 자동동기화 HWP→HWPX",
            "form_markers": [],
            "template_source": "APPROVED_LAW_ARCHIVE",
        }
    return None


def registered_cap_template(project: Stage2Project) -> Mapping[str, Any] | None:
    """Resolve the CAP layout template, preferring the CURRENT approved form.

    The CURRENT approved law.go.kr CAP template is the layout authority. A
    project-uploaded official template is allowed only as a fallback while the
    central CAP legal source is not CURRENT. Once law.go.kr has been refreshed
    and approved as CURRENT, an older project copy must never silently
    reappear merely because the new official HWP/HWPX cannot be mapped by the
    current template engine — report generation fails closed (returns None)
    until the new form mapping is supported.
    """
    current = _approved_current_cap_template_meta()
    if current is not None:
        return current
    if approved_source_is_current(CAP_LAW_SOURCE_KEY):
        return None

    rec = project.get_field(TEMPLATE_FIELD_KEY)
    if rec is not None and isinstance(rec.value, Mapping):
        return rec.value
    return None


def load_registered_cap_template_bytes(project: Stage2Project) -> bytes:
    meta = registered_cap_template(project)
    if not meta:
        raise FileNotFoundError(
            "현재 승인된 법제처 CAP HWPX 원본을 찾지 못했습니다. 법령 최신성 확인·첨부원본 승인 상태를 확인하거나 원본서식을 직접 등록해 주세요."
        )
    path = Path(str(meta.get("stored_path") or ""))
    if not path.exists():
        raise FileNotFoundError("등록 또는 자동동기화된 CAP 원본 파일을 찾을 수 없습니다.")
    raw = path.read_bytes()
    expected = str(meta.get("sha256") or "")
    if expected and sha256(raw).hexdigest() != expected:
        raise ValueError("CAP 법정서식 원본의 해시가 승인 당시 값과 달라졌습니다. 사용을 중단합니다.")

    if path.suffix.lower() == ".hwp":
        data = convert_hwp_to_hwpx(raw, path.name)
    else:
        data = raw
    validation = validate_cap_hwpx_template(data)
    if not validation.ok:
        raise ValueError("현재 승인된 CAP 첨부원본이 필요한 별지서식 구조 검증을 통과하지 못했습니다.")
    return data


def _confirmed_value(project: Stage2Project, *keys: str) -> str:
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        value = rec.value
        if value in (None, "", [], {}):
            continue
        return str(value)
    return ""


def _confirmed_rows(project: Stage2Project, *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        if isinstance(rec.value, list):
            rows = [dict(row) for row in rec.value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def _row_value(row: Mapping[str, object], *aliases: str) -> str:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, ""):
            return str(value)
    return ""


def _section_for_anchor(data: bytes, anchor: str) -> str:
    by_section = _hwpx_text_by_section(data)
    target = _norm(anchor)
    hits = [path for path, text in by_section.items() if target in _norm(text)]
    if len(hits) != 1:
        raise ValueError(f"원본 HWPX에서 서식 제목 '{anchor}'의 section을 고유하게 찾지 못했습니다.")
    return hits[0]


def _fill_scalar_batch(source: bytes, specs: Sequence[tuple[str, str, str]]) -> tuple[bytes, int, list[str]]:
    cells: list[dict[str, Any]] = []
    warnings: list[str] = []
    for table_anchor, label, value in specs:
        if not str(value or "").strip():
            continue
        try:
            section = _section_for_anchor(source, table_anchor)
        except Exception as exc:
            warnings.append(str(exc))
            continue
        cells.append({
            "section_path": section,
            "table_anchor": table_anchor,
            "cell_anchor": {"label": label, "direction": "right"},
            "text": str(value),
            "max_lines": 4,
        })
    if not cells:
        return source, 0, warnings
    result = fill_cells(source, cells, min_font_pt=7.0)
    warnings.extend(skip.reason for skip in result.skipped)
    return result.data, len(result.applied), warnings


def _resolve_down(source: bytes, table_anchor: str, header: str):
    section = _section_for_anchor(source, table_anchor)
    return resolve_cell_target(source, {
        "section_path": section,
        "table_anchor": table_anchor,
        "cell_anchor": {"label": header, "direction": "down"},
    })


def _fill_structured_table(
    source: bytes,
    *,
    table_anchor: str,
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[tuple[str, Sequence[str]]],
) -> tuple[bytes, int, list[str]]:
    if not rows:
        return source, 0, []
    warnings: list[str] = []
    targets = []
    for header, _aliases in columns:
        try:
            targets.append((header, _resolve_down(source, table_anchor, header)))
        except Exception as exc:
            warnings.append(f"{table_anchor} / {header}: {exc}")
            return source, 0, warnings

    fills: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        for (header, aliases), (_resolved_header, target) in zip(columns, targets):
            value = str(offset + 1) if aliases == ("__rowno__",) else _row_value(row, *aliases)
            if not value:
                continue
            fills.append({
                "section_path": target.section_path,
                "table_index": target.table_index,
                "row": target.logical_row + offset,
                "col": target.logical_col,
                "text": value,
                "max_lines": 3,
            })
    if not fills:
        return source, 0, warnings
    result = fill_cells(source, fills, min_font_pt=6.5)
    if result.skipped:
        warnings.extend(
            f"{table_anchor}: {skip.reason} (row={skip.row}, col={skip.col})"
            for skip in result.skipped
        )
    return result.data, len(result.applied), warnings


def _facility_count_text(project: Stage2Project) -> str:
    rows = _confirmed_rows(project, "inventory.facilities", "cap.facility.equipment_specs")
    counts: dict[str, int] = {}
    for row in rows:
        name = _row_value(row, "설비종류", "설비형태", "장치·설비 종류")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return " / ".join(f"{name} {count}기" for name, count in counts.items())


def build_cap_hwpx_draft(project: Stage2Project, template_bytes: bytes | None = None) -> CAPHwpxBuildResult:
    if not project.cap_in_scope:
        raise ValueError("화학사고예방관리계획서가 현재 작성범위에 포함되어 있지 않습니다.")
    source = template_bytes if template_bytes is not None else load_registered_cap_template_bytes(project)
    validation = validate_cap_hwpx_template(source)
    if not validation.ok:
        raise ValueError("사용 중인 HWPX가 현재 CAP 별지 원본서식 검증을 통과하지 못했습니다.")

    applied = 0
    warnings: list[str] = []
    level = project.cap_group
    scalar_specs = [
        ("사업장 일반정보", "사업장명", project.company_name),
        ("사업장 일반정보", "단위공장명", project.site_name),
        ("사업장 일반정보", "사업자 등록번호", _confirmed_value(project, "cap.business.registration_no", "business.registration_no")),
        ("사업장 일반정보", "대표자", _confirmed_value(project, "cap.business.representative", "business.representative")),
        ("사업장 일반정보", "우편번호/주소", _confirmed_value(project, "business.address")),
        ("사업장 일반정보", "산업단지", _confirmed_value(project, "cap.business.industrial_complex")),
        ("사업장 일반정보", "대표전화", _confirmed_value(project, "cap.business.contact")),
        ("사업장 일반정보", "제출구분", _confirmed_value(project, "cap.business.submission_type")),
        ("사업장 일반정보", "작성수준", f"{'■' if level == '1군' else '□'} 1군   {'■' if level == '2군' else '□'} 2군"),
        ("사업장 일반정보", "공동비상대응계획 수립 여부", _confirmed_value(project, "cap.business.joint_emergency_plan")),
        ("사업장 일반정보", "유사제도 심사결과 활용", _confirmed_value(project, "cap.business.other_system_review")),
        ("사업장 일반정보", "총괄영향범위내 주민여부", _confirmed_value(project, "cap.business.residents_in_overall_range")),
        ("사업장 일반정보", "최근 3년간 화학사고 발생 여부", _confirmed_value(project, "cap.business.recent_accident")),
        ("사업장 일반정보", "화학사고예방관리계획서 작성자", _confirmed_value(project, "cap.business.writer_info")),
        ("사업장 일반정보", "담당자 연락처", _confirmed_value(project, "cap.business.writer_contact")),
        ("사업장 일반정보", "담당자 메일주소", _confirmed_value(project, "cap.business.writer_email")),
        ("총괄 취급시설 개요", "단위공장 구성", _confirmed_value(project, "cap.basic.total_facility_overview")),
        ("총괄 취급시설 개요", "공정개요", _confirmed_value(project, "process.description")),
        ("총괄 취급시설 개요", "장치·설비 종류 및 수량", _facility_count_text(project)),
        ("총괄 취급시설 개요", "입·출하 및 운반시설", _confirmed_value(project, "cap.basic.loading_transport")),
        ("세부 취급시설 개요", "단위공장 구성", _confirmed_value(project, "cap.basic.unit_facility_overview")),
        ("세부 취급시설 개요", "공정개요", _confirmed_value(project, "process.description")),
        ("세부 취급시설 개요", "장치·설비 종류 및 수량", _facility_count_text(project)),
        ("세부 취급시설 개요", "입·출하 및 운반시설", _confirmed_value(project, "cap.basic.loading_transport")),
    ]
    source, count, warn = _fill_scalar_batch(source, scalar_specs)
    applied += count
    warnings.extend(warn)

    chemicals = _confirmed_rows(project, "cap.chemical.details", "inventory.chemicals")
    source, count, warn = _fill_structured_table(
        source,
        table_anchor="유해화학물질 목록 및 명세",
        rows=chemicals,
        columns=(
            ("연번", ("__rowno__",)),
            ("유해화학물질명", ("물질명", "유해화학물질명")),
            ("물질구분", ("물질구분",)),
            ("화학물질식별번호", ("CAS 번호", "CAS No.", "화학물질식별번호")),
            ("고유번호", ("고유번호",)),
            ("물질상태", ("물질상태", "물리적 상태")),
            ("함량(%)", ("함량(%)", "함량")),
            ("비중", ("비중",)),
            ("하한", ("폭발한계 하한", "폭발하한")),
            ("상한", ("폭발한계 상한", "폭발상한")),
            ("항목", ("독성구분 항목", "독성구분-항목")),
            ("구분", ("독성구분", "독성구분-구분")),
            ("위험노출수준", ("위험노출수준", "ERPG", "AEGL", "PAC", "IDLH")),
            ("허용농도값", ("허용농도값", "TWA", "노출기준")),
            ("증기압", ("증기압", "증기압(20℃, mmHg)")),
            ("부식성", ("부식성", "부식성(유, 무)")),
        ),
    )
    applied += count
    warnings.extend(warn)

    facilities = _confirmed_rows(project, "cap.facility.equipment_specs", "inventory.facilities")
    source, count, warn = _fill_structured_table(
        source,
        table_anchor="장치 설비 목록 및 명세",
        rows=facilities,
        columns=(
            ("연번", ("__rowno__",)),
            ("구분기호", ("설비번호", "구분기호", "장치번호")),
            ("장치·설비명", ("설비명", "장치·설비명", "장치명")),
            ("취급물질", ("취급물질", "물질명")),
            ("물질상태", ("물질상태", "물리적 상태")),
            ("함량(%)", ("함량(%)", "함량")),
            ("연결구 크기", ("연결구 크기", "호칭경")),
            ("설계", ("설계압력",)),
            ("운전", ("운전압력",)),
            ("설계용량", ("설계용량", "용량")),
            ("취급량", ("취급량", "최대보유량", "최대보유량(kg)")),
            ("비고", ("비고", "P&ID 번호", "PFD 도면번호")),
        ),
    )
    applied += count
    warnings.extend(warn)

    dikes = _confirmed_rows(project, "cap.safety.dike_layout")
    source, count, warn = _fill_structured_table(
        source,
        table_anchor="확산방지설비 현황",
        rows=dikes,
        columns=(
            ("연번", ("__rowno__",)),
            ("설비형태", ("설비형태",)),
            ("구분기호", ("구분기호", "설비번호")),
            ("장치·설비명", ("장치·설비명", "설비명")),
            ("설계용량", ("설계용량",)),
            ("설비종류", ("설비종류",)),
            ("필요용량", ("필요용량",)),
            ("유효용량", ("유효용량",)),
            ("검토결과", ("검토결과",)),
            ("비고", ("비고",)),
        ),
    )
    applied += count
    warnings.extend(warn)

    detectors = _confirmed_rows(project, "cap.safety.gas_detection", "psm.psi.gas_detection")
    source, count, warn = _fill_structured_table(
        source,
        table_anchor="고정식 유해감지시설 명세",
        rows=detectors,
        columns=(
            ("연번", ("__rowno__",)),
            ("구분 기호", ("감지기 번호", "감지기번호", "구분기호")),
            ("감지대상", ("검출대상 물질", "감지대상")),
            ("설치위치", ("설치위치", "설치장소")),
            ("작동시간", ("작동시간",)),
            ("측정방식", ("감지방식", "측정방식")),
            ("경보 설정값", ("경보 설정값", "경보설정값")),
            ("경보기 설치장소", ("경보 위치", "경보기 설치장소")),
            ("연동여부", ("연동여부",)),
            ("정밀도", ("정밀도",)),
            ("유지관리", ("유지관리", "점검주기")),
            ("비고", ("비고", "관련 도면번호")),
        ),
    )
    applied += count
    warnings.extend(warn)

    freq_rows = _confirmed_rows(project, "cap.offsite.scenario_frequency")
    source, count, warn = _fill_structured_table(
        source,
        table_anchor="사고시나리오별 시설빈도",
        rows=freq_rows,
        columns=(
            ("연번", ("__rowno__",)),
            ("개시사건", ("개시사건",)),
            ("빈도", ("빈도",)),
            ("개수", ("개수",)),
            ("사고빈도", ("사고빈도",)),
        ),
    )
    applied += count
    warnings.extend(warn)

    risk_rows = _confirmed_rows(project, "cap.offsite.risk_analysis")
    source, count, warn = _fill_structured_table(
        source,
        table_anchor="위험도 분석",
        rows=risk_rows,
        columns=(
            ("연번", ("__rowno__",)),
            ("사고시나리오 명", ("사고시나리오 명", "사고시나리오")),
            ("사고시나리오 시설빈도", ("사고시나리오 시설빈도", "시설빈도")),
            ("사고시나리오 거리", ("사고시나리오 거리", "거리")),
            ("주민수", ("주민수", "주민 수")),
        ),
    )
    applied += count
    warnings.extend(warn)

    warnings = list(dict.fromkeys(warnings))
    return CAPHwpxBuildResult(
        data=source,
        applied_count=applied,
        warnings=tuple(warnings),
        template_sha256=validation.sha256,
    )


def cap_hwpx_filename(project: Stage2Project) -> str:
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", project.company_name or project.project_id).strip("._")
    return f"{safe}_화학사고예방관리계획서_법정원본서식_작성본.hwpx"
