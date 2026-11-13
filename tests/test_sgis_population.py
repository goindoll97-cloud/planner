"""SGIS census population integration: geometry, API, audit and fail-closed tests."""
from __future__ import annotations

from unittest.mock import patch
from io import BytesIO
from docx import Document
import pytest
from pyproj import Transformer
from shapely.geometry import Point, box, mapping

from engine.stage2 import cap_impact_workspace as iw
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import sgis_population as sgis
from engine.stage2.project import Stage2Project


ORIGIN = "35.1800000,126.9000000"


def project():
    p = Stage2Project(project_id="SGIS-CAP-AUDIT", company_name="가상 사업장", cap_required=True)
    p.set_authoring_scope(psm_selected=False, cap_selected=True)
    p.set_field(sc.SCENARIO_KEY, "시험 사고시나리오", [
        {"사고시나리오명": "독성-1", "사고원점 좌표": ORIGIN},
        {"사고시나리오명": "독성-2", "사고원점 좌표": ORIGIN},
    ], "CALCULATED")
    return p


def impacts():
    return [
        iw.ScenarioImpact("독성-1", "물질", "TK-1", sc.TOXIC, 100.0, 20.0, "근거", (), ()),
        iw.ScenarioImpact("독성-2", "물질", "TK-2", sc.TOXIC, 100.0, 20.0, "근거", (), ()),
    ]


def feature_and_area():
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform(126.9, 35.18)
    area = box(x - 200, y - 200, x + 200, y + 200)
    return {"type": "Feature", "geometry": mapping(area),
            "properties": {"adm_cd": "29000000", "adm_nm": "시험동"}}, area


class FakeClient:
    def __init__(self, *, incomplete=False):
        self.calls = []
        self.feature, self.area = feature_and_area()
        if incomplete:
            x, y = self.area.centroid.coords[0]
            self.feature["geometry"] = mapping(box(x, y, x + 200, y + 200))

    def available_years(self):
        return ["2024"]

    def administrative_areas(self, extent):
        self.calls.append("userarea")
        return [self.feature]

    def counts(self, adm_cd, year):
        self.calls.append(("counts", adm_cd, year))
        return 1000, 200, 100  # residents, total business employees, manufacturing


def test_two_identical_scenarios_not_double_counted_in_overall_union():
    p = project()
    client = FakeClient()
    with patch.object(FakeClient, "available_years", return_value=["2024"]):
        result = sgis.estimate(p, impacts(), client=client)
    one = result["scenario"]["독성-1"]
    assert result["scenario"]["독성-2"] == one
    assert result["overall"]["거주민수"] == one["거주민수"]
    assert result["overall"]["근로자수"] == one["근로자수"]
    ratio = Point(*client.area.centroid.coords[0]).buffer(100, resolution=48).area / client.area.area
    assert one["거주민수"] == round((1000 + 200 - 100) * ratio)
    assert one["근로자수"] == round(100 * ratio)
    assert result["administrative_dongs"] == ["29000000"]
    assert client.calls.count("userarea") == 1
    assert len([x for x in client.calls if isinstance(x, tuple)]) == 1


def test_geometry_coverage_incomplete_must_not_generate_zero_or_partial_count():
    with patch.object(FakeClient, "available_years", return_value=["2024"]):
        with pytest.raises(sgis.SGISPopulationError, match="경계가 영향범위"):
            sgis.estimate(project(), impacts(), client=FakeClient(incomplete=True))


def test_auto_calculated_values_populate_form12_and_13_project_facts():
    p = project()
    imps = impacts()
    p.set_field(iw.IMPACT_TABLE_KEY, "시험", [
        {"사고시나리오명": "독성-1", "거주민수": "", "근로자수": "", "영향반경(m)": 100},
        {"사고시나리오명": "독성-2", "거주민수": "", "근로자수": "", "영향반경(m)": 100},
    ], "CALCULATED")
    p.set_field(iw.SUMMARY_KEY, "시험", [
        {"총괄영향범위 내 거주민수": "", "총괄영향범위 내 근로자수": ""}
    ], "CALCULATED")
    with patch.object(FakeClient, "available_years", return_value=["2024"]):
        result = sgis.refresh_for_draft(p, imps, client=FakeClient())
    data = p.get_field(iw.IMPACT_TABLE_KEY)
    assert data.status == "CALCULATED"
    assert data.value[0]["거주민수"] == result["scenario"]["독성-1"]["거주민수"]
    assert data.value[0]["근로자수"] == result["scenario"]["독성-1"]["근로자수"]
    summary = p.get_field(iw.SUMMARY_KEY).value[0]
    assert summary["총괄영향범위 내 거주민수"] == result["overall"]["거주민수"]
    assert summary["총괄영향범위 내 근로자수"] == result["overall"]["근로자수"]
    audit = p.get_field(sgis.RESULT_KEY)
    assert audit.status == "CALCULATED"
    assert any(url.endswith("userarea.geojson") for url in audit.value["source_urls"])
    assert audit.value["latest_common_year"] == "2024"
    assert "추정" in audit.value["status"]


