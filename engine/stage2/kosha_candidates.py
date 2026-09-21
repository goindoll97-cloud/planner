from __future__ import annotations

"""CAS 번호로 KOSHA 물질안전보건자료(제2항)를 조회해 'SDS 제2항 분류' 후보 문구를 만든다.

KOSHA 자료는 참고자료이며 회사 제품 SDS를 대신하지 않는다. 그래서 이 모듈은 값을 확정하지 않고 후보만 돌려주고,
사용자가 제품 SDS와 대조해 확인한 뒤에만 판정에 쓰도록 호출부가 강제한다. 분류에 '구분 N'이 명시된 항목만 후보로
쓰며, 자료가 없거나 분류가 보이지 않는다고 '해당없음'을 대신 채우지 않는다.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable

from .project import Stage2Project

CANDIDATES_KEY = "stage1.kosha_sds_candidates"
MAX_WORKERS = 4


@dataclass(frozen=True)
class Candidate:
    cas: str
    status: str
    text: str = ""
    chemical_name: str = ""
    message: str = ""
    checked_at_utc: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.text)


def candidate_text(classifications: Iterable[str]) -> str:
    """'구분 N'이 있는 분류만 판정 입력 형식(| 로 구분)으로 잇는다."""
    kept = [c.strip() for c in classifications if "구분" in str(c)]
    return "|".join(dict.fromkeys(kept))


def _lookup_default(cas: str):
    from engine import kosha_msds

    return kosha_msds.lookup_by_cas(cas)


def pending_cas(cas_numbers: Iterable[str], have: dict[str, Candidate]) -> list[str]:
    """아직 후보를 얻지 못한 CAS. 처음 조회하는 것과, 네트워크 오류로 실패한 것(다시 시도해 볼 만한 것)."""
    out = []
    for cas in dict.fromkeys(str(c).strip() for c in cas_numbers if str(c).strip()):
        cand = have.get(cas)
        if cand is None or (not cand.usable and cand.status == "API_ERROR"):
            out.append(cas)
    return out


def fetch(cas_numbers: Iterable[str], lookup: Callable = _lookup_default, retries: int = 1) -> dict[str, Candidate]:
    """CAS별 후보. 같은 CAS는 한 번만 조회하고, 조회 실패도 상태로 돌려준다(예외를 밖으로 내지 않는다).
    일시적인 네트워크 오류(연결 시간 초과 등)는 retries만큼 다시 시도한다."""
    unique = list(dict.fromkeys(str(c).strip() for c in cas_numbers if str(c).strip()))

    def once(cas: str) -> Candidate:
        try:
            result = lookup(cas)
        except Exception as exc:  # 네트워크·키 문제도 한 행의 상태로만 남긴다
            return Candidate(cas, "API_ERROR", message=f"{type(exc).__name__}")
        return Candidate(
            cas=cas, status=str(result.status), text=candidate_text(result.ghs_classifications),
            chemical_name=str(result.chemical_name or ""), message=str(result.message or ""),
            checked_at_utc=str(result.checked_at_utc or ""),
        )

    def one(cas: str) -> Candidate:
        candidate = once(cas)
        for _ in range(max(retries, 0)):
            if candidate.status != "API_ERROR":
                break
            candidate = once(cas)
        return candidate

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return dict(zip(unique, pool.map(one, unique)))


def record_use(project: Stage2Project, used: dict[str, Candidate]) -> None:
    """사용자가 확인하고 판정에 쓴 KOSHA 후보의 출처와 조회 시각을 프로젝트에 남긴다."""
    if not used:
        return
    record = project.get_field(CANDIDATES_KEY)
    current = dict(record.value) if record is not None and isinstance(record.value, dict) else {}
    for cas, cand in used.items():
        current[cas] = {"text": cand.text, "chemical_name": cand.chemical_name, "checked_at_utc": cand.checked_at_utc,
                        "source": "한국산업안전보건공단 물질안전보건자료 조회 서비스(참고자료, 사용자가 제품 SDS와 대조·확인함)"}
    project.set_field(CANDIDATES_KEY, "KOSHA 참고자료로 채운 SDS 제2항 분류(사용자 확인)", current, "USER_CONFIRMED")
