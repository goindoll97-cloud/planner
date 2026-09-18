from __future__ import annotations

"""Runtime support for CAP official forms that law.go.kr publishes as many files.

The legal archive may contain one HWP/HWPX per appendix/form instead of one
monolithic HWPX that contains every CAP form.  Stage 5 must not report that the
official source is missing merely because the current source is split across
several approved files.

This module keeps the existing fail-closed rules:
- only the CURRENT approved CAP_DRAFT source is considered;
- official files are never redrawn or merged into a new synthetic legal form;
- each original form is filled independently and returned in one ZIP package;
- incomplete coverage, failed HWP conversion, or unrecognised forms stay HOLD.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import platform
import re
from threading import RLock
from typing import Any, Mapping, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

from ..law_attachment_archive import approved_source_files, approved_source_is_current
from . import cap_hwpx
from .cap_risk_engine import build_cap_form14_data, build_cap_form15_data
from .cap_risk_hwpx import render_form14_single_scenario, render_form15_risk


WRAPPER_MARKER = "_cap_multi_form_runtime_wrapper"
CACHE_DIR = cap_hwpx.PROJECT_ROOT / "data" / "runtime" / "cap_hwpx_converted"
BUNDLE_SOURCE = "APPROVED_LAW_ARCHIVE_BUNDLE"
BUNDLE_INCOMPLETE_SOURCE = "APPROVED_LAW_ARCHIVE_BUNDLE_INCOMPLETE"
_VALIDATION_LOCK = RLock()
_PARTIAL_VALIDATION_ALLOWED: ContextVar[bool] = ContextVar(
    "cap_multi_form_partial_validation_allowed",
    default=False,
)


@dataclass(frozen=True)
class CAPOfficialForm:
    path: Path
    hwpx_data: bytes
    markers: tuple[str, ...]
    source_sha256: str
    source_format: str


@dataclass(frozen=True)
class CAPRiskRendererPreflight:
    ready: bool
    blockers: tuple[str, ...]
    messages: tuple[str, ...]


@dataclass(frozen=True)
class CAPOfficialFormBundle:
    status: str
    forms: tuple[CAPOfficialForm, ...]
    required_markers: tuple[str, ...]
    found_markers: tuple[str, ...]
    missing_markers: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "READY" and bool(self.forms) and not self.missing_markers


def _required_markers() -> tuple[str, ...]:
    return tuple(str(v) for v in cap_hwpx._policy().get("required_form_markers", []))


def _safe_name(value: str, fallback: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", str(value or "")).strip("._")
    return text[:140] or fallback


def _converted_hwp_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{digest}.hwpx"
    if cached.exists() and cached.stat().st_size > 0:
        data = cached.read_bytes()
        # Never trust a stale/corrupt derived cache merely because the file exists.
        cap_hwpx._hwpx_text_by_section(data)
        return data

    data = cap_hwpx.convert_hwp_to_hwpx(raw, path.name)
    cap_hwpx._hwpx_text_by_section(data)
    cached.write_bytes(data)
    return data


def _load_form(path: Path) -> CAPOfficialForm:
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        data = raw
        source_format = "법제처 자동동기화 HWPX"
    elif suffix == ".hwp":
        if platform.system() != "Windows":
            raise RuntimeError(
                f"{path.name}: 법제처 HWP 원본은 확인했지만 HWPX 자동작성에는 Windows + 한컴오피스가 필요합니다."
            )
        data = _converted_hwp_bytes(path)
        source_format = "법제처 자동동기화 HWP→HWPX"
    else:
        raise ValueError(f"지원하지 않는 CAP 공식서식 형식입니다: {path.name}")

    validation = cap_hwpx.validate_cap_hwpx_template(data)
    if not validation.found_markers:
        raise ValueError(f"{path.name}: CAP 별지서식 표식을 찾지 못했습니다.")
    return CAPOfficialForm(
        path=path,
        hwpx_data=data,
        markers=tuple(validation.found_markers),
        source_sha256=digest,
        source_format=source_format,
    )


def _select_cover(forms: Sequence[CAPOfficialForm], required: Sequence[str]) -> tuple[CAPOfficialForm, ...]:
    """Pick the smallest practical set that covers the required official forms."""
    remaining = set(required)
    selected: list[CAPOfficialForm] = []
    pool = list(forms)
    while remaining:
        ranked = sorted(
            pool,
            key=lambda form: (
                len(remaining.intersection(form.markers)),
                1 if form.path.suffix.lower() == ".hwpx" else 0,
                len(form.markers),
                form.path.name,
            ),
            reverse=True,
        )
        if not ranked:
            break
        best = ranked[0]
        covered = remaining.intersection(best.markers)
        if not covered:
            break
        selected.append(best)
        remaining.difference_update(covered)
        pool.remove(best)
    return tuple(selected)


def resolve_current_cap_form_bundle() -> CAPOfficialFormBundle:
    required = _required_markers()
    if not approved_source_is_current(cap_hwpx.CAP_LAW_SOURCE_KEY):
        return CAPOfficialFormBundle(
            status="NOT_CURRENT",
            forms=(),
            required_markers=required,
            found_markers=(),
            missing_markers=required,
            issues=("법제처 CAP 작성규정 최신 승인본이 아직 CURRENT 상태가 아닙니다.",),
        )

    paths = approved_source_files(
        cap_hwpx.CAP_LAW_SOURCE_KEY,
        {".hwpx", ".hwp"},
        require_current=True,
    )
    if not paths:
        return CAPOfficialFormBundle(
            status="UNAVAILABLE",
            forms=(),
            required_markers=required,
            found_markers=(),
            missing_markers=required,
            issues=("최신 승인 원본은 확인되었지만 HWP/HWPX 별지서식 파일을 찾지 못했습니다.",),
        )

    loaded: list[CAPOfficialForm] = []
    issues: list[str] = []
    seen_payloads: set[str] = set()
    for path in sorted(paths, key=lambda item: item.name):
        try:
            form = _load_form(path)
        except Exception as exc:
            issues.append(f"{type(exc).__name__}: {exc}")
            continue
        payload_digest = sha256(form.hwpx_data).hexdigest()
        if payload_digest in seen_payloads:
            continue
        seen_payloads.add(payload_digest)
        loaded.append(form)

    found_set = {marker for form in loaded for marker in form.markers}
    missing = tuple(marker for marker in required if marker not in found_set)
    selected = _select_cover(loaded, required)
    if missing:
        return CAPOfficialFormBundle(
            status="INCOMPLETE",
            forms=tuple(loaded),
            required_markers=required,
            found_markers=tuple(marker for marker in required if marker in found_set),
            missing_markers=missing,
            issues=tuple(issues),
        )

    return CAPOfficialFormBundle(
        status="READY",
        forms=selected,
        required_markers=required,
        found_markers=required,
        missing_markers=(),
        issues=tuple(issues),
    )


def _bundle_meta(bundle: CAPOfficialFormBundle) -> Mapping[str, Any]:
    source = BUNDLE_SOURCE if bundle.ready else BUNDLE_INCOMPLETE_SOURCE
    return {
        "file_name": f"법제처 공식 CAP 별지서식 {len(bundle.forms)}개",
        "stored_path": "",
        "sha256": "",
        "source_format": "법제처 자동동기화 공식 별지서식 묶음",
        "form_markers": list(bundle.found_markers),
        "missing_form_markers": list(bundle.missing_markers),
        "template_source": source,
        "bundle_files": [str(form.path) for form in bundle.forms],
        "bundle_status": bundle.status,
        "bundle_issues": list(bundle.issues),
    }


def _relaxed_validation(strict_validate, data: bytes):
    validation = strict_validate(data)
    if validation.found_markers:
        return cap_hwpx.CAPTemplateValidation(
            ok=True,
            sha256=validation.sha256,
            found_markers=validation.found_markers,
            missing_markers=validation.missing_markers,
            section_paths=validation.section_paths,
        )
    return validation


def _partial_builder(original_build):
    """Relax validation only inside one approved split-form build context.

    ``cap_hwpx.build_cap_hwpx_draft`` resolves ``validate_cap_hwpx_template``
    from the module at call time, so the split-form path still needs a temporary
    wrapper there.  The wrapper is context-local: only the thread/task that set
    ``_PARTIAL_VALIDATION_ALLOWED`` sees partial-form validation as acceptable.
    Any concurrent Streamlit session sees the same temporary wrapper but its
    ContextVar remains false, so it still executes the captured strict validator.
    The module binding is restored in ``finally`` for compatibility with callers
    that expect the ordinary validator object outside the split-form call.
    """

    def build_partial(project, template_bytes: bytes | None = None):
        if template_bytes is None:
            return original_build(project)
        with _VALIDATION_LOCK:
            current = cap_hwpx.validate_cap_hwpx_template
            token = _PARTIAL_VALIDATION_ALLOWED.set(True)

            def contextual_validate(data: bytes):
                if not _PARTIAL_VALIDATION_ALLOWED.get():
                    return current(data)
                return _relaxed_validation(current, data)

            cap_hwpx.validate_cap_hwpx_template = contextual_validate
            try:
                return original_build(project, template_bytes=template_bytes)
            finally:
                cap_hwpx.validate_cap_hwpx_template = current
                _PARTIAL_VALIDATION_ALLOWED.reset(token)

    return build_partial


def _meaningful_warnings(
    values: Sequence[str],
    active_markers: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Keep only warnings relevant to the official form file being written.

    Split law.go.kr attachments are built through the same generic CAP writer,
    so data engines for other annexes may legitimately report missing company
    facts. Those warnings are not meaningful for a Form-14-only HWPX. When the
    current file's markers are known, suppress only a warning that explicitly
    names an annex not present in that file.
    """
    active_form_numbers: set[str] | None = None
    if active_markers is not None:
        active_form_numbers = set()
        for marker in active_markers:
            match = re.search(r"별지\s*제?\s*(\d+)\s*호", str(marker))
            if match:
                active_form_numbers.add(match.group(1))

    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if "서식 제목" in text and "고유하게 찾지 못했습니다" in text:
            continue
        if active_form_numbers is not None:
            match = re.search(r"별지\s*제?\s*(\d+)\s*호", text)
            if match and match.group(1) not in active_form_numbers:
                continue
        if text not in out:
            out.append(text)
    return tuple(out)


