# 화학사고예방관리계획서 작성 매뉴얼 Stage 2 인덱스

## 원본 provenance

- 문서명: `화학사고예방관리계획서 작성 매뉴얼 개정본`
- 문서번호: `NICS-GP2026-8`
- PDF 페이지 수: `156`
- SHA-256: `e6c55a0a1d87e97ab85afe7afc608abfc773540390e01f29eeac38f364ba2565`
- 역할: **작성 실무지침**
- 주의: 이 자료는 법령 자체가 아니다. 제출대상 판단과 현행 법적 근거는 기존 법령·승인 규정 DB가 담당하고, 이 registry는 작성항목·작성방법·요청자료를 구조화하는 데 사용한다.

실행용 상세정보는 `data/stage2/cap_manual_registry.json`에 저장한다.

## 작성구조

| 구분 | 매뉴얼 쪽 | Stage 2 핵심항목 |
|---|---:|---|
| 3.1 기본정보 | 36-48 | 사업장 일반정보, 취급시설 개요, 유해화학물질 명세·유해성, 입지정보 |
| 3.2 시설정보 | 49-61 | 공정개요, PFD, P&ID, 설비명세, 공정위험성 분석, 안전장치 |
| 3.3 장외평가정보 | 62-84 | 예비시나리오, 영향범위, 주변지역 영향, 시현빈도, 위험도 |
| 3.4 사전관리방침 | 85-106 | 안전관리, 교육훈련, 자체점검, 변경관리, 비상대응체계 |
| 3.5 내부 비상대응계획 | 107-118 | 가동중지, 방재자원, 내부 정보전달, 시설별 응급조치, 사고조사·복구 |
| 3.6 외부 비상대응계획 | 119-140 | 지역사회 소통·공조, 주민 보호·대피, 지역사회 고지 |
| 제출 전·후 확인 | 142-150 | 검토신청서, 타법 활용, 공동비상대응, 누락점검, 보완관리, 신규·변경 대조 |

## 1군/2군 적용

- **1군:** 3.1-3.6 전체 registry 사용
- **2군:** 3.1-3.5 registry 사용, 3.6 외부 비상대응계획은 필수 요청에서 제외
- 작성수준이 Stage 1에서 확정되지 않으면 fail-closed 원칙에 따라 1군 범위를 임시 적용한다.

## 상세 Requirement ID

### 3.1 기본정보

- `cap.basic.business` - 사업장 일반정보 - p.36-38
- `cap.basic.facility_overview` - 취급시설 개요 - p.39-40
- `cap.basic.chemical_inventory` - 유해화학물질 목록 및 명세 - p.41-42
- `cap.basic.hazard_info` - 유해화학물질 유해성 정보 - p.43-44
- `cap.basic.site_location` - 취급시설 입지정보 - p.45-48

### 3.2 시설정보

- `cap.facility.process_overview` - 공정개요 - p.49-50
- `cap.facility.pfd` - 공정흐름도(PFD) - p.49-50
- `cap.facility.pid` - 공정배관계장도(P&ID) - p.49, 51
- `cap.facility.equipment_specs` - 장치·설비 목록 및 명세 - p.49, 52-53
- `cap.facility.process_hazard_analysis` - 공정위험성 분석 자료 - p.49, 54-55
- `cap.facility.staffing` - 운전책임자 및 작업자 현황 - p.49, 56
- `cap.safety.dike` - 확산방지설비 현황 및 배치도 - p.57-58
- `cap.safety.detectors` - 고정식 유해감지시설 명세 및 배치도 - p.57, 59-60
- `cap.safety.relief_devices` - 안전밸브 및 파열판 명세 - p.57, 61
- `cap.safety.waste_treatment` - 배출물질 처리시설 현황 - p.57, 61

### 3.3 장외평가정보

- `cap.offsite.target_selection` - 대상 설비 선정 및 취급량 산정 - p.62-66
- `cap.offsite.impact_range` - 예비시나리오 영향범위 평가 - p.62-73
- `cap.offsite.surrounding_impact` - 사업장 주변 지역 영향 평가 - p.74-76
- `cap.offsite.frequency` - 사고 가능성 및 시현빈도 - p.77-81
- `cap.offsite.risk` - 위험도 분석 및 최종 위험도 - p.82-84

### 3.4 사전관리방침

- `cap.prevention.safety_management` - 안전관리 운영 계획 - p.85-88
- `cap.prevention.training` - 화학사고 대비 교육·훈련 계획 - p.87, 89-90
- `cap.prevention.self_inspection` - 자체점검계획 - p.90-98
- `cap.prevention.change_management` - 변경관리계획 - p.99-101
- `cap.prevention.emergency_contact` - 비상연락체계 - p.102
- `cap.prevention.emergency_org` - 비상대응조직도 - p.102-106
- `cap.prevention.command_center` - 비상통제실 운영 계획 - p.102-104

### 3.5 내부 비상대응계획

- `cap.internal.shutdown` - 가동중지 권한 및 절차 - p.107-109
- `cap.internal.resources` - 방재 인력 및 장비·물품 운용 계획 - p.108-114
- `cap.internal.communication` - 사업장 내부 정보전달체계 - p.108, 110
- `cap.internal.facility_response` - 취급시설 유형별 응급조치계획 - p.111-115
- `cap.internal.investigation` - 사고원인 조사 및 재발방지계획 - p.116-118
- `cap.internal.recovery` - 사고복구계획 - p.116-118

### 3.6 외부 비상대응계획 - 1군

- `cap.external.communication` - 지역사회와의 소통계획 - p.119-126
- `cap.external.mutual_aid` - 지역비상대응기관·인근 사업장 공조계획 - p.120-127
- `cap.external.evacuation` - 주민 보호·대피 계획 - p.128-134
- `cap.external.public_notice` - 지역사회 고지계획 - p.135-140

## 프로그램 처리원칙

각 requirement는 다음 메타데이터를 가진다.

- `field_keys`: 확보해야 할 구조화 사실
- `suggested_evidence`: 회사에 권장할 증빙자료
- `input_kind`: 표·도면·계산·계획서 등 입력유형
- `source_owner`: COMPANY / MIXED
- `automation`: 프로그램이 수행할 수 있는 처리방식
- `manual_pages`: 원문 재확인이 필요한 페이지

`VERIFIED`, `USER_CONFIRMED`, `CALCULATED` 상태인 필드는 다시 회사에 요청하지 않는다. `AI_DRAFT`, `HOLD`, 미등록 필드는 완료로 인정하지 않는다.
