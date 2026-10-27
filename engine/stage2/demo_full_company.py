"""화학사고예방관리계획서를 처음부터 내려받기까지 직접 해 보는 가상 회사 자료(작은 회사, 모든 별지용 자료 포함).

큰 연습 자료(demo_company)는 ‘자료 정리’가 복잡한 경우에 얼마나 견디는지 보는 용도이고,
이 자료는 사람이 화면을 따라가며 계획서 전체를 한 번 끝까지 써 보는 용도입니다.
그래서 제품 3개·설비 4대로 작게 만들고, 각 별지에서 참고할 값을 회사 문서 형태로 넣었습니다.
별지 제1·3~7·9~11호와 서술형은 파일만 올려도 채워집니다(tests/test_evidence_catalog_reading.py). 별지 제8호 지도 조사와 제12~15호 시나리오는 아직 파일만으로 끝나지 않으며, 누락 검사로 이를 확인합니다.

모든 값은 이 파일의 DATA 하나에서 나옵니다. 문서·안내서·자동 점검(tests/test_demo_full_company.py)이 같은 값을 씁니다.
회사·사람·주소·번호·운전값은 모두 허구입니다(물질명·CAS 번호만 실제). 실제 운전·평가·제출에 쓸 수 없습니다.

주소를 주면(full_demo_zip(address=...)) 그 실제 주소에 이 가상 회사가 있다고 보고 자료를 만듭니다. 이때 별지 제8호 주변
보호대상은 지어낸 목록 대신 그 주소로 지도 조회(브이월드·카카오)와 확인을 해서 채우도록 안내합니다. 주소는 저장소에 넣지
않고 내려받는 사람이 그때그때 넣습니다.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO, StringIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

COMPANY = "가상 새솔화학(주)"

DATA = {
    "company": {
        "사업장명": COMPANY, "주소": "울산광역시 남구 가상산업로 100 (가상 주소)",
        "registration_no": "000-81-00000", "representative": "김가상", "industrial_complex": "가상 국가산업단지",
        "contact": "052-000-0000", "joint": "단독제출", "other_review": "미해당", "residents": "있음",
        "recent_accident": "없음", "writer_department": "안전환경팀", "writer_name": "이담당",
        "writer_contact": "052-000-0001", "writer_email": "safety@example.com", "작성수준": "2군",
        "제출구분": "신규제출", "제출 사유": "최초 제출(화학사고예방관리계획서 작성 대상 확인)",
        "단위공장명": "가상 새솔화학 제1공장",
    },
    "process": {
        "총괄 개요": "제1공장 1개 단위공장. 톨루엔 저장탱크 1기, 염산 저장탱크 1기, 수지 반응기 1기, 액화암모니아 용기 보관소 1개소.",
        "공정개요": "톨루엔을 저장탱크(TK-01)에서 반응기(RX-01)로 이송해 수지를 합성한다. 염산(TK-02)은 중화 공정에 쓰고, "
                    "액화암모니아(CY-01)는 용기째 보관하다 배기가스 처리설비에 공급한다.",
        "입출하 시설 수": "1",
        "단위공장 개요": "제1공장: 저장(TK-01, TK-02) → 반응(RX-01) → 제품 포장. 암모니아 용기 보관소(CY-01)는 공장 북쪽 별도 구역.",
    },
    "products": [
        # 코드, 제품명, CAS, 함량(%), 성상, 비중, SDS 물성(별지 제6·7호)
        {"code": "P-01", "name": "가상 톨루엔", "cas": "108-88-3", "conc": 99.5, "state": "액체", "density": 0.87,
         "props": {"폭발한계 하한": "1.1 %", "폭발한계 상한": "7.1 %", "독성구분 항목": "흡입", "독성구분": "구분 4",
                   "위험노출수준": "ERPG-2 300 ppm", "허용농도값": "50 ppm (TWA)", "증기압": "22", "분자량": "92.14", "부식성": "무",
                   "SDS 파일명": "가상톨루엔_SDS_2026.pdf", "SDS 개정일": "2026-01-10"},
         "hazard": {"인체유해성": "흡인 유해성 구분 1, 생식독성 구분 2", "물리적 위험성": "인화성 액체 구분 2",
                    "환경유해성": "만성 수생환경 유해성 구분 3", "선정 사유": "취급량이 가장 많은 인화성 액체(화재·폭발 대표물질)", "출처": "회사 제품 SDS(가상)"}},
        {"code": "P-02", "name": "가상 염산 35%", "cas": "7647-01-0", "conc": 35.0, "state": "액체", "density": 1.17,
         "props": {"폭발한계 하한": "해당 없음", "폭발한계 상한": "해당 없음", "독성구분 항목": "흡입", "독성구분": "구분 3",
                   "위험노출수준": "ERPG-2 20 ppm", "허용농도값": "1 ppm (C)", "증기압": "105", "분자량": "36.46", "부식성": "유",
                   "SDS 파일명": "가상염산35_SDS_2025.pdf", "SDS 개정일": "2025-11-20"},
         "hazard": {"인체유해성": "피부부식성 구분 1B, 급성독성(흡입) 구분 3", "물리적 위험성": "금속부식성 물질 구분 1",
                    "환경유해성": "급성 수생환경 유해성 구분 3", "선정 사유": "부식성·흡입독성 물질", "출처": "회사 제품 SDS(가상)"}},
        {"code": "P-03", "name": "가상 액화암모니아", "cas": "7664-41-7", "conc": 99.9, "state": "기체·고압가스", "density": 0.68,
         "props": {"폭발한계 하한": "15 %", "폭발한계 상한": "28 %", "독성구분 항목": "흡입", "독성구분": "구분 3",
                   "위험노출수준": "ERPG-2 150 ppm", "허용농도값": "25 ppm (TWA)", "증기압": "6430", "분자량": "17.03", "부식성": "무",
                   "SDS 파일명": "가상액화암모니아_SDS_2026.pdf", "SDS 개정일": "2026-02-01"},
         "hazard": {"인체유해성": "급성독성(흡입) 구분 3, 피부부식성 구분 1B", "물리적 위험성": "고압가스(액화가스)",
                    "환경유해성": "급성 수생환경 유해성 구분 1", "선정 사유": "독성 가스(독성 누출 대표물질)", "출처": "회사 제품 SDS(가상)"}},
    ],
    "facilities": [
        # 별지 제1호·설비대장, 제9호 사양, 제10호 확산방지설비, 별지 제1호 추가 입력
        {"id": "TK-01", "name": "가상 톨루엔 저장탱크", "type": "저장탱크", "process": "", "product": "P-01",
         "capacity_m3": 50, "inventory_kg": 37000, "pressure": 0.01, "temperature": 25, "state": "액체", "density": 0.87,
         "spec": {"최대 연결구 크기(mm)": "80", "설계압력": "0.05", "운전압력": "0.01", "설계온도": "60", "운전온도": "25", "비고": "P&ID 가상-001"},
         "dike": {"적용여부": "예", "설비형태": "저장", "확산방지설비 종류": "방류벽", "내부 길이(m)": "10", "내부 폭(m)": "8",
                  "유효높이(m)": "1.0", "내부 차감용적(m3)": "2", "비고": "철근콘크리트 방류벽"},
         "form1": {}},
        {"id": "TK-02", "name": "가상 염산 저장탱크", "type": "저장탱크", "process": "", "product": "P-02",
         "capacity_m3": 20, "inventory_kg": 19900, "pressure": 0.01, "temperature": 25, "state": "액체", "density": 1.17,
         "spec": {"최대 연결구 크기(mm)": "50", "설계압력": "0.05", "운전압력": "0.01", "설계온도": "60", "운전온도": "25", "비고": "P&ID 가상-002"},
         "dike": {"적용여부": "예", "설비형태": "저장", "확산방지설비 종류": "방류벽", "내부 길이(m)": "7", "내부 폭(m)": "5",
                  "유효높이(m)": "1.0", "내부 차감용적(m3)": "1", "비고": "내산 라이닝 방류벽"},
         "form1": {}},
        {"id": "RX-01", "name": "가상 수지 반응기", "type": "제조·사용시설", "process": "반응", "product": "P-01",
         "capacity_m3": 5, "inventory_kg": 3700, "pressure": 0.3, "temperature": 80, "state": "액체", "density": 0.87,
         "spec": {"최대 연결구 크기(mm)": "50", "설계압력": "0.5", "운전압력": "0.3", "설계온도": "150", "운전온도": "80", "비고": "P&ID 가상-003"},
         "dike": {"적용여부": "예", "설비형태": "제조", "확산방지설비 종류": "방지턱", "내부 길이(m)": "5", "내부 폭(m)": "5",
                  "유효높이(m)": "0.3", "내부 차감용적(m3)": "0.5", "비고": "반응기실 바닥 방지턱"},
         "form1": {"별표4 기준함량(%)": "99.5", "함량근거": "가상 공정배합표 2026-01"}},
        {"id": "CY-01", "name": "가상 액화암모니아 용기 보관소", "type": "보관시설", "process": "", "product": "P-03",
         "capacity_m3": 1.88, "inventory_kg": 1000, "pressure": 0.86, "temperature": 25, "state": "기체·고압가스", "density": 0.68,
         "spec": {"최대 연결구 크기(mm)": "15", "설계압력": "2.94", "운전압력": "0.86", "설계온도": "50", "운전온도": "25", "비고": "500kg 용기 2기"},
         "dike": {"적용여부": "해당 없음", "설비형태": "보관", "비고": "기체(액화가스) 용기 보관소 — 확산방지설비 대상 아님"},
         "form1": {"직접확인 최대보유량": "1000", "질량단위": "kg", "직접확인 근거": "500kg 용기 2기 × 충전량(가상 용기 명판)",
                   "보관계획도 최대량": "1000", "일일최대보관량": "1000"}},
    ],
    "dike_rule": {"비율(%)": "110", "근거": "최대 탱크 용량의 110% (가상 사내 기준)"},
    "detectors": [
        {"감지기 번호": "GD-01", "검출대상 물질": "가상 액화암모니아", "설치위치": "CY-01 용기 보관소 내부", "작동시간": "30초 이내",
         "측정방식": "전기화학식", "경보 설정값": "25 ppm", "경보 위치": "중앙통제실·현장", "연동여부": "예",
         "연동 설비·조치": "배기팬 자동 가동, 경광등", "정밀도": "±5%", "유지관리": "월 1회 교정", "비고": ""},
        {"감지기 번호": "GD-02", "검출대상 물질": "가상 염산 35%", "설치위치": "TK-02 방류벽 안", "작동시간": "30초 이내",
         "측정방식": "전기화학식", "경보 설정값": "2 ppm", "경보 위치": "중앙통제실", "연동여부": "아니오",
         "연동 설비·조치": "", "정밀도": "±5%", "유지관리": "월 1회 교정", "비고": "염화수소 검지"},
        {"감지기 번호": "GD-03", "검출대상 물질": "가상 톨루엔", "설치위치": "TK-01·RX-01 사이", "작동시간": "30초 이내",
         "측정방식": "접촉연소식", "경보 설정값": "LEL 20%", "경보 위치": "중앙통제실·현장", "연동여부": "예",
         "연동 설비·조치": "이송펌프 정지", "정밀도": "±3% LEL", "유지관리": "월 1회 교정", "비고": ""},
    ],
    "surroundings": [
        {"보호대상 명칭": "가상 초등학교", "보호대상 구분": "갑종", "세부유형": "교육·연구시설", "주소·위치": "사업장 남동쪽",
         "사업장 경계와 거리(m)": "420", "GIS/현장 근거": "가상 현장 확인(2026-03)", "거주민수": "", "근로자수": "40"},
        {"보호대상 명칭": "가상 아파트 단지", "보호대상 구분": "갑종", "세부유형": "주택", "주소·위치": "사업장 남쪽",
         "사업장 경계와 거리(m)": "350", "GIS/현장 근거": "가상 현장 확인(2026-03)", "거주민수": "1200", "근로자수": ""},
        {"보호대상 명칭": "가상 물류창고", "보호대상 구분": "을종", "세부유형": "공업시설", "주소·위치": "사업장 동쪽",
         "사업장 경계와 거리(m)": "60", "GIS/현장 근거": "가상 현장 확인(2026-03)", "거주민수": "", "근로자수": "25"},
        {"보호대상 명칭": "가상천", "보호대상 구분": "환경수용체", "세부유형": "하천", "주소·위치": "사업장 서쪽",
         "사업장 경계와 거리(m)": "180", "GIS/현장 근거": "가상 현장 확인(2026-03)", "거주민수": "", "근로자수": ""},
    ],
    "survey": {"source": "가상 현장 조사(2026-03) 및 지도 확인", "method": "사업장 경계에서 500m 반경 현장 확인", "map_numbers": "1,2,3,4"},
    "scenario_inputs": {
        # 별지 제12호 사고시나리오 목록에 더 적는 값(설비번호별)
        "TK-01": {"액위(m)": "3.5", "경계까지 거리(m)": "45", "누출지점 배관길이(m)": "0.5", "연소열": "40500", "비점": "110.6",
                  "액체비열": "1.7", "기화열": "363"},
        "TK-02": {"액위(m)": "2.5", "경계까지 거리(m)": "30", "누출지점 배관길이(m)": "0.5"},
        "RX-01": {"경계까지 거리(m)": "70", "누출지점 배관길이(m)": "0.5", "연소열": "40500", "비점": "110.6",
                  "액체비열": "1.7", "기화열": "363"},
        "CY-01": {"경계까지 거리(m)": "25", "누출지점 배관길이(m)": "0.3", "증발잠열(kcal/kg)": "297", "액체비열(kcal/kg·℃)": "1.12",
                  "증기밀도(kg/m3)": "6.9"},
    },
    "frequency": {
        # 별지 제14호: 시나리오의 대상 설비번호별 개시사건 개수·완화장치
        "TK-01": {"배관누출": "2", "플랜지 등의 가스켓 파손": "4", "펌프/컴프레서 누출": "1", "상압 탱크 파열 및 누출": "1",
                  "개수 산정근거": "P&ID 가상-001 검토", "수동적 완화장치": "방류벽", "능동적 완화장치": "", "안전성확보설비 증빙": "가상 방류벽 준공도면 2025-05"},
        "TK-02": {"배관누출": "1", "플랜지 등의 가스켓 파손": "3", "상압 탱크 파열 및 누출": "1",
                  "개수 산정근거": "P&ID 가상-002 검토", "수동적 완화장치": "방류벽", "능동적 완화장치": "", "안전성확보설비 증빙": "가상 방류벽 준공도면 2025-05"},
        "RX-01": {"배관누출": "2", "플랜지 등의 가스켓 파손": "6", "안전밸브 오작동 및 조기개방": "1", "냉각수 손실": "1",
                  "개수 산정근거": "P&ID 가상-003 검토", "수동적 완화장치": "", "능동적 완화장치": "", "안전성확보설비 증빙": ""},
        "CY-01": {"배관누출": "1", "플랜지 등의 가스켓 파손": "2", "고압용기파열": "2",
                  "개수 산정근거": "용기 2기·충전 배관 검토", "수동적 완화장치": "", "능동적 완화장치": "가스감지기와 자동차단밸브의 연동",
                  "안전성확보설비 증빙": "가상 연동 시험성적서 2026-02"},
    },
    "narrative": {
        "safety_management": {"책임자": "공장장", "조직": "안전환경팀(팀장 1, 담당 2)이 안전관리 총괄", "회의": "월 1회 안전점검 회의"},
        "training": {"대상": "전 직원 및 협력업체 상주 인원", "주기": "분기 1회 교육, 반기 1회 비상대응 훈련", "방법": "집합교육과 현장 모의훈련"},
        "self_inspection": {"대상": "TK-01·TK-02·RX-01·CY-01과 배관·감지기", "주기": "주 1회 순회점검, 월 1회 정밀점검", "방법": "점검표 작성 후 전산 보관"},
        "change_management": {"절차": "변경요청서 → 위험성 검토 → 공장장 승인 → 시행 → 교육", "담당": "안전환경팀장", "기록": "변경관리대장에 5년 보관"},
        "emergency_org": {"총괄": "공장장(부재 시 생산팀장)", "대응반": "방제반·구조반·연락반", "교대": "야간·휴일은 당직 조장이 초기 대응 후 공장장에게 보고"},
        "command_center": {"위치": "본관 1층 중앙통제실", "운영": "사고 시 즉시 비상통제실로 전환해 24시간 운영", "담당": "연락반장"},
        "shutdown": {"권한자": "현장 조장 이상", "판단기준": "가스감지기 경보 또는 누출 확인 시", "방법": "비상정지 버튼으로 이송펌프·반응기 가열 정지"},
        "communication": {"수단": "사내 방송, 비상벨, 무전기", "방법": "발견자 → 중앙통제실 → 전 직원 방송", "담당": "연락반장"},
        "recovery": {"책임": "생산팀장", "순서": "누출 차단 → 중화·흡착 → 폐기물 처리 → 설비 점검 후 재가동", "환경조치": "오염 토양·물 시료 채취 후 처리 업체 위탁"},
    },
    "emergency": {
        # 별지 제16호 내부 비상대응(2군)
        "contact": "공장장 김가상 010-0000-0001, 안전환경팀장 이담당 010-0000-0002, 당직실 052-000-0003",
        "organization": "총괄: 공장장 / 방제반: 생산팀(누출 차단·중화) / 구조반: 안전환경팀(인명 구조·응급처치) / 연락반: 총무팀(신고·전파)",
        "shutdown": "현장 조장 이상이 가스감지기 경보나 누출을 확인하면 비상정지 버튼으로 이송펌프와 반응기 가열을 멈춘다.",
        "personnel": "방재 인원 12명, 공기호흡기 6조, 화학보호복 6벌, 중화제(소석회) 500kg, 흡착포 200장, 이동식 펌프 1대",
        "alarm": "비상벨과 사내 방송으로 전 직원에게 알리고, 경광등을 켠다.",
        "first_aid": "저장탱크: 이송 정지 후 방류벽 안 누출물 회수. 반응기: 가열·교반 정지 후 냉각. 용기 보관소: 밸브 차단 후 물분무로 희석.",
        "investigation": "사고 후 7일 안에 원인조사팀을 꾸려 근본원인을 분석하고 재발방지 대책을 세워 교육한다.",
        "recovery": "누출 차단 → 중화·흡착 → 폐기물 처리 → 설비 점검 → 공장장 승인 후 재가동.",
    },
}

def company(address: str = "", complex_name: str = "") -> dict:
    """회사 정보. 주소를 주면 그 주소(실제 위치)로 바꾸고 산업단지는 넣은 이름(없으면 ‘해당 없음’)으로 씁니다."""
    c = dict(DATA["company"])
    address = " ".join(str(address or "").split())
    if address:
        c["주소"] = address
        c["industrial_complex"] = " ".join(str(complex_name or "").split()) or "해당 없음"
    return c


_FORM8_FICTION = f"""\
 - 별지 제8호: 07_주변보호대상_조사표.xlsx(‘조사 방법’ 시트 포함)와 07_주변보호대상_지도.png는 지도 조사 화면에서 쓰는 자료입니다.
   지도 조사 화면에서 ‘기존 보호대상 목록’으로 올려 구분하기 → 검토 항목 4개 확인, 지도 번호 「{DATA['survey']['map_numbers']}」"""

_FORM8_REAL = """\
 - 별지 제8호 (실제 주소로 조사 — 회사에서 처음 쓸 때와 같은 순서. 지도 조사 화면을 다시 연결하면 이 순서로 합니다)
   ① ‘1. 주소 조사·지도 정리’ 단계에서 ‘주소로 주변자료 조사’(카카오 장소명도 같이 보려면 체크).
   ② 지도에서 사업장 부지 경계를 그립니다. 가상 회사라 실제 부지 도면이 없으니 주소점 둘레에 공장 부지를
      150m × 100m쯤으로 그리고, ‘경계를 확인한 도면·지도와 날짜’에 「연습용 가상 부지 경계, 오늘 날짜」를 적고
      확인 체크 → ‘사업장 경계 저장·내외부 분석’.
   ③ 아래 ‘시설 묶음 후보’에서 학교·아파트·병원·하천처럼 보호대상이 될 만한 것을 골라 ‘시설 묶음 확인·저장’ →
      ‘별지 제8호에 미검토 후보로 추가’. 지도에 없는데 실제로 있는 대상은 다음 단계 표에 새 행으로 넣습니다.
   ④ ‘2. 보호대상 목록’에서 ‘갑종·을종·환경수용체 구분하기’. 비어 있는 구분·실제 거리(지도의 최소거리 참고값을 보고
      확인)·거주민수·근로자수를 채웁니다(모르면 거주민수·근로자수는 비워 두면 0으로 셉니다).
   ⑤ 지도·현장 확인 기록: 검토 항목 4개, 사용자료 「브이월드 공간자료·항공사진, 조회일」, 방법 「그린 부지 경계에서
      500m 안을 지도로 확인」, 지도 번호(목록 순번), ‘확인한 지도·도면 파일’에는 번호를 표시한 지도 화면 캡처(PNG).
   키가 없거나 조회가 안 되면: 07_주변보호대상_조사표.xlsx(빈 양식)에 지도 서비스로 직접 찾은 대상을 적어
   ‘기존 보호대상 목록’으로 올리고 ④부터 하면 됩니다."""


def readme(address: str = "", complex_name: str = "") -> str:
    """단계별 안내서. 주소를 주면 그 주소로 별지 제8호를 지도 조회해 채우는 안내가 들어갑니다."""
    c = company(address, complex_name)
    real = bool(address and address.strip())
    notice = ("주소만 직접 넣은 실제 주소이고, 회사·사람·번호·운전값·설비는 모두 허구입니다(물질명·CAS 번호만 실제)."
              if real else "모든 회사·사람·주소·번호·운전값은 허구입니다(물질명·CAS 번호만 실제).")
    keys = ("\n   주소 조회를 쓰려면 실행 환경(.env 또는 Streamlit secrets)에 VWORLD_API_KEY와 발급 때 등록한 VWORLD_DOMAIN이"
            "\n   있어야 합니다(카카오 장소명까지 보려면 KAKAO_REST_API_KEY도)." if real else "")
    return f"""{COMPANY} — 화학사고예방관리계획서 끝까지 연습 자료

