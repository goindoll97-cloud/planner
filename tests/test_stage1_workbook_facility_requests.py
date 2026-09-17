from engine.stage1_workbook import _facility_blocker_requests


def test_generic_facility_request_is_replaced_with_exact_blockers():
    blockers = [
        "화학물질 목록 6행(과산화수소 35%): 별표4 시설정보가 한 줄 이상 필요합니다.",
        "시설정보 9행(T-901 메탄올탱크): 설계용량·용량단위·비중(밀도)이 필요합니다.",
    ]

    result = _facility_blocker_requests(blockers)

    assert (
        "04_시설별최대보유량: 화학물질 목록 6행(과산화수소 35%): "
        "별표4 시설정보가 한 줄 이상 필요합니다."
    ) in result
    assert (
        "04_시설별최대보유량: 시설정보 9행(T-901 메탄올탱크): "
        "설계용량·용량단위·비중(밀도)이 필요합니다."
    ) in result


def test_detailed_blockers_are_deduplicated():
    blocker = "시설정보 4행(T-101): 직접확인 최대보유량의 근거를 입력해 주세요."
    result = _facility_blocker_requests([blocker, blocker])

    assert result == [f"04_시설별최대보유량: {blocker}"]


def test_generic_request_is_kept_when_no_exact_blocker_is_available():
    assert _facility_blocker_requests([]) == [
        "04_시설별최대보유량: 시설별 최대보유량 산정에 필요한 용량·밀도·직접확인 최대보유량 등 누락 항목을 확인하여 작성해 주세요."
    ]
