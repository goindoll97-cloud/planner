"""SGIS census population integration: geometry, API, audit and fail-closed tests."""
from __future__ import annotations

from unittest.mock import patch
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

    def administrative_areas(self, extent):
        self.calls.append("userarea")
        return [self.feature]

    def counts(self, adm_cd, year):
        self.calls.append(("counts", adm_cd, year))
        return 1000, 200, 100  # residents, total business employees, manufacturing


def test_two_identical_scenarios_not_double_counted_in_overall_union():
    p = project()
    client = FakeClient()
    with patch.object(sgis, "census_year", return_value="2024"):
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
    with patch.object(sgis, "census_year", return_value="2024"):
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
    with patch.object(sgis, "census_year", return_value="2024"):
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
    assert audit.value["source_urls"][0].endswith("userarea.geojson")
    assert "추정" in audit.value["status"]


def test_input_change_cannot_reuse_old_sgis_numbers():
    p = project()
    imps = impacts()
    p.set_field(iw.IMPACT_TABLE_KEY, "시험", [{"사고시나리오명": "독성-1"}], "CALCULATED")
    p.set_field(iw.SUMMARY_KEY, "시험", [{}], "CALCULATED")
    with patch.object(sgis, "census_year", return_value="2024"):
        result = sgis.estimate(p, imps, client=FakeClient())
    changed = [iw.ScenarioImpact("독성-1", "물질", "TK-1", sc.TOXIC, 101.0, 20.0, "근거", (), ())]
    with pytest.raises(sgis.SGISPopulationError, match="이전 통계"):
        sgis.apply_estimate(p, changed, result)


def test_explicit_company_confirmed_facts_must_not_be_overwritten():
    p = project()
    p.set_field(iw.IMPACT_TABLE_KEY, "외부 확인 인구", [{"사고시나리오명": "독성-1", "거주민수": 77}], "USER_CONFIRMED")
    p.set_field(iw.SUMMARY_KEY, "시험", [{}], "CALCULATED")
    with patch.object(sgis, "census_year", return_value="2024"):
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
