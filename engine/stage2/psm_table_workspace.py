from __future__ import annotations

"""PSM 표 서식(별지 제14호 등)을 화면 표로 작성한다. 서식마다 데이터 정의만 다르고 저장·점검 방식은 같다.

저장 키와 열 이름은 서식 출력 코드(statutory_report, psm_baseline_docx)가 읽는 이름과 같게 둔다. 이 화면이 그 표의
유일한 입력 창구이므로 저장할 때 표 전체를 교체하고, 완전히 빈 행은 버린다. 해당하는 사업장만 작성하는 조건부 서식은
적용 여부와 확인근거를 먼저 받는다(psm_later_form_engine이 읽는 psm.psi.form_applicability).
"""

from dataclasses import dataclass
from typing import Any, Mapping

from .project import Stage2Project


@dataclass(frozen=True)
class Column:
    id: str
    label: str
    help: str
    required: bool = True
    kind: str = "text"
    options: tuple[str, ...] = ()  # 자주 쓰는 선택지(직접 입력도 가능)


@dataclass(frozen=True)
class TableSpec:
    form_no: str
    key: str
    title: str
    summary: str
    columns: tuple[Column, ...]
    unique: str = ""  # 중복되면 안 되는 열
    one_of: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (안내 문구, 그중 하나는 있어야 하는 열들)
    conditional: bool = False  # 해당하는 사업장만 작성하는 서식
    seed_key: str = ""  # 화학사고예방관리계획서에서 이미 입력한 같은 성격의 표
    seed_map: tuple[tuple[str, str], ...] = ()  # (이 서식 열, 그 표의 열)

    def column_ids(self) -> list[str]:
        return [c.id for c in self.columns]


def _cols(*items: tuple) -> tuple[Column, ...]:
    """(열 이름, 도움말[, 'opt']) 목록을 Column으로 바꾼다. 화면 라벨은 열 이름과 같다."""
    return tuple(Column(item[0], item[0], item[1], required=not (len(item) > 2 and item[2] == "opt")) for item in items)


MACHINERY = TableSpec(
    "14", "psm.psi.machinery_list", "동력기계 목록",
    "펌프·압축기·교반기·송풍기처럼 전동기로 돌아가는 기계를 한 줄에 하나씩 적습니다. 기계 사양서와 P&ID에서 확인합니다.",
    (
        Column("기계번호", "동력기계 번호", "도면(P&ID)에 붙은 기계 기호입니다. (예시) P-101"),
        Column("기계명", "동력기계명", "기계의 이름입니다. (예시) 염소 이송 펌프, 배기 팬"),
        Column("명세", "명세", "종류와 용량입니다. (예시) 원심펌프 10 m3/h, 양정 30 m"),
        Column("주요재질", "주요재질", "물질과 닿는 부분의 주된 재질입니다. (예시) SUS316, 카본강"),
        Column("전동기용량", "전동기용량(kW)", "전동기의 용량(kW)입니다. 명판이나 사양서에서 확인합니다."),
        Column("방호·보호장치 종류", "방호·보호장치의 종류",
               "법으로 정한 안전·방호장치와 모터보호장치(THT＼R, EOCR, EMPR 등)를 적습니다."),
        Column("비고", "비고", "인버터나 기동방식(직입, Y-Δ 등)을 적습니다. 없으면 비워 둡니다.", required=False),
    ),
    unique="기계번호",
)

PIPING = TableSpec(
    "16", "psm.psi.piping_gasket_specs", "배관 및 개스킷 명세",
    "배관을 종류(분류코드)별로 한 줄씩 적습니다. 배관 재질과 개스킷 사양은 배관 사양서(Piping Class)에서 확인합니다.",
    _cols(
        ("분류코드", "P&ID에서 배관 종류를 구분하는 코드(Class)입니다. (예시) A1A"),
        ("유체의 명칭 또는 구분", "그 배관에 흐르는 물질이나 구분입니다. (예시) 염소, 공정수"),
        ("설계온도", "배관의 설계온도(℃)입니다."),
        ("설계압력", "배관의 설계압력(MPa)입니다."),
        ("배관재질", "배관의 재질입니다. (예시) SUS316L, CS"),
        ("개스킷 재질 및 형태", "개스킷의 재질과 형태입니다. (예시) 스파이럴 와운드"),
        ("비파괴검사율", "용접부 비파괴검사 비율(%)입니다."),
        ("후열처리여부", "용접 후 열처리를 하는지(예/아니오)입니다."),
        ("비고", "관련 P&ID 번호 등을 적습니다.", "opt"),
    ),
    unique="분류코드",
)

