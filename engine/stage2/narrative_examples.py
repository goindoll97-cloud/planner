from __future__ import annotations

"""서술형 사실 입력에 붙이는 일반 예시. 예시는 참고용이며 저장 전에는 회사 사실이 아니다."""

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "stage2"
DATA_PATH = DATA_DIR / "narrative_examples.json"
EXTRA_PATHS = (DATA_DIR / "narrative_examples_cap.json",)


@lru_cache(maxsize=1)
def _doc() -> dict[str, Any]:
    """공용 예시 파일에 문서별 예시 파일의 사실 항목을 합친다."""
    doc = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    for path in EXTRA_PATHS:
        extra = json.loads(path.read_text(encoding="utf-8"))
        overlap = set(doc["facts"]) & set(extra["facts"])
        if overlap:
            raise ValueError(f"예시 항목이 겹칩니다: {sorted(overlap)}")
        doc["facts"].update(extra["facts"])
    return doc


MARK = "(예시)"


def labelled(text: str) -> str:
    """예시 문구 앞에 (예시) 표시를 붙인다."""
    return f"{MARK} {text}"


def has_mark(text: object) -> bool:
    return str(text or "").lstrip().startswith(MARK)


def strip_mark(text: object) -> str:
    value = str(text or "").lstrip()
    return value[len(MARK):].lstrip() if value.startswith(MARK) else str(text or "")


def notice() -> str:
    return str(_doc()["notice"])


def draft_checks() -> list[str]:
    return list(_doc()["draft_checks"])


def choices(key: str, field: str = "") -> list[str]:
    """사실 키(묶음 사실이면 하위 칸 이름도)에 대한 고를 수 있는 예시 목록."""
    entry = _doc()["facts"].get(key, {})
    value = entry.get(field) if field else entry.get("choices")
    return list(value) if isinstance(value, list) else []


def template(key: str) -> str:
    return str(_doc()["facts"].get(key, {}).get("template", ""))


def checks(key: str) -> list[str]:
    return list(_doc()["facts"].get(key, {}).get("checks", []))


def is_example(key: str, field: str, text: object) -> bool:
    """입력한 문장이 예시와 글자 그대로 같은지(고치지 않고 그대로 골랐는지)."""
    value = " ".join(strip_mark(text).split())
    return bool(value) and any(value == " ".join(item.split()) for item in choices(key, field))
