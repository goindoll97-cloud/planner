"""필드 단위 CAP 매뉴얼 작성가이드 로더.

data/stage2/cap_manual_registry.json이 "이 섹션에 어떤 자료가 필요한가"를
다루는 인테이크(수집) 단위 레지스트리라면, 이 모듈이 읽는
cap_manual_field_guidance.json은 그 registry의 field_keys 각각에 대해
"실제로 서식 한 칸을 어떻게 채우는가"를 다루는 문구 지침 레이어다.

같은 매뉴얼(NICS-GP2026-8)을 출처로 하며, 가능한 경우 registry와 동일한
field_keys를 그대로 사용해 두 레이어가 연결되도록 만들어졌다. 아직
3.1 기본정보(별지 제3~8호서식)만 채워져 있고 3.2~3.6은 추후 채워야 한다.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "stage2"
FIELD_GUIDANCE_PATH = DATA_DIR / "cap_manual_field_guidance.json"


@lru_cache(maxsize=1)
def load_cap_manual_field_guidance() -> dict[str, Any]:
    with FIELD_GUIDANCE_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "cap-manual-field-guidance-v1":
        raise ValueError("지원하지 않는 CAP 매뉴얼 필드가이드 registry 버전입니다.")
    return raw


def cap_field_guidance(field_key: str) -> dict[str, Any] | None:
    """field_key(예: 'cap.business.writing_level')에 대한 작성가이드를 반환한다.

    가이드가 아직 없는 field_key(3.2~3.6 미작성분 포함)에는 None을 반환한다 —
    작성요령이 없다는 뜻이지 오류가 아니므로, 호출부는 None을 "매뉴얼 지침
    없음"으로 다루고 회사 데이터만으로 진행해야 한다.
    """
    fields = load_cap_manual_field_guidance().get("fields") or {}
    entry = fields.get(field_key)
    return dict(entry) if isinstance(entry, dict) else None


def cap_field_guidance_text(field_key: str) -> str:
    """LLM 프롬프트에 그대로 주입할 수 있는 한 줄짜리 작성요령 문자열.

    guidance가 없거나(자명한 항목) 이 field_key 자체가 아직 미작성 구간이면
    빈 문자열을 반환한다 — 프롬프트에 "guidance: " 같은 빈 라벨을 남기지
    않기 위해서다.
    """
    entry = cap_field_guidance(field_key)
    if not entry:
        return ""
    guidance = entry.get("guidance")
    return str(guidance) if guidance else ""