# (저장 열 이름 = 서식 출력 코드가 읽는 이름, 화면 라벨, 도움말)
_RELIEF_COLUMNS = (
    ("안전밸브·파열판 번호", "계기번호", "도면상의 안전밸브 또는 파열판 번호입니다. (예시) PSV-101"),
    ("배출물질", "내용물", "밸브를 통해 나가는 물질입니다."),
    ("배출상태", "물상태", "나가는 물질의 상태(기체·액체·2상)입니다."),
    ("배출용량", "배출용량(kg/hr)", "사고 때 배출해야 하는 양(kg/hr)입니다. 계산서에서 확인합니다."),
    ("정격용량", "정격용량(kg/hr)", "밸브가 실제로 배출할 수 있는 양(kg/hr)입니다. 제작사 자료에서 확인합니다."),
    ("노즐크기 입구", "노즐크기-입구", "입구 노즐 크기입니다."),
    ("노즐크기 출구", "노즐크기-출구", "출구 노즐 크기입니다."),
    ("보호대상 설비번호", "보호기기 번호", "이 밸브가 지키는 설비 번호입니다. 별지 제15호의 장치번호와 같아야 합니다."),
    ("보호기기 운전압력", "보호기기 운전압력(MPa)", "보호 대상 설비의 운전압력입니다."),
    ("보호기기 설계압력", "보호기기 설계압력(MPa)", "보호 대상 설비의 설계압력입니다."),
    ("설정압력", "설정압력(MPa)", "밸브가 열리기 시작하는 압력입니다."),
    ("몸체재질", "몸체재질", "밸브 몸체의 재질입니다."),
    ("TRIM 재질", "TRIM 재질", "밸브 내부 부품(트림)의 재질입니다."),
    ("정밀도", "정밀도(오차범위)", "설정압력의 허용 오차입니다."),
    ("최종 배출·처리 지점", "배출 연결부위", "나간 물질이 최종 도착하는 곳입니다. (예시) 대기, 스크러버, 플레어"),
    ("배출원인", "배출원인", "밸브가 작동하는 원인입니다. (예시) 냉각수 차단, 화재, 밸브 오작동"),
    ("형식", "형식", "밸브 형식입니다. (예시) 스프링식, 파일럿식, 파열판"),
)
RELIEF = TableSpec(
    "17", "psm.psi.relief_device_specs", "안전밸브 및 파열판 명세",
    "압력이 너무 높아질 때 열리는 안전밸브와 파열판을 한 줄에 하나씩 적습니다. 제작사 사양서와 P&ID에서 확인합니다.",
    tuple(Column(i, label, help_text) for i, label, help_text in _RELIEF_COLUMNS),
    unique="안전밸브·파열판 번호",
)

