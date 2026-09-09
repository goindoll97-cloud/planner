from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAW_BASE_URL = "https://www.law.go.kr"
SEARCH_URL = f"{LAW_BASE_URL}/DRF/lawSearch.do"
SERVICE_URL = f"{LAW_BASE_URL}/DRF/lawService.do"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_local_env() -> None:
    """Load simple KEY=VALUE entries without overriding process variables."""
    for path in (PROJECT_ROOT / ".env", Path.cwd() / ".env"):
        if not path.exists():
            continue
        try:
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)
        except OSError:
            continue


def get_api_credential() -> tuple[str, str]:
    _load_local_env()
    value = os.getenv("LAW_OC", "").strip()
    if value:
        return value, "환경변수 또는 .env"
    return "", "미설정"


def credential_status() -> dict[str, str]:
    value, source = get_api_credential()
    return {
        "status": "READY" if value else "MISSING",
        "source": source,
        "message": "LAW_OC 설정 완료" if value else ".env 또는 환경변수에 LAW_OC를 설정하세요.",
    }


def _recursive_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _recursive_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _recursive_dicts(value)


def _normalized_title(value: Any) -> str:
    return re.sub(r"\s+", "", _clean(value))


def _normalize_appendix_no(value: Any) -> str:
    """Normalize appendix numbers such as '13', '013', '[별표 13]' to '13'."""
    digits = re.sub(r"\D", "", _clean(value))
    if not digits:
        return ""
    try:
        return str(int(digits))
    except ValueError:
        return digits


def _safe_error(exc: Exception, credential: str) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if credential:
        text = text.replace(credential, "***")
    return re.sub(r"([?&]OC=)[^&\s]+", r"\1***", text, flags=re.I)


def _date_key(value: Any) -> int:
    digits = re.sub(r"\D", "", _clean(value))
    try:
        return int(digits[:8]) if digits else 0
    except ValueError:
        return 0


def _is_deleted_attachment(title: str) -> bool:
    """Return True for official placeholder appendices/forms whose content is deleted.

    The Open API may expose current attachment records such as ``<삭제>`` or
    ``삭제``.  Those PDFs are not operative regulatory content and must not be
    hashed as if they were active annexes.
    """
    normalized = re.sub(r"[\s<>\[\]{}()]+", "", _clean(title))
    return normalized in {"삭제", "폐지"} or normalized.startswith("삭제")


