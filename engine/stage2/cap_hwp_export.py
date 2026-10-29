"""Convert the completed CAP DOCX to a real HWP 5.0 file with Hancom Office."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import platform

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