def test_impact_report_discloses_estimates_and_source_year():
    p = project()
    imps = impacts()
    p.set_field(iw.IMPACT_TABLE_KEY, "시험", [
        {"사고시나리오명": item.name, "거주민수": "", "근로자수": ""}
        for item in imps
    ], "CALCULATED")
    p.set_field(iw.SUMMARY_KEY, "시험", [{}], "CALCULATED")
    with patch.object(FakeClient, "available_years", return_value=["2024"]):
        result = sgis.refresh_for_draft(p, imps, client=FakeClient())
    doc = Document(BytesIO(iw.report_docx(p, imps)))
    text = "\n".join([par.text for par in doc.paragraphs] +
                     [cell.text for table in doc.tables for row in table.rows for cell in row.cells])
    assert "SGIS 2024" in text or "2024" in text
    assert "면적 비율" in text
    assert "SGIS 추정" in text
    assert str(result["overall"]["거주민수"]) in text


def test_input_change_cannot_reuse_old_sgis_numbers():
    p = project()
    imps = impacts()
    p.set_field(iw.IMPACT_TABLE_KEY, "시험", [{"사고시나리오명": "독성-1"}], "CALCULATED")
    p.set_field(iw.SUMMARY_KEY, "시험", [{}], "CALCULATED")
    with patch.object(FakeClient, "available_years", return_value=["2024"]):
        result = sgis.estimate(p, imps, client=FakeClient())
    changed = [iw.ScenarioImpact("독성-1", "물질", "TK-1", sc.TOXIC, 101.0, 20.0, "근거", (), ())]
    with pytest.raises(sgis.SGISPopulationError, match="이전 통계"):
        sgis.apply_estimate(p, changed, result)


def test_explicit_company_confirmed_facts_must_not_be_overwritten():
    p = project()
    p.set_field(iw.IMPACT_TABLE_KEY, "외부 확인 인구", [{"사고시나리오명": "독성-1", "거주민수": 77}], "USER_CONFIRMED")
    p.set_field(iw.SUMMARY_KEY, "시험", [{}], "CALCULATED")
    with patch.object(FakeClient, "available_years", return_value=["2024"]):
        result = sgis.estimate(p, impacts(), client=FakeClient())
    with pytest.raises(sgis.SGISPopulationError, match="덮어쓸 수 없습니다"):
        sgis.apply_estimate(p, impacts(), result)
    assert p.get_field(iw.IMPACT_TABLE_KEY).value[0]["거주민수"] == 77


def test_api_parsing_auth_and_missing_statistics():
    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    seen = []
    def get(url, *, params, timeout):
        seen.append((url, dict(params)))
        if url.endswith("authentication.json"):
            return Response({"errCd": 0, "result": {"accessToken": "test-only"}})
        if url.endswith("population.json"):
            return Response({"errCd": 0, "result": [{"adm_cd": "29000000", "tot_ppltn": "125"}]})
        if url.endswith("company.json") and params.get("class_code") == "C":
            return Response({"errCd": 0, "result": [{"adm_cd": "29000000", "tot_worker": "N/A"}]})
        if url.endswith("company.json"):
            return Response({"errCd": 0, "result": [{"adm_cd": "29000000", "tot_worker": "40"}]})
        raise AssertionError(url)

    with patch.object(sgis, "configured", return_value=True), patch.object(
        sgis, "_setting", side_effect=lambda key: {"SGIS_CONSUMER_KEY": "service-id",
                                               "SGIS_CONSUMER_SECRET": "password"}[key]
    ):
        client = sgis.SGISClient(get=get)
        with pytest.raises(sgis.SGISPopulationError, match="누락·비공개"):
            client.counts("29000000", "2024")
        assert client._token == "test-only"
    assert seen[0][1]["consumer_key"] == "service-id"
    assert len([url for url, _ in seen if url.endswith("authentication.json")]) == 1