def search_current_source(title: str, target: str, timeout: int = 45) -> dict[str, Any]:
    """Find the exact current law/administrative-rule record by official title."""
    credential, source = get_api_credential()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not credential:
        return {
            "api_status": "API_KEY_MISSING",
            "checked_at_utc": checked_at,
            "credential_source": source,
            "message": ".env 또는 환경변수에 LAW_OC를 설정해야 공식 법령을 확인할 수 있습니다.",
        }

    if target not in {"law", "admrul"}:
        return {
            "api_status": "UNSUPPORTED_TARGET",
            "checked_at_utc": checked_at,
            "message": f"지원하지 않는 target입니다: {target}",
        }

    try:
        response = requests.get(
            SEARCH_URL,
            params={
                "OC": credential,
                "target": target,
                "type": "JSON",
                "query": title,
                "display": 100,
                "nw": 1,
                "search": 1,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()

        candidates: list[dict[str, Any]] = []
        wanted = _normalized_title(title)
        for record in _recursive_dicts(payload):
            if target == "law":
                found_title = _clean(record.get("법령명한글") or record.get("법령명_한글"))
                serial = _clean(record.get("법령일련번호"))
                stable_id = _clean(record.get("법령ID"))
                issue_date = _clean(record.get("공포일자"))
                issue_number = _clean(record.get("공포번호"))
            else:
                found_title = _clean(record.get("행정규칙명") or record.get("행정규칙제목"))
                serial = _clean(record.get("행정규칙일련번호") or record.get("행정규칙 일련번호"))
                stable_id = _clean(record.get("행정규칙ID"))
                issue_date = _clean(record.get("발령일자"))
                issue_number = _clean(record.get("발령번호") or record.get("행정규칙발령번호"))

            if not found_title or not serial:
                continue
            if _normalized_title(found_title) != wanted:
                continue
            candidates.append(
                {
                    "title": found_title,
                    "serial": serial,
                    "stable_id": stable_id,
                    "issue_date": issue_date,
                    "issue_number": issue_number,
                    "effective_date": _clean(record.get("시행일자")),
                    "revision_type": _clean(record.get("제개정구분명")),
                    "ministry": _clean(record.get("소관부처명")),
                }
            )

        if not candidates:
            return {
                "api_status": "NO_EXACT_MATCH",
                "checked_at_utc": checked_at,
                "credential_source": source,
                "message": f"공식 API 검색 결과에서 정확히 일치하는 현행 제목을 찾지 못했습니다: {title}",
            }

        best = sorted(
            candidates,
            key=lambda row: (
                _date_key(row.get("effective_date")),
                _date_key(row.get("issue_date")),
                int(row["serial"]) if str(row.get("serial", "")).isdigit() else 0,
            ),
        )[-1]
        return {
            "api_status": "FOUND",
            "checked_at_utc": checked_at,
            "credential_source": source,
            "message": "국가법령정보 공동활용 API 현행본 확인 완료",
            **best,
        }
    except Exception as exc:
        return {
            "api_status": "API_ERROR",
            "checked_at_utc": checked_at,
            "credential_source": source,
            "message": _safe_error(exc, credential),
        }


def fetch_source_payload(search_result: dict[str, Any], target: str, timeout: int = 90) -> dict[str, Any]:
    """Fetch the full official JSON for one previously resolved current source.

    For statutes/decrees, ``BD=ON`` is explicitly requested so the Open API
    includes appendix metadata (별표단위).  This is required for PSM 시행령
    별표 13 monitoring; a plain law body response can omit the appendix block.
    """
    if search_result.get("api_status") != "FOUND":
        raise ValueError("현행 법령 검색이 성공한 자료만 본문을 조회할 수 있습니다.")
    credential, _ = get_api_credential()
    if not credential:
        raise RuntimeError("LAW_OC가 설정되어 있지 않습니다.")

    serial = _clean(search_result.get("serial"))
    params: dict[str, Any] = {"OC": credential, "target": target, "type": "JSON"}
    if target == "law":
        params["MST"] = serial
        params["BD"] = "ON"
    elif target == "admrul":
        params["ID"] = serial
    else:
        raise ValueError(f"지원하지 않는 target입니다: {target}")

    response = requests.get(SERVICE_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def extract_attachments(payload: Any) -> list[dict[str, str]]:
    """Extract active official appendix/form links from law/admrul JSON payloads.

    Deleted placeholder records are ignored.  Duplicate records that point to
    the same official PDF/HWP URL are also collapsed so the same attachment is
    not downloaded twice merely because the API returned two metadata shapes.
    """
    found: list[dict[str, str]] = []
    seen_urls: set[tuple[str, str]] = set()
    seen_meta: set[tuple[str, str, str, str, str]] = set()

    for record in _recursive_dicts(payload):
        pdf_path = _clean(record.get("별표서식PDF파일링크"))
        hwp_path = _clean(record.get("별표서식파일링크"))
        if not pdf_path and not hwp_path:
            continue

        title = _clean(record.get("별표제목"))
        if _is_deleted_attachment(title):
            continue

        pdf_url = urljoin(LAW_BASE_URL, pdf_path) if pdf_path else ""
        hwp_url = urljoin(LAW_BASE_URL, hwp_path) if hwp_path else ""
        url_signature = (pdf_url, hwp_url)
        if url_signature != ("", "") and url_signature in seen_urls:
            continue

        item = {
            "appendix_no": _normalize_appendix_no(record.get("별표번호")),
            "appendix_branch": _normalize_appendix_no(record.get("별표가지번호")),
            "appendix_kind": _clean(record.get("별표구분")),
            "appendix_title": title,
            "pdf_url": pdf_url,
            "hwp_url": hwp_url,
        }
        meta_signature = (
            item["appendix_kind"],
            item["appendix_no"],
            item["appendix_branch"],
            item["appendix_title"],
            item["pdf_url"] or item["hwp_url"],
        )
        if meta_signature in seen_meta:
            continue

        if url_signature != ("", ""):
            seen_urls.add(url_signature)
        seen_meta.add(meta_signature)
        found.append(item)
    return found


def download_binary(url: str, timeout: int = 90) -> bytes:
    if not url:
        raise ValueError("다운로드 URL이 비어 있습니다.")
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content
