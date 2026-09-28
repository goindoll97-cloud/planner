from __future__ import annotations

from io import BytesIO
from pathlib import Path
import os
import unittest
from unittest.mock import patch

from docx import Document

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_site_lookup as lookup
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from engine.stage2.project import Stage2Project

ROOT = Path(__file__).resolve().parents[1]


def _project() -> Stage2Project:
    project = Stage2Project(project_id="S2-F8", company_name="테스트화학", site_name="공장", cap_required=True,
                            scope_confirmed=True, cap_selected=True, cap_group="2군")
    project.set_field("business.address", "사업장 소재지", "울산광역시 남구 산업로 1", "VERIFIED")
    return project


def _fake_get(url, params, headers):
    if url.endswith("address.json"):
        return {"documents": [{"x": "129.3", "y": "35.5"}]}
    code = params.get("category_group_code")
    if code == "SC4":
        return {"documents": [{"place_name": "한빛초등학교", "distance": "310", "road_address_name": "산업로 9"}]}
    if params.get("query") == "하천":
        return {"documents": [{"place_name": "태화강", "distance": "450", "address_name": "울산 남구"}]}
    return {"documents": []}


class CAPForm8WorkspaceTests(unittest.TestCase):
    def test_company_list_import_is_staged_and_deduplicated(self):
        project = _project()
        imported, notices = f8.import_company_rows([
            {"명칭": "한빛초등학교", "주소": "산업로 9", "구분": "갑종", "거리(m)": "320"},
            {"명칭": "한빛초등학교", "주소": "산업로 9"},
            {"명칭": "", "주소": "이름 없는 시설"},
        ])
        self.assertEqual(len(imported), 1)
        self.assertEqual(len(notices), 2)
        self.assertEqual(imported[0]["사업장 경계와 거리(m)"], "320")
        self.assertEqual(imported[0]["검색 출처·검색일"], "")
        self.assertFalse(imported[0]["500m 범위 전체 확인"])
        f8.save(project, imported, no_target=False, scope_reviewed=False, status="HOLD")
        self.assertTrue(f8.needs(project))

    def test_map_numbers_and_review_record_are_rechecked_when_candidates_change(self):
        project = _project()
        checks = {key: True for key, _ in f8.REVIEW_ITEMS}
        row = {"보호대상 명칭": "한빛초등학교", "보호대상 구분": "갑종",
               "세부유형": "교육·연구시설", "주소·위치": "산업로 9",
               "사업장 경계와 거리(m)": 320, "GIS/현장 근거": "지도 2026-09-28 경계 측정"}
        self.assertEqual(f8.review_issues([row], False, checks, "지도·도면 2026-09-28", "경계 측정", "1"), [])
        self.assertEqual(f8.review_issues([{**row, "사업장 경계와 거리(m)": 0}], False,
                                          checks, "지도·도면 2026-09-28", "경계 측정", "1"), [])
        self.assertTrue(any("지도 번호" in issue for issue in
                            f8.review_issues([row], False, checks, "자료", "측정", "2")))
        self.assertTrue(any("자연환경" in issue for issue in
                            f8.review_issues([row], False, {**checks, "environment": False}, "자료", "측정", "1")))
        f8.save(project, [row], no_target=False, scope_reviewed=True)
        from engine.stage2.project import EvidenceRef
        map_ref = EvidenceRef(source_type="FORM8_MAP_REVIEW", source_name="확인 지도.pdf", sha256="abc123")
        f8.save_review(project, checks, "지도·도면 2026-09-28", "경계 측정", "1", [map_ref])
        self.assertEqual(f8.review(project)["지도 번호"], "1")
        self.assertEqual(project.get_field(f8.REVIEW_KEY).evidence[0].source_name, "확인 지도.pdf")
        self.assertEqual(f8.needs(project), [])
        f8.save_review(project, checks, "지도·도면 2026-09-28", "경계 측정", "2")
        self.assertTrue(any("일련번호" in issue for issue in f8.needs(project)))
        f8.invalidate_review(project)
        self.assertEqual(f8.review(project), {})
        self.assertTrue(any("다시 검토" in issue for issue in f8.needs(project)))

    def test_schema_follows_guideline_and_annex4(self):
        self.assertTrue(ws.load_form_schema(8)["title"].endswith(guide.form_guidelines()[8].title))
        rules = guide.protected_target_rules()
        self.assertEqual(set(rules), {"갑종", "을종", "환경수용체"})
        self.assertIn("300명", f8.type_hint("갑종", "종교시설"))
        self.assertIn("20명", f8.type_hint("갑종", "노유자시설"))

    def test_printed_options_match_the_form_checkboxes(self):
        header = " ".join(cell for row in guide.form_guidelines()[8].tables[0] for cell in row)
        for options in f8.SUBTYPES.values():
            for option in options:
                self.assertIn(option.replace(" ", ""), header.replace(" ", ""))

    def test_no_key_means_no_lookup(self):
        with patch.dict(os.environ, {lookup.ENV_KEY: ""}):
            found, message = lookup.find_candidates("울산", get=_fake_get)
        self.assertEqual(found, [])
        self.assertIn(lookup.ENV_KEY, message)

    def test_candidates_are_proposed_from_address_and_sorted_by_distance(self):
        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            found, _ = lookup.find_candidates("울산광역시 남구 산업로 1", get=_fake_get)
        self.assertEqual([c.name for c in found], ["한빛초등학교", "태화강"])
        self.assertEqual((found[0].category, found[0].subtype), ("갑종", "교육·연구시설"))
        self.assertEqual(found[1].category, "환경수용체")

    def test_paged_places_are_deduplicated_by_place_id_and_nature_is_suggested(self):
        calls = []

        def get(url, params, headers):
            if url.endswith("address.json"):
                return {"documents": [{"x": "129.3", "y": "35.5"}]}
            if params.get("query") == "산림":
                calls.append(params["page"])
                if params["page"] == 1:
                    return {"documents": [{"id": "forest-1", "place_name": "근처 숲",
                                            "address_name": "울산", "distance": "420"}],
                            "meta": {"is_end": False}}
                return {"documents": [{"id": "forest-2", "place_name": "다른 숲",
                                        "address_name": "울산", "distance": "550"}],
                        "meta": {"is_end": True}}
            if params.get("query") == "숲":
                return {"documents": [{"id": "forest-1", "place_name": "근처 숲",
                                        "address_name": "울산", "distance": "420"}],
                        "meta": {"is_end": True}}
            return {"documents": [], "meta": {"is_end": True}}

        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            found, _ = lookup.find_candidates("울산", get=get)
        self.assertEqual(calls, [1, 2])
        self.assertEqual([c.name for c in found], ["근처 숲", "다른 숲"])
        self.assertEqual((found[0].category, found[0].subtype),
                         ("환경수용체", "산림지 및 유적지"))
        self.assertTrue(all(c.distance_m is not None for c in found))

    def test_vworld_environment_layers_respect_buffer_and_keep_partial_results(self):
        from engine.stage2 import cap_vworld_lookup as vworld

        def data(params):
            self.assertEqual(params["geomFilter"], "POINT(129.3 35.5)")
            self.assertEqual(params["buffer"], 800)
            if params["data"] == "LT_C_UM901":
                return {"response": {"status": "ERROR"}}
            features = {
                "LT_C_WKMSTRM": [
                    {"id": "river", "properties": {"riv_nm": "태화강"}, "geometry": {
                        "type": "LineString", "coordinates": [[129.307, 35.5], [129.307, 35.501]]}},
                    {"id": "far", "properties": {"riv_nm": "먼 하천"}, "geometry": {
                        "type": "Point", "coordinates": [129.32, 35.5]}},
                ],
                "LT_C_WGISARWET": [{"id": "wetland", "properties": {}, "geometry": {
                    "type": "Polygon", "coordinates": [[[129.299, 35.499], [129.301, 35.499],
                                                   [129.301, 35.501], [129.299, 35.501],
                                                   [129.299, 35.499]]]}}],
            }.get(params["data"], [])
            return {"response": {"status": "OK", "result": {"featureCollection": {"features": features}}}}

        with patch.dict(os.environ, {vworld.ENV_KEY: "test-key"}):
            found, warnings = vworld.search(35.5, 129.3, get=data)
        self.assertEqual({c.name for c in found}, {"태화강"})
        self.assertLess(found[0].distance_m, 800)
        self.assertIn("습지보호지역", " ".join(warnings))

    def test_vworld_key_alone_can_geocode_and_find_environment(self):
        from engine.stage2 import cap_vworld_lookup as vworld

        original_geocode = vworld.geocode
        def point(params):
            return {"response": {"status": "OK", "result": {"point": {"x": "129.3", "y": "35.5"}}}}

        with patch.dict(os.environ, {lookup.ENV_KEY: "", vworld.ENV_KEY: "test-key"}):
            with patch.object(vworld, "geocode", side_effect=lambda addr: original_geocode(addr, get=point)):
                found, message = lookup.find_combined_candidates(
                    "울산 남구 사평로 119", vworld_search=lambda lat, lon: (
                        [lookup.Candidate("태화강", "환경수용체", "기타 환경수용체", "브이월드", 430, "브이월드")], []),
                    environment_search=lambda lat, lon: [],
                )
        self.assertEqual([c.name for c in found], ["태화강"])
        self.assertIn("브이월드 공간정보 1건", message)

    def test_building_map_records_and_unclassified_selection(self):
        from engine.stage2 import cap_vworld_lookup as vworld

        def data(params):
            features = []
            if params["data"] == "LT_C_SPBD":
                features = [{"id": "building-1", "properties": {"bd_nm": "비어 있는 건물"},
                             "geometry": {"type": "Polygon", "coordinates": [[
                                 [129.299, 35.499], [129.301, 35.499],
                                 [129.301, 35.501], [129.299, 35.501], [129.299, 35.499]]]}}]
            return {"response": {"status": "OK", "result": {"featureCollection": {"features": features}}}}

        with patch.dict(os.environ, {vworld.ENV_KEY: "test-key"}):
            found, notices = vworld.search(35.5, 129.3, get=data)
        self.assertEqual(notices, [])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].distance_m, 0)
        raw = f8.candidate_row(found[0], unclassified=True)
        self.assertEqual(raw["보호대상 구분"], "")
        self.assertEqual(raw["세부유형"], "")
        project = _project()
        f8.save(project, [raw], no_target=False, status="HOLD")
        self.assertTrue(f8.needs(project))

    def test_named_and_unnamed_osm_features_are_visible_without_legal_classification(self):
        from engine.stage2 import cap_environment_lookup as osm

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"elements": [
                    {"id": 1, "type": "node", "lat": 35.5, "lon": 129.3,
                     "tags": {"amenity": "school", "name": "학교"}},
                    {"id": 2, "type": "way", "tags": {"building": "yes"}, "geometry": [
                        {"lat": 35.499, "lon": 129.299}, {"lat": 35.499, "lon": 129.301},
                        {"lat": 35.501, "lon": 129.301}, {"lat": 35.501, "lon": 129.299},
                        {"lat": 35.499, "lon": 129.299}]},
                ]}

        found = osm.search(35.5, 129.3, post=lambda *args, **kwargs: Response())
        self.assertEqual({c.name for c in found}, {"학교"})
        self.assertTrue(all(c.category == "" and c.subtype == "" for c in found))
        self.assertEqual(found[0].distance_m, 0)

    def test_existing_vworld_environment_variable_is_accepted(self):
        from engine.stage2 import cap_vworld_lookup as vworld

        with patch.dict(os.environ, {vworld.ENV_KEY: "", "v_world_key": "existing-key"}):
            self.assertEqual(vworld.api_key(), "existing-key")

    def test_failure_of_environment_layer_preserves_kakao_facilities(self):
        with patch.dict(os.environ, {lookup.ENV_KEY: "k", "VWORLD_API_KEY": ""}):
            found, message = lookup.find_combined_candidates(
                "울산", get=_fake_get,
                environment_search=lambda lat, lon: (_ for _ in ()).throw(ValueError("server error")),
            )
        self.assertEqual([c.name for c in found], ["한빛초등학교", "태화강"])
        self.assertIn("OpenStreetMap 환경 지도 조회 실패", message)

    def test_candidate_distance_is_reference_only_until_boundary_distance_is_entered(self):
        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            found, _ = lookup.find_candidates("울산광역시 남구 산업로 1", get=_fake_get)
        row = f8.candidate_row(found[0])
        self.assertEqual(row["사업장 경계와 거리(m)"], "")
        self.assertEqual(row["검색결과 거리(주소점 기준, 참고)"], 310)
        self.assertEqual(row["GIS/현장 근거"], "")
        self.assertFalse(row["500m 범위 전체 확인"])

    def test_only_supported_search_types_are_suggested_and_unknowns_stay_blank(self):
        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            school, river = lookup.find_candidates("울산", get=_fake_get)[0][0:2]
        self.assertEqual(f8.candidate_row(school)["보호대상 구분"], "갑종")
        self.assertEqual(f8.candidate_row(school)["세부유형"], "교육·연구시설")
        self.assertEqual(f8.candidate_row(river)["보호대상 구분"], "")
        apartment = lookup.Candidate("아파트", "갑종", "주택", "울산", 300, "카카오 로컬 API · 검색어 아파트")
        self.assertEqual(f8.candidate_row(apartment)["보호대상 구분"], "")
        mapped = lookup.Candidate("학교", "", "", "지도 분류: amenity=school · OSM node/1", 20,
                                  "OpenStreetMap/Overpass 지도 객체 (법정 분류 미확인)")
        self.assertEqual(f8.candidate_row(mapped)["보호대상 구분"], "갑종")
        unknown = lookup.Candidate("건물", "", "", "지도 분류: building=yes · OSM way/2", 20,
                                   "OpenStreetMap/Overpass 지도 객체 (법정 분류 미확인)")
        self.assertEqual(f8.candidate_row(unknown)["보호대상 구분"], "")

    def test_vworld_status_is_visible_without_exposing_server_text(self):
        from engine.stage2 import cap_vworld_lookup as vworld

        def data(params):
            if params["data"] == "LT_C_SPBD":
                return {"response": {"status": "ERROR", "error": {"code": "INVALID_KEY", "text": "secret"}}}
            return {"response": {"status": "NOT_FOUND"}}

        with patch.dict(os.environ, {vworld.ENV_KEY: "secret"}):
            found, notices = vworld.search(35.5, 129.3, get=data)
        self.assertEqual(found, [])
        self.assertEqual(len(notices), 1)
        self.assertIn("INVALID_KEY", notices[0])
        self.assertNotIn("secret", notices[0])

    def test_invalid_vworld_key_is_reported_once(self):
        from engine.stage2 import cap_vworld_lookup as vworld
        calls = []

        def data(params):
            calls.append(params["data"])
            return {"response": {"status": "ERROR", "error": {"code": "INCORRECT_KEY"}}}

        with patch.dict(os.environ, {vworld.ENV_KEY: "redacted"}):
            found, notices = vworld.search(35.5, 129.3, get=data)
        self.assertEqual(found, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(notices), 1)
        self.assertIn("도메인", notices[0])

    def test_added_search_candidate_is_proposed_not_confirmed(self):
        project = _project()
        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            found, _ = lookup.find_candidates("울산광역시 남구 산업로 1", get=_fake_get)
        f8.save(project, [f8.candidate_row(found[0])], no_target=False, status="HOLD")
        record = project.get_field(f8.SITE_KEY)
        self.assertEqual(record.status, "HOLD")
        self.assertTrue(f8.needs(project))

    def test_lookup_failure_falls_back_to_manual_entry(self):
        def boom(url, params, headers):
            raise lookup.requests.ConnectionError("down")

        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            found, message = lookup.find_candidates("울산", get=boom)
        self.assertEqual(found, [])
        self.assertIn("직접 입력", message)

    def test_http_auth_failure_explains_which_kakao_setting_to_check(self):
        response = lookup.requests.Response()
        response.status_code = 401

        def unauthorized(url, params, headers):
            raise lookup.requests.HTTPError(response=response)

        with patch.dict(os.environ, {lookup.ENV_KEY: "invalid-key"}):
            found, message = lookup.find_candidates("울산", get=unauthorized)
        self.assertEqual(found, [])
        self.assertIn("HTTP 401", message)
        self.assertIn("REST API 키", message)
        self.assertIn("직접 입력", message)

    def test_http_403_uses_kakao_error_code_to_give_specific_guidance(self):
        response = lookup.requests.Response()
        response.status_code = 403
        response._content = b'{"code":-3,"msg":"API is not allowed"}'
        error = lookup.requests.HTTPError(response=response)
        hint = lookup._http_error_hint(error)
        self.assertIn("오류 코드 -3", hint)
        self.assertIn("사용 또는 호출 허용", hint)

    def test_confirmed_list_derives_checkboxes_and_reaches_the_docx(self):
        project = _project()
        with patch.dict(os.environ, {lookup.ENV_KEY: "k"}):
            found, _ = lookup.find_candidates("주소", get=_fake_get)
        rows = [f8.candidate_row(c) for c in found]
        rows[0]["사업장 경계와 거리(m)"] = 320
        rows[0]["GIS/현장 근거"] = "공식 지도에서 경계부터 측정, 2026-09-25"
        rows[1]["사업장 경계와 거리(m)"] = 430
        rows[1]["보호대상 구분"] = "환경수용체"  # reviewer confirmed designated river
        rows[1]["세부유형"] = "하천"
        rows[1]["GIS/현장 근거"] = "현장 확인 및 지도 측정, 2026-09-25"
        self.assertEqual(f8.save(project, rows, no_target=False, scope_reviewed=True), 2)
        chosen = f8.selected_options(project)
        self.assertEqual(chosen["갑종"], {"교육·연구시설"})
        self.assertEqual(chosen["환경수용체"], {"하천"})
        self.assertEqual(f8.needs(project), [])
        tables = Document(BytesIO(build_cap_baseline_draft(project))).tables
        context = "\n".join(c.text for r in tables[FORM_TABLE_INDEX["8"][0]].rows for c in r.cells)
        listing = "\n".join(c.text for r in tables[FORM_TABLE_INDEX["8"][1]].rows for c in r.cells)
        self.assertIn("☒ 교육·연구시설", context)
        self.assertIn("☐ 의료시설", context)
        self.assertIn("☒ 하천", context)
        self.assertNotIn("☒ 주택", context)
        self.assertIn("한빛초등학교", listing)

    def test_no_target_declaration_needs_evidence(self):
        project = _project()
        f8.save(project, [], no_target=True, evidence="", scope_reviewed=True)
        self.assertTrue(f8.declared_no_target(project))
        self.assertTrue(f8.needs(project))
        f8.save(project, [], no_target=True, evidence="지도 확인 2026-09-19", scope_reviewed=True)
        self.assertEqual(f8.needs(project), [])

    def test_page_is_wired(self):
        self.assertIn(8, __import__("ui.cap_forms_registry", fromlist=["x"]).FORM_NUMBERS)


if __name__ == "__main__":
    unittest.main()
