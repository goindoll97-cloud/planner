"""개정 전후 조문 비교(법제처 신구법 비교 Open API).

- 법령(법률·시행령·시행규칙): ``lawService.do?target=oldAndNew&MST=<법령일련번호>``
- 행정규칙(고시·규정):       ``lawService.do?target=admrulOldAndNew&ID=<행정규칙일련번호>``

응답의 ``구조문목록``·``신조문목록``은 신구조문대비표의 왼쪽·오른쪽 열이며 같은 순서로 나란히
놓인다. 이 모듈은 두 목록을 줄 단위로 짝지어 돌려준다. 법제처가 제공하는 비교는 현재 판과
**바로 직전 판** 사이의 비교이므로, 작성본이 여러 번의 개정 전에 쓰였다면 마지막 개정만 보인다.

조회 결과는 ``data/runtime/law_old_new/``에 캐시한다(같은 판은 다시 내려받지 않음).
실제 인증키로 응답 구조를 검증하기 전까지는 파싱이 실패하면 원문 링크만 안내한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import requests

from .law_api import SERVICE_URL, _safe_error, get_api_credential

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "data" / "runtime" / "law_old_new"
TARGETS = {"law": ("oldAndNew", "MST"), "admrul": ("admrulOldAndNew", "ID")}
_ARTICLE = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")
_TAG = re.compile(r"</?[A-Za-z][^>]*>")  # HTML 태그만 — '<삭제>' 같은 표기는 남긴다


def _clean_text(value: Any) -> str:
    text = _TAG.sub("", str(value or ""))
    text = (text.replace("&nbsp;", " ").replace("\xa0", " ")
            .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    return re.sub(r"[ \t]+", " ", text).strip()


def _walk(obj: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _find(payload: Any, *names: str) -> Any:
    wanted = {n.replace(" ", "") for n in names}
    for key, value in _walk(payload):
        if key.replace(" ", "") in wanted:
            return value
    return None


def _articles(block: Any) -> list[str]:
    """구조문목록/신조문목록 블록에서 조문 문자열 목록을 꺼낸다(문자열·목록·dict 모두 허용)."""
    if block is None:
        return []
    if isinstance(block, Mapping):
        inner = block.get("조문")
        if inner is None:
            inner = block.get("content") or block.get("#text")
        block = inner if inner is not None else list(block.values())
    if isinstance(block, str):
        return [_clean_text(block)]
    rows: list[str] = []
    for item in block if isinstance(block, list) else [block]:
        if isinstance(item, Mapping):
            text = item.get("content") or item.get("#text") or item.get("조문내용") or item.get("조문")
            rows.append(_clean_text(text if not isinstance(text, (list, Mapping)) else json.dumps(text, ensure_ascii=False)))
        else:
            rows.append(_clean_text(item))
    return rows


def _article_label(*texts: str) -> str:
    for text in texts:
        match = _ARTICLE.search(text or "")
        if match:
            return re.sub(r"\s+", "", match.group(0))
    return ""


def _is_deleted(text: str) -> bool:
    rest = _ARTICLE.sub("", text, count=1)
    rest = re.sub(r"^\s*(\([^)]*\))?\s*", "", rest)
    return rest.startswith("<삭제") or rest.strip() == "삭제"


def parse_old_new(payload: Any) -> dict[str, Any]:
    """신구법 응답을 {'status', 'rows': [{'조문','개정 전','개정 후','변경'}], 'old_info', 'new_info'}로."""
    exists = _clean_text(_find(payload, "신구법존재여부", "신구법 존재여부"))
    if exists.upper() == "N":
        return {"status": "NO_COMPARISON", "rows": [], "message": "법제처에 이 판의 신구조문 비교가 없습니다."}
    old_list = _articles(_find(payload, "구조문목록"))
    new_list = _articles(_find(payload, "신조문목록"))
    if not old_list and not new_list:
        return {"status": "PARSE_FAILED", "rows": [], "message": "응답에서 개정 전후 조문 목록을 찾지 못했습니다."}

    def _info(name: str) -> dict[str, str]:
        block = _find(payload, name)
        if not isinstance(block, Mapping):
            return {}
        keep = ("시행일자", "공포일자", "공포번호", "발령일자", "발령번호", "제개정구분명")
        return {k: _clean_text(block.get(k)) for k in keep if block.get(k) not in (None, "")}

    rows: list[dict[str, str]] = []
    for i in range(max(len(old_list), len(new_list))):
        before = old_list[i] if i < len(old_list) else ""
        after = new_list[i] if i < len(new_list) else ""
        if not before and not after:
            continue
        if not before:
            change = "신설"
        elif not after or _is_deleted(after):
            change = "삭제"
        elif before == after:
            change = "같음"
        else:
            change = "개정"
        rows.append({"조문": _article_label(after, before), "개정 전": before, "개정 후": after, "변경": change})
    return {
        "status": "OK",
        "rows": rows,
        "old_info": _info("구조문_기본정보"),
        "new_info": _info("신조문_기본정보"),
    }


def _cache_path(key: str, serial: str, cache_dir: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{key}_{serial}")
    return cache_dir / f"{safe}.json"


def fetch_old_new(
    key: str,
    source: Mapping[str, Any],
    *,
    timeout: int = 60,
    cache_dir: Path = CACHE_DIR,
    use_cache: bool = True,
) -> dict[str, Any]:
    """승인된 법령판(source: target·serial 포함)의 개정 전후 조문 비교."""
    target = str(source.get("target") or "")
    serial = str(source.get("serial") or "").strip()
    if target not in TARGETS or not serial:
        return {"status": "UNSUPPORTED", "rows": [], "message": "조회 정보(법령 종류·일련번호)가 없어 비교할 수 없습니다."}
    path = _cache_path(key, serial, cache_dir)
    if use_cache and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("status") in {"OK", "NO_COMPARISON"}:
                return cached
        except Exception:
            pass
    credential, _ = get_api_credential()
    if not credential:
        return {"status": "API_KEY_MISSING", "rows": [], "message": ".env에 LAW_OC를 넣어야 법제처에서 조문 비교를 불러올 수 있습니다."}
    service, id_param = TARGETS[target]
    try:
        response = requests.get(
            SERVICE_URL,
            params={"OC": credential, "target": service, "type": "JSON", id_param: serial},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"status": "API_ERROR", "rows": [], "message": _safe_error(exc, credential)}
    result = parse_old_new(payload)
    result.update({
        "key": key,
        "serial": serial,
        "target": target,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    if result["status"] in {"OK", "NO_COMPARISON"}:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return result
