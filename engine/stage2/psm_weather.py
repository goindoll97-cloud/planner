from __future__ import annotations

"""PSM 별지 제19호의2 대기온도·습도를 사업장 주소로 자동 산정한다.

주소에서 가까운 기상청 관측소를 고르고(이름 일치, 못 찾으면 사용자가 선택), 지난 3년 일자료로 값을 만들어 근거와 함께
프로젝트에 기록한다. 이미 기록된 값이 있으면 다시 조회하지 않는다. 조회 실패는 오류가 아니라 상태로 돌려주고 직접 입력으로 넘어간다.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from .. import kma_asos
from .project import Stage2Project

KEY = "psm.risk.weather_basis"
ADDRESS_KEY = "business.address"


@dataclass(frozen=True)
class AutoResult:
    status: str  # SAVED / FILLED / NO_ADDRESS / NO_STATION / NOT_CONFIGURED / NO_DATA / ERROR
    message: str = ""


def saved(project: Stage2Project) -> dict[str, Any]:
    record = project.get_field(KEY)
    return dict(record.value) if record is not None and isinstance(record.value, dict) else {}


def address(project: Stage2Project) -> str:
    record = project.get_field(ADDRESS_KEY)
    return "" if record is None or record.value is None else str(record.value).strip()


def store(project: Stage2Project, basis: kma_asos.WeatherBasis) -> None:
    project.set_field(KEY, "대기온도·습도 산정 근거(기상청 ASOS 일자료)", {
        "관측소코드": basis.station_id, "관측소": f"{basis.station_name}({basis.station_id})", "기간": basis.period,
        "관측일수": basis.days, "최고기온(℃)": basis.max_temperature_c, "최고기온 일자": basis.max_temperature_date,
        "평균 상대습도(%)": basis.mean_humidity_pct, "평균 풍속(m/s)": basis.mean_wind_ms}, "CALCULATED",
        note="지난 3년 일자료의 일 최고기온 중 최댓값, 일 평균 상대습도의 평균. 낮 동안만의 평균 습도는 아님")


def refresh(project: Stage2Project, station: str, *, today: date | None = None,
            get: Callable[[str, dict[str, Any]], tuple[int, str]] | None = None) -> AutoResult:
    kwargs: dict[str, Any] = {"today": today}
    if get is not None:
        kwargs["get"] = get
    basis, result = kma_asos.three_year_basis(station, **kwargs)
    if basis is None:
        return AutoResult(result.status, result.message)
    store(project, basis)
    return AutoResult("FILLED", f"{basis.station_name} 관측소 {basis.period}({basis.days}일) 자료로 채웠습니다.")


def auto_fill(project: Stage2Project, *, today: date | None = None,
              get: Callable[[str, dict[str, Any]], tuple[int, str]] | None = None) -> AutoResult:
    """이미 있으면 그대로 두고, 없으면 주소로 관측소를 골라 조회한다."""
    if saved(project):
        return AutoResult("SAVED")
    where = address(project)
    if not where:
        return AutoResult("NO_ADDRESS", "사업장 주소가 없어 관측소를 고를 수 없습니다.")
    station = kma_asos.suggest_station(where)
    if not station:
        return AutoResult("NO_STATION", "주소에서 가까운 관측소를 찾지 못했습니다. 목록에서 골라 주세요.")
    return refresh(project, station, today=today, get=get)
