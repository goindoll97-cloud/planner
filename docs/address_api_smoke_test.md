# 실제 주소로 주변 공간자료 조회 시험

프로젝트 루트의 `.env`에 발급받은 키와 등록 URL을 입력합니다. 실제 키는 커밋하지 않습니다.

```dotenv
KAKAO_REST_API_KEY=실제_카카오_REST_API_키
v_world_key=실제_브이월드_키
VWORLD_DOMAIN=http://localhost:8501
NGII_API_KEY=실제_국토정보플랫폼_키
NGII_REFERRER_URL=국토정보플랫폼에_등록한_사이트주소
```

`VWORLD_DOMAIN`에는 브이월드 발급 때 등록한 실제 서비스 URL을 입력합니다. 위 localhost 값은 그 주소로 등록한 경우의 예시입니다. `VWORLD_API_KEY`, `v_world_key`, `VWORLD_KEY` 중 기존에 쓰던 이름을 유지할 수 있습니다.

## 실행

```powershell
python check_address_apis.py
```

주소와 국토정보플랫폼 시험용 인근 시설명을 묻습니다. 한 서비스만 시험할 수도 있습니다.

```powershell
python check_address_apis.py --provider vworld --address "울산 남구 용연로 184"
python check_address_apis.py --provider ngii --address "울산 남구 용연로 184" --keyword "롯데케미칼 울산2공장"
```

결과는 `address_api_results_날짜_시간.json`에 저장합니다. 키 값은 표시하거나 저장하지 않습니다. `LAW_OC`와 `KOSHA_MSDS_SERVICE_KEY`는 설정 유무만 확인하며 이 명령으로 실제 API 연결을 검증하지 않습니다.

## 결과 읽기

- 브이월드는 레이어별 API 원자료 건수, 반경 내 건수, 이름 미인식 건수, 오류 상세를 표시합니다.
- 이름을 인식하지 못했어도 유효한 공간 객체는 `명칭 미제공`과 응답 식별번호로 후보에 남습니다. 건물 객체 수는 회사 수나 법정 보호대상 시설 수가 아닙니다.
- `NOT_FOUND`는 해당 자료와 조회조건에서의 결과 없음입니다. 주변에 조사 대상이 전혀 없다는 의미는 아닙니다.
- `INCORRECT_KEY`는 키·등록 URL·서비스 이용 설정을 확인합니다.
- `INVALID_RANGE`는 상세 오류의 파라미터명을 확인합니다. 특히 `data` 코드가 거부된 레이어는 조회 미완료이며, 다른 공식 자료로 보완해야 합니다.
- 국토정보플랫폼은 장소명 검색 결과를 거리로 걸러 내므로 주변 전수조사가 아닙니다. 정확한 인근 시설명을 사용하세요.

사용자가 2026-10-26에 위 울산 주소로 실행한 진단에서는 건물 원자료 504건이 반환됐지만 이름 미인식으로 모두 제외되는 문제가 확인됐습니다. 해당 누락을 수정했으며 504건 무명 객체의 페이지 조회와 보존을 모의 응답으로 검증합니다. 같은 실행에서 `LT_C_WGISARECO`가 2D 데이터 API의 `data` 값으로 거부됐고, 이 레이어의 대체 코드/공식 경계자료 확보는 아직 필요합니다.

현재 거리는 주소점 기준 참고값입니다. 실제 사업장 경계와 사고 영향범위의 공간분석, 논·밭 면적자료 조사 및 법정 보호대상 확정을 대신하지 않습니다.