_SETPOINTS = ("설정값-온도(℃)", "설정값-압력(MPa)", "설정값-액위(m)", "설정값-기타")
INTERLOCK = TableSpec(
    "17-2", "psm.psi.interlock_conditions", "이상발생시 인터록 작동조건 및 가동중지 범위",
    "이상 상태가 되면 설비를 자동으로 멈추는 장치(인터록)를 한 줄에 하나씩 적습니다. 설정값은 온도·압력·액위·기타 중 하나 이상 적습니다.",
    _cols(
        ("인터록번호", "다른 인터록과 구분되는 번호입니다. (예시) IL-101"),
        ("대상설비번호", "이 인터록이 감시하는 설비 번호입니다."),
        ("설정값-온도(℃)", "온도가 이 값이 되면 작동합니다. 해당 없으면 비워 둡니다.", "opt"),
        ("설정값-압력(MPa)", "압력이 이 값이 되면 작동합니다. 해당 없으면 비워 둡니다.", "opt"),
        ("설정값-액위(m)", "액위가 이 값이 되면 작동합니다. 해당 없으면 비워 둡니다.", "opt"),
        ("설정값-기타", "유량 등 다른 설정값입니다.", "opt"),
        ("감지기번호", "이상을 감지하는 계기 번호입니다."),
        ("최종 작동설비번호", "마지막에 작동해서 멈추거나 차단하는 설비 번호입니다."),
        ("가동중지범위", "멈추는 범위입니다. (예시) 반응기 투입 중단, 전체 공정 정지"),
        ("점검주기", "인터록을 점검하는 주기입니다. (예시) 연 1회"),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
    unique="인터록번호",
    one_of=(("설정값(온도·압력·액위·기타 중 최소 1개)", _SETPOINTS),),
    conditional=True,
)

_FIGHTING = ("소화기", "자동확산소화기", "자동소화장치", "옥내소화전", "스프링클러", "물분무소화설비", "포소화설비",
             "CO2 소화설비", "할로겐화합물 소화설비", "청정소화약제 소화설비", "옥외소화전")
FIRE_FIGHTING = TableSpec(
    "17-3", "psm.psi.fire_protection_table", "소화설비 설치계획",
    "설치 지역마다 설치할 소화설비의 개수를 적습니다. 설치하지 않는 설비는 비워 둡니다.",
    _cols(("설치지역", "소화설비를 설치하는 지역입니다."),
          *[(n, f"{n}의 설치 개수입니다. 없으면 비워 둡니다.", "opt") for n in _FIGHTING]),
    unique="설치지역",
    one_of=(("소화설비 종류별 설치현황 중 최소 1개", _FIGHTING),),
    conditional=True,
)

_DETECTION = ("단독경보형 감지기", "비상경보설비", "시각경보기", "자동화재탐지설비", "비상방송설비", "자동화재속보설비",
              "통합감시시설", "누전경보기")
FIRE_DETECTION = TableSpec(
    "17-4", "psm.psi.fire_detection_table", "화재탐지경보설비 설치계획",
    "설치 지역마다 설치할 화재탐지·경보설비의 개수나 유무를 적습니다. 설치하지 않는 설비는 비워 둡니다.",
    _cols(("설치지역", "화재탐지경보설비를 설치하는 지역입니다."),
          *[(n, f"{n}의 설치 여부나 개수입니다. 없으면 비워 둡니다.", "opt") for n in _DETECTION]),
    unique="설치지역",
    one_of=(("화재탐지·경보설비 종류별 설치현황 중 최소 1개", _DETECTION),),
    conditional=True,
)

GAS_ALARM = TableSpec(
    "17-5", "psm.psi.gas_detection_table", "가스누출감지경보기 설치계획",
    "가스 누출을 감지해 경보하는 장치를 한 줄에 하나씩 적습니다. 화학사고예방관리계획서(별지 제11호)에서 이미 입력한 감지시설은 자동으로 채워집니다.",
    _cols(
        ("감지기번호", "감지기의 고유 번호입니다. (예시) GD-001"),
        ("감지대상", "감지하려는 물질입니다."),
        ("설치장소", "감지기를 설치한 장소(설비)입니다."),
        ("작동시간", "제조사 사양서의 응답 시간입니다."),
        ("측정방식", "센서의 측정 원리입니다. (예시) 전기화학식, 적외선식"),
        ("경보설정값", "경보가 울리는 농도입니다. 단위와 함께 적습니다."),
        ("경보기 위치", "경보기가 설치된 장소입니다."),
        ("정밀도", "제조사 사양서의 정밀도입니다."),
        ("경보시 조치내용", "경보가 울렸을 때 자동으로 하거나 사람이 해야 하는 조치입니다."),
        ("유지관리", "점검·교정 주기입니다."),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
    unique="감지기번호", conditional=True,
    seed_key="cap.safety.gas_detection",
    seed_map=(("감지기번호", "감지기 번호"), ("감지대상", "검출대상 물질"), ("설치장소", "설치위치"),
              ("작동시간", "작동시간"), ("측정방식", "측정방식"), ("경보설정값", "경보 설정값"),
              ("경보기 위치", "경보 위치"), ("정밀도", "정밀도"), ("경보시 조치내용", "연동 설비·조치"),
              ("유지관리", "유지관리"), ("비고", "비고")),
)

FIREPROOF = TableSpec(
    "18", "psm.psi.fireproofing_table", "내화구조 명세",
    "화재에 견디도록 내화 처리한 설비나 지역을 적습니다. 건축물, 배관 지지대, 탱크 지지대 등이 대상입니다.",
    _cols(
        ("내화설비 또는 지역", "내화 처리한 건축물, 배관 지지대, 설비 지지대나 그 지역입니다."),
        ("내화부위", "내화 처리한 부위입니다. (예시) 기둥, 보, 지지 다리"),
        ("내화시험기준 및 시간", "내화 성능을 시험한 기준과 견디는 시간입니다. (예시) KS F 2257, 2시간"),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
    conditional=True,
)

LOCAL_EXHAUST = TableSpec(
    "19", "psm.psi.local_exhaust_table", "국소배기장치 개요",
    "유해물질이 나오는 곳에서 그 공기를 바로 빨아내는 국소배기장치를 한 줄에 하나씩 적습니다.",
    _cols(
        ("공정 또는 작업장명", "장치가 설치된 공정이나 작업장입니다."),
        ("실내외 구분", "실내인지 실외인지입니다."),
        ("발생원", "유해물질이 발생하는 설비입니다."),
        ("유해물질 종류", "발생하는 유해물질입니다."),
        ("후드형식", "후드(흡입구) 형식입니다. (예시) 부스형, 외부식"),
        ("후드 제어풍속(m/s)", "후드에서 유해물질을 빨아들이는 풍속입니다."),
        ("덕트내 반송속도(m/s)", "덕트 안에서 공기가 흐르는 속도입니다."),
        ("배풍량(m3/min)", "송풍기가 보내는 풍량입니다."),
        ("전동기용량(kW)", "송풍기 전동기의 용량입니다."),
        ("방폭형식", "폭발 위험 장소에 설치할 때의 방폭 형식입니다. 해당 없으면 '해당 없음'."),
        ("배기 및 처리순서", "빨아낸 공기가 거쳐 가는 순서입니다. (예시) 후드 → 덕트 → 스크러버 → 배기구"),
    ),
    conditional=True,
)

_ZONES = ("0종장소 선정기준(방폭형식)", "1종장소 선정기준(방폭형식)", "2종장소 선정기준(방폭형식)")
EX_EQUIPMENT = TableSpec(
    "20", "psm.psi.ex_equipment", "방폭전기/계장 기계·기구 선정기준",
    "폭발 위험이 있는 장소에 설치하는 전기·계장 기기와 그 방폭 형식을 적습니다. 0종·1종·2종 중 해당하는 장소의 형식을 적습니다.",
    _cols(
        ("설치장소 또는 공정", "기기가 설치된 장소나 공정입니다."),
        ("전기/계장 기계·기구명", "전동기, 계측 장치, 조명 등의 이름입니다."),
        (_ZONES[0], "0종 장소에 쓰는 방폭 형식입니다. 해당 없으면 비워 둡니다.", "opt"),
        (_ZONES[1], "1종 장소에 쓰는 방폭 형식입니다. 해당 없으면 비워 둡니다.", "opt"),
        (_ZONES[2], "2종 장소에 쓰는 방폭 형식입니다. 해당 없으면 비워 둡니다.", "opt"),
    ),
    one_of=(("0·1·2종 장소 선정기준 중 최소 1개", _ZONES),),
    conditional=True,
)

EXPERTS = TableSpec(
    "21", "psm.risk.team", "위험성평가 참여 전문가 명단",
    "공정위험성평가에 참여한 전문가를 한 줄에 한 명씩 적습니다.",
    _cols(
        ("책임분야", "그 전문가가 맡은 분야입니다. (예시) 공정, 기계, 전기·계장, 안전"),
        ("성명", "전문가의 이름입니다."),
        ("소속회사", "전문가가 속한 회사입니다."),
        ("직책", "전문가의 직책입니다."),
        ("주요경력", "주요 경력입니다."),
    ),
)

EMERGENCY_RESOURCES = TableSpec(
    "emergency-resources", "psm.emergency.resources", "비상장비·인력",
    "사고가 났을 때 쓰는 비상 장비와 대응 인력을 한 줄에 하나씩 적습니다. 회사만 아는 정보라서 직접 적어야 합니다.",
    _cols(
        ("구분", "장비인지 인력인지 적습니다. (예시) 장비, 인력"),
        ("명칭", "장비나 인력의 이름입니다. (예시) 공기호흡기, 화학복, 자체 소방대"),
        ("수량", "수량이나 인원수입니다."),
        ("보관위치", "장비를 두는 곳이나 인력의 근무 위치입니다."),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
)

EMERGENCY_CONTACTS = TableSpec(
    "emergency-contacts", "psm.emergency.contacts", "비상연락체계",
    "사고가 났을 때 연락할 곳을 순서대로 적습니다. 사내 담당자와 소방서·경찰서·관할 관서 등 외부 기관을 모두 포함합니다.",
    _cols(
        ("연락처 구분", "사내 또는 외부 기관입니다. (예시) 사내, 소방서, 지방고용노동관서"),
        ("기관·부서·담당자", "연락할 기관, 부서 또는 담당자 이름입니다."),
        ("전화번호", "비상시 연결되는 전화번호입니다."),
        ("연락 순서", "몇 번째로 연락하는지입니다. (예시) 1"),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
)

WASH_PPE = TableSpec(
    "wash-ppe", "psm.psi.wash_facility", "세안·세척시설 및 안전보호장구",
    "눈이나 몸을 씻는 시설과 작업자가 착용하는 보호구를 한 줄에 하나씩 적습니다.",
    _cols(
        ("구분", "세안·세척시설인지 보호구인지 적습니다. (예시) 세안기, 비상샤워, 방독면"),
        ("위치", "시설이 있는 곳이나 보호구를 두는 곳입니다."),
        ("수량", "수량입니다."),
        ("비고", "참고할 내용을 적습니다. (예시) 물질별 사용 보호구", "opt"),
    ),
)

CAP_CONTACTS = TableSpec(
    "cap-contacts", "cap.prevention.emergency_contact_system", "비상연락체계",
    "사고가 났을 때 연락할 곳을 순서대로 적습니다. 사내 담당자와 소방서·경찰서 등 외부 기관을 모두 포함합니다.",
    _cols(
        ("연락처 구분", "사내 또는 외부 기관입니다. (예시) 사내, 소방서, 관할 환경 관서"),
        ("기관·부서·담당자", "연락할 기관, 부서 또는 담당자 이름입니다."),
        ("전화번호", "비상시 연결되는 전화번호입니다."),
        ("연락 순서", "몇 번째로 연락하는지입니다."),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
)

CAP_RESOURCES = TableSpec(
    "cap-resources", "cap.internal.response_equipment", "방재 장비·인력",
    "사고에 대응할 때 쓰는 장비와 인력을 한 줄에 하나씩 적습니다. 회사만 아는 정보라서 직접 적어야 합니다.",
    _cols(
        ("구분", "장비인지 인력인지 적습니다. (예시) 장비, 인력"),
        ("명칭", "장비나 인력의 이름입니다. (예시) 공기호흡기, 흡착포, 방재팀"),
        ("수량", "수량이나 인원수입니다."),
        ("보관위치", "장비를 두는 곳이나 인력의 근무 위치입니다."),
        ("비고", "참고할 내용을 적습니다.", "opt"),
    ),
)

SPECS: dict[str, TableSpec] = {spec.form_no: spec for spec in (
    CAP_CONTACTS, CAP_RESOURCES, EMERGENCY_RESOURCES, EMERGENCY_CONTACTS, WASH_PPE,
    MACHINERY, PIPING, RELIEF, INTERLOCK, FIRE_FIGHTING, FIRE_DETECTION, GAS_ALARM, FIREPROOF, LOCAL_EXHAUST,
    EX_EQUIPMENT, EXPERTS)}
APPLICABILITY_KEY = "psm.psi.form_applicability"
APPLICABLE, NOT_APPLICABLE = "적용", "해당 없음"


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def seeded(project: Stage2Project, form_no: str) -> list[dict[str, str]]:
    """화학사고예방관리계획서에서 이미 입력한 같은 성격의 표를 이 서식 열로 옮긴다(저장 전 미리 채움)."""
    spec = SPECS[form_no]
    if not spec.seed_key:
        return []
    record = project.get_field(spec.seed_key)
    if record is None or not isinstance(record.value, list):
        return []
    return [{mine: _clean(row.get(theirs)) for mine, theirs in spec.seed_map}
            for row in record.value if isinstance(row, Mapping) and any(_clean(v) for v in row.values())]


def rows(project: Stage2Project, form_no: str) -> list[dict[str, str]]:
    spec = SPECS[form_no]
    record = project.get_field(spec.key)
    if record is None or not isinstance(record.value, list):
        return seeded(project, form_no)
    return [{c: _clean(row.get(c)) for c in spec.column_ids()} for row in record.value if isinstance(row, Mapping)]


def save(project: Stage2Project, form_no: str, new_rows: list[Mapping[str, Any]]) -> int:
    spec = SPECS[form_no]
    cleaned = [{c: _clean(row.get(c)) for c in spec.column_ids()} for row in new_rows]
    cleaned = [row for row in cleaned if any(row.values())]
    project.set_field(spec.key, f"{spec.title}(작성대)", cleaned, "USER_CONFIRMED")
    return len(cleaned)


def needs(project: Stage2Project, form_no: str) -> list[str]:
    spec = SPECS[form_no]
    if spec.conditional and applicability(project, form_no)[0] == NOT_APPLICABLE:
        return []
    saved = project.get_field(spec.key)
    current = rows(project, form_no) if saved is not None else []
    if not current:
        return [f"{spec.title}에 적은 행이 없습니다."]
    out = []
    for index, row in enumerate(current, start=1):
        missing = [c.label for c in spec.columns if c.required and not row[c.id]]
        if missing:
            out.append(f"{index}행: {', '.join(missing)}이(가) 비어 있습니다.")
    for message, columns in spec.one_of:
        for index, row in enumerate(current, start=1):
            if not any(row[c] for c in columns):
                out.append(f"{index}행: {message}가 필요합니다.")
    if spec.unique:
        seen: set[str] = set()
        for row in current:
            value = "".join(row[spec.unique].split()).lower()
            if value and value in seen:
                out.append(f"{row[spec.unique]}이(가) 두 번 이상 적혀 있습니다.")
            seen.add(value)
    return out


# ---- 조건부 서식: 해당하는 사업장만 작성한다 ------------------------------------------------------------------


def applicability(project: Stage2Project, form_no: str) -> tuple[str, str]:
    record = project.get_field(APPLICABILITY_KEY)
    if record is None or not isinstance(record.value, list):
        return "", ""
    for row in record.value:
        if isinstance(row, Mapping) and _clean(row.get("서식번호")) == form_no:
            return _clean(row.get("적용여부")), _clean(row.get("확인근거"))
    return "", ""


def save_applicability(project: Stage2Project, form_no: str, decision: str, basis: str) -> None:
    record = project.get_field(APPLICABILITY_KEY)
    kept = [dict(r) for r in (record.value if record is not None and isinstance(record.value, list) else [])
            if isinstance(r, Mapping) and _clean(r.get("서식번호")) != form_no]
    kept.append({"서식번호": form_no, "적용여부": decision, "확인근거": basis.strip()})
    project.set_field(APPLICABILITY_KEY, "PSM 조건부 서식 적용여부", kept, "USER_CONFIRMED")