{notice} 실제 운전·평가·제출에 쓸 수 없습니다.
ZIP의 answer_key.json에 물질·설비의 원래 값을 보관합니다. 실제 주소를 넣은 경우 주변 보호대상 정답은
만들어 두지 않았습니다. 조사 결과를 지도와 대조하세요.

[준비]
0. 왼쪽 ‘참고 > 규정 DB 관리’에서 최신본 업데이트로 법령 기준표(별표 1~4)를 승인해 두세요.
   이게 없으면 최대보유량 계산·사고시나리오 대상 판정·별지 제6호 물질구분이 ‘승인 DB 필요’로 멈춥니다.{keys}

[1] 파일 올리기 (왼쪽 ‘사업장 업무’) — 서식에 직접 적지 않습니다
 1-1. ‘새 사업장 만들기’: 사업장 이름 「{COMPANY}」, 주소 「{c['주소']}」
 1-2. ① 자료 올리기: 아래 엑셀·워드 파일을 한 번에 선택하고 ‘자료 읽기’를 누르세요. 파일마다 종류를 알아보고 읽습니다.
      01_제품목록.xlsx, 02_설비대장.xlsx, 03_사업장_일반정보.docx, 04_공정설명서.docx,
      05_SDS_물성표.xlsx, 06_설비사양_안전설비.xlsx, 09_안전관리_비상대응계획.docx
      같은 내용의 한글판(HWPX·HWP 5.0)도 넣었습니다: 01_제품목록_한글판.hwpx, 02_설비대장_한글판.hwpx,
      03_사업장_일반정보_한글판.hwpx, 04_공정설명서_한글판.hwpx, 09_안전관리_비상대응계획_한글판.hwpx와
      같은 다섯 파일의 _한글판.hwp. 형식 비교용 복제본이므로 한 사업장에는 한 형식만 올리세요.
      PNG 그림(06_가스감지기_배치도.png, 07_주변보호대상_지도.png)은 도면·근거 첨부용이라 값으로 읽지 않습니다.
 1-3. ② 파일별 보완 요청: ‘화학사고예방관리계획서에 필요한 사실’ 표에서 O(파일에서 찾음)·빈칸·⚠ 충돌을 봅니다.
      빈칸은 ‘올릴 파일’에 ‘고칠 점’의 항목 이름으로 적어 다시 올리거나, ‘엑셀 업로드 양식’을 받아 채워 올립니다.
      파일을 고쳐 같은 이름으로 다시 올리면 예전 파일을 새 파일로 바꿉니다. 잘못 올린 파일은 ①의 ‘이 파일 빼기’로 뺍니다.
 1-4. ④ 보내기·진행 현황: 읽은 값은 자동으로 초안에 들어가 있습니다. 서술형(사전관리방침·비상대응계획)은 09 파일의 사실로
      초안이 만들어지고, 근거가 없는 부분은 ‘[확인 필요]’로 남습니다.
 1-5. 왼쪽 ‘초안 내려받기’에서 규정서식 초안과 내부 초안 DOCX를 받아 고쳐 씁니다.

