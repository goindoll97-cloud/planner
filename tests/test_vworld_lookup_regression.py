"""독립적인 모의 응답 회귀검사. API 키/실제 네트워크 없이 실행합니다."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch


from engine.stage2 import cap_vworld_lookup as v


LAT, LON = 35.47790404772272, 129.35893422223296


def feature(identifier=None, properties=None):
    item = {"type": "Feature", "properties": properties or {},
            "geometry": {"type": "Point", "coordinates": [LON, LAT]}}
    if identifier is not None:
        item["id"] = identifier
    return item


def response(rows):
    return {"response": {"status": "OK", "result": {
        "featureCollection": {"type": "FeatureCollection", "features": rows}}}}


def empty():
    return {"response": {"status": "NOT_FOUND"}}


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"v_world_key": "FAKE_TEST_KEY", "VWORLD_DOMAIN": "http://localhost:8501"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_504_unnamed_buildings_survive_pagination(self):
        calls = []
        def get(params):
            calls.append((params["data"], params["page"]))
            if params["data"] != "LT_C_SPBD":
                return empty()
            start = (params["page"] - 1) * 100
            return response([feature(f"building.{i}", {"bd_mgt_sn": str(i)})
                             for i in range(start, min(start + 100, 504))])
        rows, notes = v.search(LAT, LON, get=get)
        self.assertEqual(len(rows), 504)
        self.assertEqual(len(set(r.address for r in rows)), 504)
        self.assertTrue(all(r.name.startswith("명칭 미제공") for r in rows))
        self.assertTrue(all(r.category == r.subtype == "" for r in rows))
        self.assertIn(("LT_C_SPBD", 6), calls)
        self.assertTrue(any("504" in note and "보존" in note for note in notes))

    def test_name_alias_case_and_anonymous_geometry(self):
        def get(params):
            return (response([feature("one", {"BULD_NM": "실제 반환 건물명"}),
                              feature(properties={"other": "A"}),
                              feature(properties={"other": "B"})])
                    if params["data"] == "LT_C_SPBD" else empty())
        rows, _ = v.search(LAT, LON, get=get)
        self.assertEqual(len(rows), 3)
        self.assertIn("실제 반환 건물명", [r.name for r in rows])
        self.assertEqual(len({r.address for r in rows}), 3)

    def test_duplicate_identifier_is_one_candidate(self):
        def get(params):
            return response([feature("same"), feature("same")]) if params["data"] == "LT_C_SPBD" else empty()
        rows, _ = v.search(LAT, LON, get=get)
        self.assertEqual(len(rows), 1)

    def test_rejected_data_code_is_not_treated_as_absence(self):
        def get(params):
            if params["data"] == "LT_C_WGISARECO":
                return {"response": {"status": "ERROR", "error": {
                    "code": "INVALID_RANGE", "text": "data 파라미터 범위 오류: LT_C_WGISARECO"}}}
            return response([feature("one")]) if params["data"] == "LT_C_SPBD" else empty()
        rows, notes = v.search(LAT, LON, get=get)
        self.assertEqual(len(rows), 1)
        self.assertTrue(any("조회 미완료" in note and "LT_C_WGISARECO" in note for note in notes))

    def test_other_range_error_remains_a_failure(self):
        def get(params):
            return {"response": {"status": "ERROR", "error": {
                "code": "INVALID_RANGE", "text": "size 파라미터 오류"}}}
        rows, notes = v.search(LAT, LON, get=get)
        self.assertEqual(rows, [])
        self.assertTrue(any("조회 실패" in note and "INVALID_RANGE" in note for note in notes))
        self.assertFalse(any("코드가 2D" in note for note in notes))

    def test_default_request_includes_domain_and_preserves_input(self):
        params = {"key": "FAKE_TEST_KEY", "data": "LT_C_SPBD"}
        with patch.object(v.requests, "get") as http:
            http.return_value.json.return_value = empty()
            v._default_get(params)
            sent = http.call_args.kwargs["params"]
            self.assertEqual(sent["domain"], "http://localhost:8501")
            self.assertEqual(sent["key"], "FAKE_TEST_KEY")
            self.assertNotIn("domain", params)

    def test_auth_error_does_not_echo_secret(self):
        def get(params):
            return {"response": {"status": "ERROR", "error": {
                "code": "INCORRECT_KEY", "text": "key=FAKE_TEST_KEY"}}}
        rows, notes = v.search(LAT, LON, get=get)
        self.assertEqual(rows, [])
        self.assertNotIn("FAKE_TEST_KEY", " ".join(notes))


if __name__ == "__main__":
    unittest.main()