def _scenario_name(row: Mapping[str, Any]) -> str:
    normalized = {
        re.sub(r"[^0-9A-Za-z가-힣]+", "", str(key or "")).lower(): value
        for key, value in row.items()
    }
    for alias in ("사고시나리오명", "사고시나리오", "시나리오명", "시나리오"):
        key = re.sub(r"[^0-9A-Za-z가-힣]+", "", alias).lower()
        value = normalized.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _project_for_scenario(project, scenario: str):
    clone = type(project).from_dict(project.to_dict())
    for key in ("cap.offsite.scenario_frequency", "cap.offsite.scenario_impact_table"):
        rec = clone.get_field(key)
        if rec is None or not isinstance(rec.value, list):
            continue
        filtered = [
            dict(row)
            for row in rec.value
            if isinstance(row, Mapping) and _scenario_name(row) == scenario
        ]
        if not filtered:
            continue
        clone.set_field(
            key,
            rec.label,
            filtered,
            rec.status,
            evidence=list(rec.evidence),
            note=rec.note,
        )
    return clone


def preflight_cap_risk_hwpx(project) -> CAPRiskRendererPreflight:
    """Validate current official Form 14/15 layout against the risk renderers.

    This preflight reads the CURRENT approved official-form bundle and actually
    runs the byte-preserving renderers on copies in memory.  It never mutates
    the archived originals.  Final readiness may be released only when the
    current legal source itself passes this probe.
    """
    form15 = build_cap_form15_data(project)
    if form15.no_offsite_scenario:
        return CAPRiskRendererPreflight(
            True,
            (),
            ("장외 사고시나리오 없음 확정으로 별지 제14·15호 출력대상이 없습니다.",),
        )

    form14 = build_cap_form14_data(project)
    if form14.blockers or form15.blockers:
        return CAPRiskRendererPreflight(
            False,
            (),
            ("별지 제14·15호 계산자료가 완성된 뒤 공식 HWPX 구조를 검증합니다.",),
        )

    bundle = resolve_current_cap_form_bundle()
    if not bundle.ready:
        details = ", ".join(bundle.missing_markers[:6]) or "공식 원본 확인 필요"
        return CAPRiskRendererPreflight(
            False,
            (f"현재 승인된 CAP 공식 HWPX 묶음이 완전하지 않아 별지 제14·15호 출력구조를 검증할 수 없습니다: {details}",),
            (),
        )

    marker14 = "[별지 제14호서식]"
    marker15 = "[별지 제15호서식]"
    forms14 = [form for form in bundle.forms if marker14 in form.markers]
    forms15 = [form for form in bundle.forms if marker15 in form.markers]
    blockers: list[str] = []
    messages: list[str] = []

    if len(forms14) != 1:
        blockers.append(f"별지 제14호 공식 원본을 고유하게 선택하지 못했습니다({len(forms14)}개).")
    if len(forms15) != 1:
        blockers.append(f"별지 제15호 공식 원본을 고유하게 선택하지 못했습니다({len(forms15)}개).")
    if blockers:
        return CAPRiskRendererPreflight(False, tuple(blockers), ())

    source14 = forms14[0]
    source15 = forms15[0]
    if len(form14.scenario_rows) > 1 and len(source14.markers) != 1:
        blockers.append(
            "복수 사고시나리오의 별지 제14호 원본을 시나리오별 복제하려면 "
            "별지 제14호가 다른 별지와 분리된 공식 파일이어야 합니다."
        )
    else:
        for row in form14.scenario_rows:
            scenario = str(row.get("사고시나리오명") or "").strip()
            scoped = _project_for_scenario(project, scenario)
            scoped14 = build_cap_form14_data(scoped)
            scoped15 = build_cap_form15_data(scoped)
            rendered = render_form14_single_scenario(source14.hwpx_data, scoped14, scoped15)
            blockers.extend(f"{scenario}: {warning}" for warning in rendered.warnings)
        if not blockers:
            messages.append(
                f"별지 제14호 공식 원본에 사고시나리오 {len(form14.scenario_rows)}건의 "
                "개시사건·시설빈도·안전성확보설비·보호대상 셀 매핑을 검증했습니다."
            )

    rendered15 = render_form15_risk(source15.hwpx_data, form15)
    blockers.extend(rendered15.warnings)
    if not rendered15.warnings:
        messages.append(
            "별지 제15호 공식 원본의 사고시나리오 행과 A·B·C·D, 구간점수, "
            "사고빈도·사고영향 점수 셀 매핑을 검증했습니다."
        )

    return CAPRiskRendererPreflight(
        ready=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )


def _build_bundle_zip(project, bundle: CAPOfficialFormBundle, original_build):
    if not bundle.ready:
        missing = ", ".join(bundle.missing_markers[:8]) or "미확인"
        details = " / ".join(bundle.issues[:4])
        raise FileNotFoundError(
            "법제처 최신 원본은 확인되었지만 자동작성에 필요한 공식 별지서식 묶음을 완전히 확인하지 못했습니다. "
            f"누락 서식: {missing}"
            + (f" · 확인사항: {details}" if details else "")
        )

    builder = _partial_builder(original_build)
    form14 = build_cap_form14_data(project)
    form15 = build_cap_form15_data(project)
    marker14 = "[별지 제14호서식]"
    marker15 = "[별지 제15호서식]"

    package = BytesIO()
    total_applied = 0
    user_warnings: list[str] = []
    manifest_lines = [
        "화학사고예방관리계획서 법제처 공식 원본서식 자동작성 묶음",
        "",
        "- 각 HWPX는 법제처에서 받은 개별 공식 원본서식의 레이아웃을 유지합니다.",
        "- 프로그램은 여러 원본을 하나의 새 법정서식으로 임의 병합하지 않습니다.",
        "- 별지 제14호는 사고시나리오별 공식 원본 1부씩 생성합니다.",
        "- 회사 확정자료만 자동 입력하며 최종 제출 전 담당자 확인이 필요합니다.",
        "",
    ]

    used_names: set[str] = set()
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as zf:
        output_index = 0
        for form_index, form in enumerate(bundle.forms, 1):
            form_marker_set = set(form.markers)

            # When Articles 24/25 are not applicable, do not emit blank
            # standalone Forms 14/15. A combined official file is retained
            # because it may contain other required statutory forms.
            if form15.no_offsite_scenario and form_marker_set and form_marker_set.issubset({marker14, marker15}):
                manifest_lines.append(f"[생략] {form.path.name}")
                manifest_lines.append("  사유: 장외 사고시나리오 없음 확정으로 별지 제14·15호 작성대상 없음")
                manifest_lines.append("")
                continue

            if marker14 in form_marker_set and len(form14.scenario_rows) > 1:
                if form_marker_set != {marker14}:
                    raise ValueError(
                        "별지 제14호 공식 원본이 다른 별지와 한 파일에 묶여 있어 "
                        "복수 사고시나리오별 원본 복제를 안전하게 수행할 수 없습니다."
                    )
                for scenario_row in form14.scenario_rows:
                    scenario = str(scenario_row.get("사고시나리오명") or "").strip()
                    scoped = _project_for_scenario(project, scenario)
                    result = builder(scoped, template_bytes=form.hwpx_data)
                    total_applied += int(result.applied_count)
                    warnings = _meaningful_warnings(result.warnings, form.markers)
                    user_warnings.extend(warnings)

                    output_index += 1
                    stem = _safe_name(form.path.stem, f"공식서식_{form_index:02d}")
                    scenario_safe = _safe_name(scenario, f"시나리오_{output_index:02d}")
                    name = f"{stem}_{scenario_safe}_작성본.hwpx"
                    if name in used_names:
                        name = f"{output_index:02d}_{name}"
                    used_names.add(name)
                    zf.writestr(name, result.data)

                    manifest_lines.append(f"[{output_index}] {form.path.name} / 사고시나리오: {scenario}")
                    manifest_lines.append("  포함서식: " + ", ".join(form.markers))
                    manifest_lines.append(f"  자동입력: {result.applied_count}건")
                    manifest_lines.append(f"  원본 SHA-256: {form.source_sha256}")
                    if warnings:
                        manifest_lines.append("  추가확인: " + " / ".join(warnings))
                    manifest_lines.append("")
                continue

            result = builder(project, template_bytes=form.hwpx_data)
            total_applied += int(result.applied_count)
            warnings = _meaningful_warnings(result.warnings)
            user_warnings.extend(warnings)

            output_index += 1
            stem = _safe_name(form.path.stem, f"공식서식_{form_index:02d}")
            name = f"{stem}_작성본.hwpx"
            if name in used_names:
                name = f"{output_index:02d}_{name}"
            used_names.add(name)
            zf.writestr(name, result.data)

            manifest_lines.append(f"[{output_index}] {form.path.name}")
            manifest_lines.append("  포함서식: " + ", ".join(form.markers))
            manifest_lines.append(f"  자동입력: {result.applied_count}건")
            manifest_lines.append(f"  원본 SHA-256: {form.source_sha256}")
            if warnings:
                manifest_lines.append("  추가확인: " + " / ".join(warnings))
            manifest_lines.append("")

        zf.writestr("원본서식_자동작성_안내.txt", "\n".join(manifest_lines).encode("utf-8"))

    data = package.getvalue()
    return cap_hwpx.CAPHwpxBuildResult(
        data=data,
        applied_count=total_applied,
        warnings=tuple(dict.fromkeys(user_warnings)),
        template_sha256=sha256(data).hexdigest(),
    )