[2] 파일이 채우는 별지
 - 맨 위 작성수준: {DATA['company']['작성수준']} (‘사업장 판정하기’의 판정 결과를 씁니다. 03 파일의 작성수준은 비교만 합니다)
 - 별지 제1호: 02_설비대장.xlsx + 06_설비사양_안전설비.xlsx ‘별지1_추가입력’ 시트(RX-01 산정 기준 함량·근거, CY-01 직접 확인한 최대보유량 등)
 - 별지 제3호: 03_사업장_일반정보.docx
 - 별지 제4·5호: 04_공정설명서.docx
 - 별지 제6호: 05_SDS_물성표.xlsx의 ‘별지6_물성’ 시트(제품코드가 없어도 CAS 번호로 01 제품목록의 제품에 이어 붙임)
 - 별지 제7호: 05_SDS_물성표.xlsx의 ‘별지7_대표물질’ 시트(선정 사유를 적은 물질이 대표물질)
{_FORM8_REAL if real else _FORM8_FICTION}
 - 별지 제9호: 06_설비사양_안전설비.xlsx의 ‘별지9_설비사양’ 시트(머리글에 단위를 적어 두어 단위를 묻지 않음)
 - 별지 제10호: 같은 파일 ‘별지10_확산방지설비’ 시트와 ‘별지10_공통기준’ 시트(공통 필요용량 비율 110%)
 - 별지 제11호: 같은 파일 ‘별지11_가스감지기’ 시트
 - 별지 제16호·서술형: 09_안전관리_비상대응계획.docx