def test_missing_keys_never_attempt_api(monkeypatch):
    monkeypatch.delenv("SGIS_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("SGIS_CONSUMER_SECRET", raising=False)
    with patch.object(sgis, "_setting", return_value=""):
        assert not sgis.configured()
        with pytest.raises(sgis.SGISPopulationError, match="SGIS_CONSUMER_KEY"):
            sgis.SGISClient(get=lambda *args, **kwargs: pytest.fail("called")).token()

def test_official_sgis_year_api_selects_latest_mutual_year_without_env():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errCd": 0, "result": {
                "lin_yr": "2026", "lcorp_yr": "2025",
                "tin_yr": ["2022", "2023", "2024", "2025", "2026"],
                "tcorp_yr": ["2021", "2023", "2024", "2025"],
            }}

    calls = []
    def get(url, *, params, timeout):
        calls.append((url, dict(params)))
        return Response()

    client = sgis.SGISClient(get=get)
    client._token = "test-token"
    with patch.dict("os.environ", {"SGIS_CENSUS_YEAR": "2022"}):
        # Obsolete local values must not override the official year catalogue.
        assert client.available_years() == ["2025", "2024", "2023"]
    assert len(calls) == 1
    assert calls[0][0].endswith("/year/data.json")
    assert calls[0][1] == {"accessToken": "test-token"}


def test_year_metadata_selects_only_mutual_years_and_rejects_no_common_year():
    class Response:
        def __init__(self, result):
            self.result = result

        def raise_for_status(self):
            return None

        def json(self):
            return {"errCd": 0, "result": self.result}

    def make_client(result):
        client = sgis.SGISClient(get=lambda *args, **kw: Response(result))
        client._token = "test"
        return client

    assert make_client({
        "tin_yr": ["2024", "2023", "2022"],
        "tcorp_yr": ["2023", "2022"],
        "lin_yr": "2024", "lcorp_yr": "2023",
    }).available_years() == ["2023", "2022"]
    assert make_client({
        "lin_yr": "2024", "lcorp_yr": "2024",
    }).available_years() == ["2024"]
    with pytest.raises(sgis.SGISPopulationError, match="공통"):
        make_client({"tin_yr": ["2025"], "tcorp_yr": ["2024"]}).available_years()
    with pytest.raises(sgis.SGISPopulationError, match="연도 목록"):
        make_client(None).available_years()


def test_latest_year_missing_one_administrative_stat_falls_back_to_previous():
    class YearAwareClient(FakeClient):
        def available_years(self):
            return ["2025", "2024", "2023"]

        def counts(self, adm_cd, year):
            self.calls.append(("counts", adm_cd, year))
            if year == "2025":
                raise sgis.SGISPopulationYearUnavailable(
                    f"{adm_cd}의 {year}년 총인구 자료가 비공개입니다."
                )
            return 1000, 200, 100

    client = YearAwareClient()
    result = sgis.estimate(project(), impacts(), client=client)
    assert result["year"] == "2024"
    assert result["latest_common_year"] == "2025"
    assert result["year_selection"].startswith("이전 공통연도")
    assert "2025" in result["year_fallback_reasons"][0]
    assert result["administrative_statistics"][0]["SGIS_총인구"] == 1000
    assert client.calls == ["userarea", ("counts", "29000000", "2025"),
                           ("counts", "29000000", "2024")]


def test_all_published_common_years_missing_fails_without_zero():
    class IncompleteClient(FakeClient):
        def available_years(self):
            return ["2025", "2024"]

        def counts(self, adm_cd, year):
            raise sgis.SGISPopulationYearUnavailable(f"{year} 통계가 누락되었습니다.")

    with pytest.raises(sgis.SGISPopulationError, match="완전한 통계"):
        sgis.estimate(project(), impacts(), client=IncompleteClient())


def test_network_or_authentication_failure_does_not_silently_fallback():
    class BrokenClient(FakeClient):
        def available_years(self):
            return ["2025", "2024"]

        def counts(self, adm_cd, year):
            self.calls.append(("counts", adm_cd, year))
            raise sgis.SGISPopulationError("API 인증 실패")

    client = BrokenClient()
    with pytest.raises(sgis.SGISPopulationError, match="API 인증 실패"):
        sgis.estimate(project(), impacts(), client=client)
    assert client.calls == ["userarea", ("counts", "29000000", "2025")]

