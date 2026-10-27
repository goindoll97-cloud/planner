"""HWP 5.0 읽기·쓰기. 확장자가 아닌 OLE 파일 시그니처로 결과를 확인한다."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

HWP5_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def to_hwpx(content: bytes) -> bytes:
    """HWP 5.0을 HWPX 바이트로 변환해 기존 구조화 추출기에 전달한다."""
    if not content.startswith(HWP5_MAGIC):
        raise ValueError("HWP 5.0 파일이 아닙니다. 파일 형식과 암호 설정을 확인해 주세요.")
    from hwpx import HwpxDocument
    try:
        doc = HwpxDocument.open(content)
        report = getattr(doc, "conversion_report", None)
        if report and (getattr(report, "dropped", None) or getattr(report, "unconverted", None)):
            raise ValueError("HWP 문서의 일부 구조를 옮기지 못했습니다. 한글에서 HWPX로 저장하고 원본과 대조해 주세요.")
        return doc.to_bytes()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("HWP를 읽지 못했습니다. 암호·손상 여부를 확인하거나 한글에서 HWPX로 다시 저장해 주세요.") from exc


def from_hwpx(content: bytes) -> bytes:
    """HWPX를 실제 바이너리 HWP 5.0으로 저장하고 시그니처를 확인한다."""
    from hwpx import HwpxDocument
    with TemporaryDirectory(prefix="planner_hwp5_") as root:
        path = Path(root) / "document.hwp"
        doc = HwpxDocument.open(content)
        doc.save_to_path(path)
        result = path.read_bytes()
    if not result.startswith(HWP5_MAGIC):
        raise ValueError("HWP 5.0 변환 결과가 올바른 바이너리 형식이 아닙니다.")
    return result