[3] 아직 파일만으로 끝나지 않는 일
 - 별지 제8호 주변 보호대상: 지도 조사·구분·검토 기록이 필요합니다. 지도 조사 화면은 지금 메뉴에 연결돼 있지 않습니다(다음 작업).
 - 별지 제12~15호 사고시나리오·위험도: 08_사고시나리오_검토자료.xlsx는 근거 자료로 보관만 합니다. 시나리오 계산 화면도 메뉴에서 빠져 있습니다.
 - 별지 제2호: 왼쪽 ‘제출·변경·이행점검’에서 제출구분 「{DATA['company']['제출구분']}」, 사유 「{DATA['company']['제출 사유']}」,
   단위공장명 「{DATA['company']['단위공장명']}」을 확인합니다. 제출 전에 ‘버전 관리’에서 v1.0(신규제출)으로 저장해 두세요.

[4] 점검·내보내기
 - 내려받은 문서는 언제나 초안입니다. 이 자료만 올려서는 법정 서식이 완성되지 않습니다(승인 DB·지도 조사·시나리오가 남음).
 - 내부 초안 끝의 ‘프로그램 보완 안내’에 남은 일이 정리됩니다.
"""


README = readme()


# ---------------------------------------------------------------- 문서 만들기

def _book(sheets):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    book = Workbook()
    book.remove(book.active)
    for title, (headers, rows) in sheets.items():
        sheet = book.create_sheet(title)
        sheet.append(list(headers))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append([row.get(h, "") for h in headers])
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = max(12, min(40, max(len(str(c.value or "")) for c in column) + 4))
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def _doc(title, sections, notice="가상 회사 연습 자료입니다. 모든 내용은 허구입니다."):
    from docx import Document
    doc = Document()
    doc.add_heading(title, level=1)
    doc.add_paragraph(notice)
    for heading, rows in sections:
        doc.add_heading(heading, level=2)
        if isinstance(rows, str):
            doc.add_paragraph(rows)
            continue
        table = doc.add_table(rows=0, cols=2)
        table.style = "Table Grid"
        for label, value in rows:
            cells = table.add_row().cells
            cells[0].text, cells[1].text = str(label), str(value)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _hwpx_table(title, headers, rows):
    """원본 엑셀과 같은 값을 담은 독립적인 한글(HWPX) 입력 샘플."""
    from hwpx import HwpxDocument
    doc = HwpxDocument.new()
    doc.add_paragraph(title)
    doc.add_paragraph("가상 회사 연습 자료. 실제 운전·제출에 사용 금지.")
    table = doc.add_table(len(rows) + 1, len(headers))
    for col, header in enumerate(headers):
        table.set_cell_text(0, col, header)
    for row_no, row in enumerate(rows, 1):
        for col, header in enumerate(headers):
            table.set_cell_text(row_no, col, str(row.get(header, "")))
    return doc.to_bytes()


def _hwpx_from_docx(content):
    """한글 문서 형식 시험용: 원문 표와 문단을 HWPX로 복제한다."""
    from docx import Document
    from hwpx import HwpxDocument
    source = Document(BytesIO(content))
    target = HwpxDocument.new()
    for p in source.paragraphs:
        if p.text.strip():
            target.add_paragraph(p.text)
    for old in source.tables:
        new = target.add_table(len(old.rows), len(old.columns))
        for r, row in enumerate(old.rows):
            for c, cell in enumerate(row.cells):
                new.set_cell_text(r, c, cell.text)
    return target.to_bytes()


def _sds_state(state):
    """별지 제6호의 물질 상태 칸은 기체·액체·고체로 고릅니다(액화가스도 ‘기체’)."""
    return "기체" if state.startswith("기체") else state


def _name(code):
    return next(p["name"] for p in DATA["products"] if p["code"] == code)


def _files(address="", complex_name=""):
    c, pr = company(address, complex_name), DATA["process"]
    real = c["주소"] != DATA["company"]["주소"]
    products, facilities = DATA["products"], DATA["facilities"]
    files = {}
    files["01_제품목록.xlsx"] = _book({"제품목록": (
        ("제품코드", "제품명", "CAS 번호", "함량(%)", "성상", "비중"),
        [{"제품코드": p["code"], "제품명": p["name"], "CAS 번호": p["cas"], "함량(%)": p["conc"], "성상": p["state"], "비중": p["density"]}
         for p in products])})
    files["02_설비대장.xlsx"] = _book({"설비대장": (
        ("설비번호", "설비명", "시설구분", "공정구분", "취급제품", "용량(m3)", "최대보유량(kg)", "운전압력(MPa)", "운전온도(℃)", "물질상태", "비중"),
        [{"설비번호": f["id"], "설비명": f["name"], "시설구분": f["type"], "공정구분": f["process"], "취급제품": f["product"],
          "용량(m3)": f["capacity_m3"], "최대보유량(kg)": f["inventory_kg"], "운전압력(MPa)": f["pressure"],
          "운전온도(℃)": f["temperature"], "물질상태": f["state"], "비중": f["density"]} for f in facilities])})
    files["01_제품목록_한글판.hwpx"] = _hwpx_table("제품 목록·성분 확인", ("제품코드", "제품명", "CAS 번호", "함량(%)", "성상", "비중"),
        [{"제품코드": p["code"], "제품명": p["name"], "CAS 번호": p["cas"], "함량(%)": p["conc"],
          "성상": p["state"], "비중": p["density"]} for p in products])
    files["02_설비대장_한글판.hwpx"] = _hwpx_table("설비목록·설비대장·운전조건", ("설비번호", "설비명", "시설구분", "취급제품", "용량(m3)", "최대보유량(kg)", "운전압력(MPa)", "운전온도(℃)"),
        [{"설비번호": f["id"], "설비명": f["name"], "시설구분": f["type"], "취급제품": f["product"],
          "용량(m3)": f["capacity_m3"], "최대보유량(kg)": f["inventory_kg"],
          "운전압력(MPa)": f["pressure"], "운전온도(℃)": f["temperature"]} for f in facilities])
    files["03_사업장_일반정보.docx"] = _doc(f"{COMPANY} 사업장 일반정보", [
        ("별지 제3호 · 사업장 일반정보", [
            ("사업자 등록번호", c["registration_no"]), ("대표자", c["representative"]), ("우편번호/주소", c["주소"]),
            ("산업단지", c["industrial_complex"]), ("대표전화", c["contact"]), ("공동비상대응계획 수립 여부", c["joint"]),
            ("유사제도 심사결과 활용", c["other_review"]), ("총괄영향범위내 주민여부", c["residents"]),
            ("최근 3년간 화학사고 발생 여부", c["recent_accident"]), ("작성자 소속 부서", c["writer_department"]),
            ("작성자 성명", c["writer_name"]), ("담당자 연락처", c["writer_contact"]), ("담당자 메일주소", c["writer_email"])]),
        ("작성수준 · 제출 정보(별지 제1·2호)", [
            ("작성수준", c["작성수준"]), ("제출구분", c["제출구분"]), ("제출 사유", c["제출 사유"]), ("단위공장명", c["단위공장명"])]),
    ], notice="가상 회사 연습 자료입니다. 주소만 실제이고 나머지 내용은 허구입니다." if real else
       "가상 회사 연습 자료입니다. 모든 내용은 허구입니다.")
    files["04_공정설명서.docx"] = _doc(f"{COMPANY} 공정 설명서", [
        ("별지 제4호 · 총괄 취급시설 개요", [("총괄 취급시설 단위공장 구성", pr["총괄 개요"]), ("공정개요", pr["공정개요"]),
                                     ("입·출하 시설 수(기)", pr["입출하 시설 수"])]),
        ("별지 제5호 · 세부 취급시설 개요", [("단위공장 취급시설 개요", pr["단위공장 개요"])]),
    ])
    prop_headers = ("제품명", "CAS 번호", "물질상태", "비중", "폭발한계 하한", "폭발한계 상한", "독성구분 항목", "독성구분",
                    "위험노출수준", "허용농도값", "증기압", "분자량", "부식성", "SDS 파일명", "SDS 개정일")
    files["05_SDS_물성표.xlsx"] = _book({
        "별지6_물성": (prop_headers, [{"제품명": p["name"], "CAS 번호": p["cas"], "물질상태": _sds_state(p["state"]), "비중": p["density"], **p["props"]}
                                   for p in products]),
        "별지7_대표물질": (("물질명", "CAS 번호", "인체유해성", "물리적 위험성", "환경유해성", "선정 사유", "출처", "SDS 파일명", "SDS 개정일"),
                       [{"물질명": p["name"], "CAS 번호": p["cas"], **p["hazard"], "SDS 파일명": p["props"]["SDS 파일명"],
                         "SDS 개정일": p["props"]["SDS 개정일"]} for p in products if p["code"] in ("P-01", "P-03")]),
    })
    # 머리글에 단위를 적어 두면 프로그램이 단위를 묻지 않습니다(설계압력 → 설계압력(MPa)).
    spec_units = {"설계압력": "설계압력(MPa)", "운전압력": "운전압력(MPa)", "설계온도": "설계온도(℃)", "운전온도": "운전온도(℃)"}
    spec_headers = ("설비번호", "설비명", "최대 연결구 크기(mm)", "설계압력(MPa)", "운전압력(MPa)", "설계온도(℃)", "운전온도(℃)", "비고")
    dike_headers = ("설비번호", "적용여부", "설비형태", "확산방지설비 종류", "내부 길이(m)", "내부 폭(m)", "유효높이(m)", "내부 차감용적(m3)", "비고")
    form1_headers = ("설비번호", "별표4 기준함량(%)", "함량근거", "직접확인 최대보유량", "질량단위", "직접확인 근거", "보관계획도 최대량", "일일최대보관량")
    files["06_설비사양_안전설비.xlsx"] = _book({
        "별지1_추가입력": (form1_headers, [{"설비번호": f["id"], **f["form1"]} for f in facilities if f["form1"]]),
        "별지9_설비사양": (spec_headers, [{"설비번호": f["id"], "설비명": f["name"],
                                       **{spec_units.get(k, k): v for k, v in f["spec"].items()}} for f in facilities]),
        "별지10_확산방지설비": (dike_headers, [{"설비번호": f["id"], **f["dike"]} for f in facilities]),
        "별지10_공통기준": (("항목", "값"), [{"항목": "공통 필요용량 비율(%)", "값": DATA["dike_rule"]["비율(%)"]},
                                         {"항목": "공통 필요용량 근거", "값": DATA["dike_rule"]["근거"]}]),
        "별지11_가스감지기": (tuple(DATA["detectors"][0]), DATA["detectors"]),
    })
    survey = DATA["survey"] if not real else {"source": "", "method": "", "map_numbers": ""}
    files["07_주변보호대상_조사표.xlsx"] = _book({"보호대상": (tuple(DATA["surroundings"][0]), [] if real else DATA["surroundings"]),
                                             "조사 방법": (("항목", "내용"), [{"항목": "근거자료", "내용": survey["source"]},
                                                                         {"항목": "조사 방법", "내용": survey["method"]},
                                                                         {"항목": "지도 번호", "내용": survey["map_numbers"]}])})
    scen_headers = ("대상 설비번호", "액위(m)", "경계까지 거리(m)", "누출지점 배관길이(m)", "연소열", "비점", "액체비열", "기화열",
                    "증발잠열(kcal/kg)", "액체비열(kcal/kg·℃)", "증기밀도(kg/m3)")
    freq_headers = ("대상 설비번호", "고압용기파열", "배관파열", "배관누출", "상압 탱크 파열 및 누출", "플랜지 등의 가스켓 파손",
                    "펌프/컴프레서 누출", "안전밸브 오작동 및 조기개방", "냉각수 손실", "입/출하 시설 누출 사고", "외부화재",
                    "개수 산정근거", "수동적 완화장치", "능동적 완화장치", "안전성확보설비 증빙")
    files["08_사고시나리오_검토자료.xlsx"] = _book({
        "별지12_추가값": (scen_headers, [{"대상 설비번호": k, **v} for k, v in DATA["scenario_inputs"].items()]),
        "별지14_개시사건": (freq_headers, [{"대상 설비번호": k, **v} for k, v in DATA["frequency"].items()]),
    })
    from .cap_narrative_workspace import DECISION_FACTS
    labels = {f.key.split(".")[-1]: f.label for f in DECISION_FACTS}
    from . import cap_fact_catalog

    def decision_label(key, name):
        """프로그램이 알아보는 항목 이름(사실 카탈로그의 표기)으로 적습니다. 예: 책임자 → 안전관리 책임자."""
        try:
            return cap_fact_catalog.get(f"narrative.{key}.{name}").template_header
        except KeyError:
            return name

    narrative = [(f"서술형 결정사항 · {labels.get(key, key)}", [(decision_label(key, k), v) for k, v in values.items()])
                 for key, values in DATA["narrative"].items()]
    from .cap_form16_workspace import items as f16_items
    titles = {i["id"]: i["label"] for i in f16_items()}
    files["09_안전관리_비상대응계획.docx"] = _doc(f"{COMPANY} 안전관리·비상대응계획", [
        ("별지 제16호 · 내부 비상대응", [(titles.get(k, k), v) for k, v in DATA["emergency"].items()]), *narrative])
    for name in ("03_사업장_일반정보", "04_공정설명서", "09_안전관리_비상대응계획"):
        files[name + "_한글판.hwpx"] = _hwpx_from_docx(files[name + ".docx"])
    from .hwp5_binary import from_hwpx
    for name in ("01_제품목록", "02_설비대장", "03_사업장_일반정보", "04_공정설명서", "09_안전관리_비상대응계획"):
        files[name + "_한글판.hwp"] = from_hwpx(files[name + "_한글판.hwpx"])
    return files


def _picture(title, marks):
    """가상 지도·배치도 그림(PNG). 글꼴 없이도 보이도록 영문·숫자만 씁니다."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([330, 220, 570, 380], outline="black", width=4)
    draw.text((340, 230), "SITE (virtual)", fill="black")
    draw.text((20, 20), title, fill="black")
    for number, (x, y, label) in enumerate(marks, start=1):
        draw.ellipse([x - 16, y - 16, x + 16, y + 16], outline="red", width=3)
        draw.text((x - 4, y - 7), str(number), fill="red")
        draw.text((x + 22, y - 7), label, fill="black")
    draw.text((20, 570), "Fictional practice material - not a real place", fill="gray")
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _pictures(real=False):
    pictures = {
        "07_주변보호대상_지도.png": _picture("Protected targets within 500 m (numbers = list order)",
                                       [(620, 520, "school 420m"), (450, 560, "apartments 350m"), (640, 300, "warehouse 60m"),
                                        (150, 300, "stream 180m")]),
        "06_가스감지기_배치도.png": _picture("Gas detector layout", [(360, 260, "GD-01 NH3 (CY-01)"), (520, 350, "GD-02 HCl (TK-02)"),
                                                                 (430, 300, "GD-03 toluene (TK-01/RX-01)")]),
    }
    if real:                       # 실제 주소로 할 때는 지어낸 주변 지도를 주지 않음(지도 조회 화면을 캡처해 씀)
        pictures.pop("07_주변보호대상_지도.png")
    return pictures


