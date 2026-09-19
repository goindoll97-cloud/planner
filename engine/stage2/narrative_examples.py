from __future__ import annotations

"""서술형 사실 입력에 붙이는 일반 예시. 예시는 참고용이며 저장 전에는 회사 사실이 아니다."""

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "narrative_examples.json"


@lru_cache(maxsize=1)
def _doc() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


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
    value = " ".join(str(text or "").split())
    return bool(value) and any(value == " ".join(item.split()) for item in choices(key, field))
