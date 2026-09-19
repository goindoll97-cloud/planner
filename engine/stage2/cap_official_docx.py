from __future__ import annotations

"""Optional CAP HWPX-to-DOCX conversion helpers.

The statutory HWP/HWPX attachment remains the layout authority.  These
conversion helpers are retained for internal/explicit use; Stage 5 does not
expose a Word-conversion section.  (Stage 5's own synthetic combined DOCX
labels/styling now live in the shared export panel, ui/report_export_panel.py.)
"""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
import platform
import re
import tempfile
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from . import cap_hwpx


@dataclass(frozen=True)
class CAPOfficialWordResult:
    data: bytes
    file_name: str
    mime: str
    form_count: int


def _safe_name(value: str, fallback: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", str(value or "")).strip("._")
    return text[:140] or fallback


def _zip_names(data: bytes) -> tuple[str, ...]:
    try:
        with ZipFile(BytesIO(data), "r") as zf:
            return tuple(zf.namelist())
    except BadZipFile as exc:
        raise ValueError("CAP 원본서식 결과가 유효한 ZIP/HWPX 형식이 아닙니다.") from exc


def _is_hwpx(data: bytes) -> bool:
    names = _zip_names(data)
    return any(re.fullmatch(r"Contents/section\d+\.xml", name) for name in names)


def _convert_one_hwpx_to_docx(hwpx_data: bytes, stem: str) -> bytes:
    if platform.system() != "Windows":
        raise RuntimeError(
            "법제처 원본서식 Word 변환은 Windows + 한컴오피스 환경에서만 지원합니다. "
            "법정 원본은 HWPX 작성본을 사용해 주세요."
        )
    try:
        from pyhwpx import Hwp  # type: ignore
    except Exception as exc:  # pragma: no cover - Windows-only optional path
        raise RuntimeError("Word 변환을 위해 pyhwpx와 한컴오피스가 필요합니다.") from exc

    safe_stem = _safe_name(stem, "CAP_공식서식")
    with tempfile.TemporaryDirectory(prefix="cap_hwpx_to_docx_") as tmp:
        src = Path(tmp) / f"{safe_stem}.hwpx"
        dst = Path(tmp) / f"{safe_stem}.docx"
        src.write_bytes(hwpx_data)
        hwp = None
        console = StringIO()
        try:  # pragma: no cover - requires Hancom COM
            with redirect_stdout(console), redirect_stderr(console):
                try:
                    hwp = Hwp(visible=False)
                except TypeError:
                    hwp = Hwp()
                opened = hwp.open(str(src), format="HWPX")
                if opened is False:
                    raise RuntimeError("한컴오피스가 작성된 HWPX를 열지 못했습니다.")
                saved = hwp.save_as(
                    str(dst),
                    format="OOXML",
                    arg="lock:false;backup:false;export",
                )
                if saved is False:
                    raise RuntimeError("한컴오피스가 DOCX 변환 저장을 완료하지 못했습니다.")
        finally:
            if hwp is not None:
                try:
                    with redirect_stdout(console), redirect_stderr(console):
                        hwp.quit()
                except Exception:
                    pass
        if not dst.exists() or dst.stat().st_size == 0:
            raise RuntimeError("한컴오피스에서 HWPX→DOCX 변환 결과를 만들지 못했습니다.")
        data = dst.read_bytes()
        if not data.startswith(b"PK"):
            raise RuntimeError("생성된 Word 파일이 정상적인 DOCX 패키지가 아닙니다.")
        return data


def build_cap_official_word(project) -> CAPOfficialWordResult:
    """Build official CAP form(s) first, then export the completed originals to DOCX."""
    written = cap_hwpx.build_cap_hwpx_draft(project)
    company = _safe_name(project.company_name or project.project_id, "사업장")

    if _is_hwpx(written.data):
        docx = _convert_one_hwpx_to_docx(
            written.data,
            f"{company}_화학사고예방관리계획서_법제처원본서식_작성본",
        )
        return CAPOfficialWordResult(
            data=docx,
            file_name=f"{company}_화학사고예방관리계획서_법제처원본서식_Word변환본.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            form_count=1,
        )

    names = _zip_names(written.data)
    hwpx_names = [name for name in names if name.lower().endswith(".hwpx")]
    if not hwpx_names:
        raise ValueError("법제처 원본서식 작성 결과에서 변환할 HWPX 파일을 찾지 못했습니다.")

    source_zip = ZipFile(BytesIO(written.data), "r")
    out = BytesIO()
    try:
        with ZipFile(out, "w", compression=ZIP_DEFLATED) as target_zip:
            for index, name in enumerate(hwpx_names, 1):
                hwpx_data = source_zip.read(name)
                stem = Path(name).stem
                docx_data = _convert_one_hwpx_to_docx(hwpx_data, stem)
                target_zip.writestr(
                    f"{_safe_name(stem, f'공식서식_{index:02d}')}.docx",
                    docx_data,
                )
            if "원본서식_자동작성_안내.txt" in names:
                target_zip.writestr(
                    "원본서식_자동작성_안내.txt",
                    source_zip.read("원본서식_자동작성_안내.txt"),
                )
            target_zip.writestr(
                "Word변환본_안내.txt",
                (
                    "이 묶음의 DOCX는 프로그램이 새 표를 그린 파일이 아닙니다.\n"
                    "회사 확인값을 입력한 법제처 원본 HWPX를 한컴오피스의 OOXML(DOCX) 저장 기능으로 변환한 파일입니다.\n"
                    "원본 HWPX가 법정 레이아웃 기준이며, 최종 제출 전 한컴오피스에서 시각 확인해 주세요.\n"
                ).encode("utf-8"),
            )
    finally:
        source_zip.close()

    return CAPOfficialWordResult(
        data=out.getvalue(),
        file_name=f"{company}_화학사고예방관리계획서_법제처원본서식_Word변환본.zip",
        mime="application/zip",
        form_count=len(hwpx_names),
    )