@lru_cache(maxsize=8)
def _build(address="", complex_name=""):
    files = _files(address, complex_name)
    real = company(address, complex_name)["주소"] != DATA["company"]["주소"]
    return tuple({**files, **_pictures(real)}.items())


def files(address: str = "", complex_name: str = ""):
    """파일 이름 → 내용(한 번 만든 내용을 계속 씀: 같은 파일 = 같은 지문)."""
    return dict(_build(" ".join(str(address or "").split()), " ".join(str(complex_name or "").split())))


UPLOAD = {"01_제품목록.xlsx": "material", "02_설비대장.xlsx": "facility"}


@lru_cache(maxsize=8)
def full_demo_zip(address: str = "", complex_name: str = ""):
    """연습 자료 ZIP. 주소를 주면 그 실제 주소로 별지 제8호를 지도 조회해 채우는 판(지어낸 주변 목록·지도 없음)."""
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for name, content in files(address, complex_name).items():
            archive.writestr(name, content)
        archive.writestr("answer_key.json", json.dumps({
            "company": company(address, complex_name), "products": DATA["products"],
            "facilities": DATA["facilities"], "scenario_inputs": DATA["scenario_inputs"],
            "surroundings": None if address.strip() else DATA["surroundings"],
            "note": "허구 자료의 생성 원본. 실제 주소의 주변 정보는 별도로 조사해 확인해야 합니다.",
        }, ensure_ascii=False, indent=2).encode("utf-8"))
        archive.writestr("README_테스트_안내서.txt", readme(address, complex_name).encode("utf-8"))
    return out.getvalue()


