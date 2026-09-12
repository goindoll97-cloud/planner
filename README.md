# 화학안전 계획서 작성 지원 시스템 (planner)

기업이 **화학사고예방관리계획서(CAP)** 및 **공정안전보고서(PSM)**의 대상 여부를 먼저 신뢰성 있게 판정하고, 대상일 때만 다음 단계의 작성자료를 요청하도록 설계한 Streamlit 기반 지원 시스템입니다.

## 핵심 원칙

1. **Rule Engine 우선**: 법적 대상 여부를 AI가 추측하지 않습니다.
2. **HOLD-first**: 법령 최신성, 규정 DB 출처, 물질 식별, 필수 수량 또는 특수조건 중 하나라도 불확실하면 확정판정을 하지 않습니다.
3. **공식본 추적**: 국가법령정보 Open API로 현행 법령·행정규칙과 첨부 PDF를 확인하고 SHA-256으로 변경을 감지합니다.
4. **승인 DB 출처 검증**: 판정용 승인 DB가 현재 공식 PDF에서 만들어진 자료인지 SHA-256 provenance를 확인한 뒤에만 판정을 허용합니다.
5. **동적 질문**: 자동으로 확정할 수 없는 사실만 추가로 묻고, 답변은 다시 Rule Engine 계산에 반영합니다.
6. **CAP/PSM 독립 판정**: 한 사업장이 두 제도 모두 대상일 수 있으므로 각각 별도로 판정합니다.

## 현재 단계 — Stage 1 판정엔진 v1.0 후보

### 사용자 화면

사이드바는 세 화면만 노출합니다.

- `✅ 1. 판정진단`
- `🗂️ 2. 규정 DB 관리`
- `📚 3. 법령 근거`

실행 진입점은 기존과 동일합니다.

```bash
pip install -r requirements.txt
streamlit run app.py
```

`app.py`는 navigation만 담당하고 실제 UI는 `ui/` 아래에 분리되어 있습니다.

### 판정 전 중앙 readiness gate

판정진단은 다음 조건을 모두 만족해야 열립니다.

```text
공식 현행 법령 조회 성공
        ↓
법령/행정규칙 및 첨부 PDF 상태 = CURRENT
        ↓
필수 승인 규정 DB 존재
        ↓
승인 DB의 근거 PDF SHA-256 확인
        ↓
현재 공식 PDF SHA-256과 일치
        ↓
ALLOW → CAP/PSM 판정 실행
```

하나라도 맞지 않으면 `HOLD` 처리합니다.

현재 provenance 검증 대상 판정 DB는 다음 5종입니다.

- PSM 시행령 별표 13
- CAP 규정수량 별표 1
- CAP 규정수량 별표 2
- CAP 규정수량 별표 3
- CAP 규정수량 별표 4

### PSM

현재 구현 범위는 다음과 같습니다.

- 시행령 제43조 대상업종 KSIC exact-code 확인
- 별표 13 CAS 기반 규정량 매칭
- 일반 물질 순도 100% 환산
- 농도조건이 직접 규정된 물질 처리
- 동일 별표 13 항목으로 연결된 회사 목록 여러 행 선합산
- 제조·취급 C/T와 저장 C/T 중 큰 값 선택 후 R 합산
- 인화성 가스·인화성 액체(별표 13 제1·2호) 동적 물성 확인
- KSIC 20202의 제1·2호 조건 연동
- 발연황산 SO₃ 함량 및 니트로셀룰로오스 질소함량 후속 확인
- 후속답변을 실제 R 계산에 재주입
- 별표 13 비고 제8호 전문 가스 저장·판매시설 제외수량 차감 후 R 재계산
- 시행령 제43조제2항 제외설비 최종 확인

### CAP

현재 구현 범위는 다음과 같습니다.

- 별표 3 사고대비물질 우선 판정
- 별표 2 직접 CAS 및 포괄 법적 물질범위 판정
- CAS 하나로 확정할 수 없는 염류·화합물군·반응생성물 등은 자동 비대상 처리하지 않고 HOLD
- 별표 1 GHS 유해성·위험성 그룹 fallback
- KOSHA MSDS 자동조회는 참고자료로만 사용하고 회사/제품 SDS 확인 요구
- 별표 4 기준 사업장 최대보유량 계산
- 하위/상위 규정수량 비교
- 법정 면제시설 확인
- 주요취급시설 확인 후 1군/2군 최종 판정

## 규정 DB와 법적 근거 관리

최신 공식 PDF에서 바로 판정 DB로 넘어가지 않습니다.

```text
공식 PDF 감시
  → 후보표 자동추출
  → 자동검증
  → 사람 검토
  → 승인 DB 저장
  → 근거 PDF 보관 및 SHA-256 연결
  → 중앙 readiness gate 통과
```

실행 중 생성되는 감시자료·후보표·법적 근거 보관자료는 Git에 커밋하지 않습니다.

## API 설정

프로젝트 루트에 `.env` 파일을 만들고 인증값을 입력합니다.

```text
LAW_OC=국가법령정보_공동활용_인증값
KOSHA_SERVICE_KEY=KOSHA_MSDS_API_인증값
```

`.env`와 Streamlit secrets는 `.gitignore`에 포함되며 GitHub에 올리지 않습니다.

## 주요 구조

```text
planner/
├─ app.py                         # Streamlit navigation
├─ ui/
│  ├─ diagnosis_entry.py          # 중앙 readiness gate + 진단 진입
│  ├─ diagnosis_page.py           # CAP/PSM 1차 판정 UI
│  ├─ psm_followup_panel.py       # PSM 후속조건 입력 및 R 재계산
│  ├─ regdb_page.py               # 규정 DB 관리자 화면
│  └─ legal_evidence_page.py      # 법적 근거 조회
├─ engine/
│  ├─ readiness.py                # 법령 + 승인 DB provenance 중앙 gate
│  ├─ law_api.py
│  ├─ law_monitor.py
│  ├─ legal_archive.py
│  ├─ psm_engine.py
│  ├─ psm_followup.py
│  ├─ cap_engine.py
│  ├─ cap_final_decision.py
│  └─ ...
├─ data/
│  ├─ law_registry.json
│  ├─ regulatory/approved/        # 로컬 승인 DB
│  ├─ runtime/                    # Git 제외
│  └─ legal_archive/              # Git 제외
└─ tests/
```

## 테스트

Pull Request와 `main` push에서 GitHub Actions가 다음을 수행합니다.

1. Python 소스 compile check
2. 전체 `unittest` 실행

중요 시나리오에는 R 합산, 동일 법적 항목 선합산, 농도조건, 특수 성분조건, PSM 제1·2호 물성 후속답변, 비고 제8호 제외수량 재계산, CAP 최종판정, 법령/승인 DB SHA-256 readiness gate 등이 포함됩니다.

## 다음 단계

Stage 1 판정엔진을 고정한 뒤 Stage 2에서 실제 CAP/PSM 작성 지원으로 확장합니다. Stage 2에서는 판정 결과에 따라 필요한 설비·공정·도면·비상대응 자료만 선택적으로 요청하고, 확인된 사실과 법적 근거만 사용해 문서 초안을 생성하는 방향으로 진행합니다.

> 본 프로그램은 규제 검토 및 작성 지원 도구입니다. 최신 법령·고시·별표 및 승인 규정 DB의 출처가 검증되지 않은 상태에서는 결과를 확정하지 않고 `HOLD` 처리합니다.