def _bundle_filename(project) -> str:
    safe = _safe_name(project.company_name or project.project_id, "사업장")
    return f"{safe}_화학사고예방관리계획서_법제처원본서식_작성본.zip"


def install_cap_multi_form_runtime() -> None:
    """Install split-form support after the CURRENT-template priority wrapper."""
    current_registered = cap_hwpx.registered_cap_template
    if bool(getattr(current_registered, WRAPPER_MARKER, False)):
        return

    original_registered = current_registered
    original_build = cap_hwpx.build_cap_hwpx_draft
    original_filename = cap_hwpx.cap_hwpx_filename

    def registered_cap_template_multi(project):
        existing = original_registered(project)
        if existing is not None:
            return existing
        bundle = resolve_current_cap_form_bundle()
        if bundle.status in {"READY", "INCOMPLETE", "UNAVAILABLE"}:
            return _bundle_meta(bundle)
        return None

    def build_cap_hwpx_draft_multi(project, template_bytes: bytes | None = None):
        if template_bytes is not None:
            return original_build(project, template_bytes=template_bytes)
        meta = registered_cap_template_multi(project)
        source = str((meta or {}).get("template_source") or "")
        if source in {BUNDLE_SOURCE, BUNDLE_INCOMPLETE_SOURCE}:
            bundle = resolve_current_cap_form_bundle()
            return _build_bundle_zip(project, bundle, original_build)
        return original_build(project)

    def cap_hwpx_filename_multi(project) -> str:
        meta = registered_cap_template_multi(project)
        source = str((meta or {}).get("template_source") or "")
        if source in {BUNDLE_SOURCE, BUNDLE_INCOMPLETE_SOURCE}:
            return _bundle_filename(project)
        return original_filename(project)

    setattr(registered_cap_template_multi, WRAPPER_MARKER, True)
    setattr(build_cap_hwpx_draft_multi, WRAPPER_MARKER, True)
    setattr(cap_hwpx_filename_multi, WRAPPER_MARKER, True)
    cap_hwpx.registered_cap_template = registered_cap_template_multi
    cap_hwpx.build_cap_hwpx_draft = build_cap_hwpx_draft_multi
    cap_hwpx.cap_hwpx_filename = cap_hwpx_filename_multi

    # The Stage 5 page already calls Streamlit's download_button.  Adjust only
    # the CAP legal-form button when the generated package is a ZIP, so the
    # filename, label and MIME type are truthful without changing unrelated UI.
    try:
        import streamlit as st

        current_download = st.download_button
        if not bool(getattr(current_download, WRAPPER_MARKER, False)):
            def download_button_multi(label, *args, **kwargs):
                file_name = str(kwargs.get("file_name") or "")
                key = str(kwargs.get("key") or "")
                if key.startswith("download_cap_hwpx_") and file_name.lower().endswith(".zip"):
                    label = "화학사고예방관리계획서 법제처 원본서식 작성본 ZIP 다운로드"
                    kwargs["mime"] = "application/zip"
                return current_download(label, *args, **kwargs)

            setattr(download_button_multi, WRAPPER_MARKER, True)
            st.download_button = download_button_multi
    except Exception:
        # Streamlit may be unavailable in isolated unit tests; the CAP engine
        # itself remains usable and tests can still validate bundle behaviour.
        pass