def stress_files():
    """정상 연습 프로젝트와 분리해서 올릴 현장형 예외 자료. 값과 회사는 모두 허구입니다."""
    return {
        "01_두공장_설비대장.csv": (
            "단위공장,설비번호,설비명,취급제품,최대보유량(kg),운전압력(MPa)\n"
            "A공장,T-01,A공장 저장탱크,P-01,1000,0.1\n"
            "B공장,T-01,B공장 저장탱크,P-01,9000,0.2\n").encode("utf-8-sig"),
        "02_혼합물_성분목록.xlsx": _book({"성분목록": (
            ("제품코드", "제품명", "CAS 번호", "함량(%)"),
            [{"제품코드": "MIX-01", "제품명": "가상 혼합용제", "CAS 번호": "64-17-5", "함량(%)": 60},
             {"제품코드": "MIX-01", "제품명": "가상 혼합용제", "CAS 번호": "67-56-1", "함량(%)": 40}])}),
        "03_구버전_설비사양.csv": (
            "설비번호,설비명,최대보유량(kg),운전압력(kPa)\n"
            "T-02,가상 반응기,5000,200\n").encode("cp949"),
        "04_개정_설비사양.csv": (
            "설비번호,설비명,최대보유량(kg),운전압력(kPa)\n"
            "T-02,가상 반응기,7000,250\n").encode("utf-8-sig"),
        "05_서술형_운전기록.docx": _doc("가상 반응기 운전기록", [
            ("설비번호 T-02", "운전압력(MPa): 0.25\n운전온도(℃): 35\n구버전 운전자료는 현재 값으로 사용하지 않음")]),
    }


