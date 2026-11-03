"""Convert the completed CAP DOCX to a real HWP 5.0 file with Hancom Office."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import platform
import re

from hwpx.hwp5.reader import read_hwp5

from .hwp5_binary import HWP5_MAGIC


def available() -> bool:
    """The conversion requires the local Windows Hancom COM application."""
    if platform.system() != "Windows":
        return False
    try:
        import pyhwpx  # noqa: F401
    except ImportError:
        return False
    return True


def convert_docx_to_hwp(docx: bytes) -> bytes:
    """Ask Hancom Office to preserve the completed document layout on save."""
    if not available():
        raise RuntimeError("HWP 변환에는 Windows용 한컴오피스와 pyhwpx가 필요합니다.")
    from pyhwpx import Hwp  # type: ignore

    with TemporaryDirectory(prefix="planner_cap_hwp_") as root:
        source = Path(root) / "draft.docx"
        target = Path(root) / "draft.hwp"
        source.write_bytes(docx)
        hwp = None
        console = StringIO()
        try:  # pragma: no cover - Hancom COM is available only on Windows
            with redirect_stdout(console), redirect_stderr(console):
                # pyhwpx otherwise attaches to an existing editor and quit()
                # could close a document the user was editing.
                hwp = Hwp(new=True, visible=True)
                # Hancom's automatic format detection works on more installed
                # versions; OOXML is the documented explicit DOCX format.
                if hwp.open(str(source)) is False and hwp.open(str(source), format="OOXML") is False:
                    raise RuntimeError(
                        "한컴오피스가 DOCX 초안을 열지 못했습니다. 한글에서 DOCX를 직접 열 수 있는지 확인해 주세요. "
                        "열 수 없다면 설치된 한글 버전의 DOCX 가져오기 기능을 확인해야 합니다."
                    )
                if hwp.save_as(str(target), format="HWP", arg="lock:false;backup:false") is False:
                    raise RuntimeError("한컴오피스가 HWP 파일을 저장하지 못했습니다.")
        finally:
            if hwp is not None:
                try:
                    with redirect_stdout(console), redirect_stderr(console):
                        hwp.quit()
                except Exception:
                    pass
        if not target.is_file():
            raise RuntimeError("한컴오피스가 HWP 파일을 만들지 못했습니다.")
        result = target.read_bytes()
        if not result.startswith(HWP5_MAGIC):
            raise RuntimeError("변환 결과가 HWP 5.0 파일 형식이 아닙니다.")
        try:
            parsed = read_hwp5(result)
        except Exception as exc:
            raise RuntimeError("변환 결과의 HWP 본문 구조를 읽지 못했습니다.") from exc
        if not parsed.sections:
            raise RuntimeError("변환된 HWP 파일에 본문이 없습니다.")
        return result


@dataclass(frozen=True)
class CAPHWPWorkspaceDraft:
    """A real HWP file, plus the extent to which it was populated."""
    data: bytes
    mode: str  # "docx_converted", "official_mapped", "basic_only"
    applied_count: int = 0
    warnings: tuple[str, ...] = ()


def _require_company_text(data: bytes, company_name: str) -> None:
    """Reject an HWP that opened successfully but lost the business information."""
    if not company_name:
        return
    from .evidence_workspace import read_document

    tables, paragraphs = read_document("draft.hwp", data)
    fragments = [
        str(cell)
        for table in tables
        for row in table.rows
        for cell in row
    ]
    fragments.append(str(paragraphs))
    compact = lambda value: re.sub(r"\\s+", "", value)
    if compact(company_name) not in compact(" ".join(fragments)):
        raise RuntimeError(
            "HWP 문서에 사업장명이 들어 있지 않습니다. 빈 변환본을 내려받을 수 없습니다."
        )


def build_workspace_hwp(project, completed_docx: bytes) -> CAPHWPWorkspaceDraft:
    """Export the completed CAP DOCX, falling back to a clearly labeled partial HWP.

    A Windows Hancom installation can convert the actual DOCX draft, including
    narratives. On other systems, populate the supplied original HWPX wherever
    the statutory-cell mapper has safe targets. Never call that partial output
    equivalent to the completed DOCX.
    """
    if not completed_docx.startswith(b"PK"):
        raise ValueError("작성된 DOCX 파일을 확인할 수 없습니다.")

    warnings: list[str] = []
    if available():
        try:
            converted = convert_docx_to_hwp(completed_docx)
            _require_company_text(converted, project.company_name)
            return CAPHWPWorkspaceDraft(data=converted, mode="docx_converted")
        except Exception:
            warnings.append(
                "완성된 DOCX의 HWP 변환에 실패하여 원본서식 부분 작성본을 제공합니다."
            )
    else:
        warnings.append(
            "DOCX 전체를 HWP로 변환하려면 프로그램 실행 컴퓨터에 Windows, 한컴오피스와 pyhwpx가 필요합니다."
        )

    from . import cap_direct_hwp
    from .hwp5_binary import from_hwpx

    try:
        from .cap_hwpx import build_cap_hwpx_draft

        rendered = build_cap_hwpx_draft(
            project, template_bytes=cap_direct_hwp.SOURCE.read_bytes()
        )
        if rendered.applied_count:
            hwp = from_hwpx(rendered.data)
            _require_company_text(hwp, project.company_name)
            return CAPHWPWorkspaceDraft(
                data=hwp,
                mode="official_mapped",
                applied_count=rendered.applied_count,
                warnings=tuple(warnings + list(rendered.warnings)),
            )
    except Exception:
        warnings.append(
            "일부 법정서식 항목 자동 입력에 실패하여 사업장 일반정보만 작성합니다."
        )

    basic = cap_direct_hwp.build_partial_hwp(project)
    _require_company_text(basic, project.company_name)
    return CAPHWPWorkspaceDraft(
        data=basic, mode="basic_only", warnings=tuple(warnings)
    )
