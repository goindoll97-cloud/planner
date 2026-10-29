"""Convert the completed CAP DOCX to a real HWP 5.0 file with Hancom Office."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import platform

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
                try:
                    hwp = Hwp(visible=False)
                except TypeError:
                    hwp = Hwp()
                if hwp.open(str(source), format="OOXML") is False:
                    raise RuntimeError("한컴오피스가 DOCX 초안을 열지 못했습니다.")
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
        return result