STRESS_TRUTH = {
    "purpose": "가상 회사 자료의 동일번호·혼합물·개정자료 충돌을 확인하는 별도 프로젝트용 진단",
    "facilities": ["A공장/T-01", "B공장/T-01", "T-02"],
    "components": [{"product": "MIX-01", "cas": "64-17-5", "concentration": 60},
                   {"product": "MIX-01", "cas": "67-56-1", "concentration": 40}],
    "current_T02_inventory_kg": 7000,
    "expected_limitations": ["단위공장별 중복 설비번호를 서로 다른 설비로 자동 분리하지 못함",
                             "한 제품코드의 여러 CAS 성분을 별도 성분으로 자동 분리하지 못함",
                             "서로 다른 시점의 값은 날짜만으로 현재 값을 자동 결정하지 않음"],
}


def stress_demo_zip():
    """정상 작성자료와 섞지 않는 별도 압박 시험 ZIP."""
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for name, content in stress_files().items():
            archive.writestr(name, content)
        archive.writestr("answer_key.json", json.dumps(STRESS_TRUTH, ensure_ascii=False, indent=2).encode())
        archive.writestr("README.txt", (
            "모두 허구의 시험자료입니다. '계획서 끝까지 연습 자료' 프로젝트에는 섞지 마세요.\n"
            "새 사업장을 만들어 01~04 파일을 올리고, 05 문서는 설비번호 T-02를 지정해 올리세요.\n"
            "T-01은 서로 다른 두 공장에 각각 한 대, MIX-01에는 두 CAS 성분이 있습니다.\n"
            "answer_key.json과 추출 설비·성분 수 및 충돌 질문을 비교하세요.\n"
            "프로그램이 두 경우를 합쳐 버리면 해결된 것이 아니라 확인된 결함입니다.\n").encode())
    return out.getvalue()
