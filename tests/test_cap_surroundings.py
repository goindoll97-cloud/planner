from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, Polygon, box, mapping
from shapely.ops import transform

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_surroundings as s
from engine.stage2.cap_site_lookup import Candidate
from engine.stage2.project import Stage2Project
from engine.stage2.storage import save_project, load_project

CENTER = (129.35893422223296, 35.47790404772272)
TO_M = Transformer.from_crs(4326, 5179, always_xy=True).transform
TO_LL = Transformer.from_crs(5179, 4326, always_xy=True).transform
X, Y = TO_M(*CENTER)


def geo(x1, y1, x2=None, y2=None):
    geom = Point(X + x1, Y + y1) if x2 is None else box(X + x1, Y + y1, X + x2, Y + y2)
    return mapping(transform(TO_LL, geom))


def obj(identifier, name="가상 공장", geometry=None):
    return Candidate(name, "을종", "공업시설", "가상 주소", 200, "가상 시험자료", identifier,
                     geo(200, 0, 220, 20) if geometry is None else geometry, {"record_id": identifier})


def project(objects=None):
    p = Stage2Project("map-test", "가상 회사", cap_required=True, cap_selected=True, scope_confirmed=True, cap_group="2군")
    p.set_field("business.address", "주소", "울산 남구 용연로 184", "USER_CONFIRMED")
    s.save_survey(p, objects or [obj("outside")], center=CENTER)
    s.save_boundary(p, geo(-100, -100, 100, 100), "가상 부지 도면", confirmed=True)
    return p


class SurroundingsTests(unittest.TestCase):
    def test_polygon_relations_do_not_exclude_crossing_or_point_candidates(self):
        rows = [obj("inside", geometry=geo(-20, -20, 20, 20)),
                obj("outside", geometry=geo(200, 0, 220, 20)),
                obj("crossing", geometry=geo(80, 0, 120, 20)),
                obj("point", geometry=geo(0, 0)),
                Candidate("좌표 없음", "", "", "", None, "가상", "missing")]
        p = project(rows)
        found = {row["object_id"]: row for row in s.annotate(p)}
        self.assertEqual(found["inside"]["relation"], "INSIDE")
        self.assertEqual(found["outside"]["relation"], "OUTSIDE")
        self.assertAlmostEqual(found["outside"]["boundary_distance_m"], 100, delta=.1)
        self.assertEqual(found["crossing"]["relation"], "CROSSES")
        self.assertEqual(found["point"]["relation"], "POINT_INSIDE")
        self.assertEqual(found["missing"]["relation"], "NO_GEOMETRY")
        self.assertEqual(len(s.survey(p)["objects"]), 5)
        self.assertTrue(all(row["category"] == "" for row in s.survey(p)["objects"]))

    def test_holes_and_boundary_contacts(self):
        outer = [(129.35,35.47),(129.37,35.47),(129.37,35.49),(129.35,35.49),(129.35,35.47)]
        hole = [(129.355,35.475),(129.365,35.475),(129.365,35.485),(129.355,35.485),(129.355,35.475)]
        touching = Polygon([outer[1],(129.38,35.47),(129.38,35.49),outer[2],outer[1]])
        p = project([obj("hole", geometry=mapping(Point(129.36,35.48))), obj("touch", geometry=mapping(touching))])
        s.save_boundary(p, mapping(Polygon(outer,[hole])), "가상 도면", confirmed=True)
        found = {r["object_id"]:r for r in s.annotate(p)}
        self.assertEqual(found["hole"]["relation"], "OUTSIDE")
        self.assertEqual(found["touch"]["relation"], "TOUCHES")

    def test_grouping_requires_same_name_nearness_and_same_relation(self):
        p = project([obj("a", geometry=geo(200,0,220,20)), obj("b", geometry=geo(250,0,270,20)),
                     obj("far", geometry=geo(500,0,520,20)), obj("internal", geometry=geo(0,0,20,20)),
                     obj("other", name="다른 회사", geometry=geo(230,0,240,20)),
                     obj("unnamed-a", name="명칭 미제공 · a", geometry=geo(280,0,290,20)),
                     obj("unnamed-b", name="명칭 미제공 · b", geometry=geo(291,0,300,20))])
        groups = [set(g["members"]) for g in s.group_suggestions(p,60)]
        self.assertIn({"a","b"}, groups)
        self.assertIn({"far"}, groups)
        self.assertIn({"internal"}, groups)
        self.assertIn({"other"}, groups)
        self.assertIn({"unnamed-a"}, groups)
        self.assertIn({"unnamed-b"}, groups)
        self.assertEqual(len(s.survey(p)["objects"]),7)

    def test_confirmed_group_import_stays_hold_and_is_idempotent(self):
        p = project()
        group = s.save_group(p,"확인할 외부 시설",["outside"],confirmed=True)
        self.assertTrue(s.import_group(p,group["group_id"]))
        self.assertFalse(s.import_group(p,group["group_id"]))
        self.assertEqual(len(f8.saved_rows(p)),1)
        row = f8.saved_rows(p)[0]
        self.assertEqual(row["보호대상 구분"],"")
        self.assertEqual(row["사업장 경계와 거리(m)"],"")
        self.assertFalse(row["500m 범위 전체 확인"])
        self.assertEqual(p.get_field(f8.SITE_KEY).status,"HOLD")
        self.assertEqual(p.get_field(f8.REVIEW_KEY).status,"HOLD")

    def test_internal_group_is_preserved_but_not_imported_as_surrounding(self):
        p=project([obj("inside",geometry=geo(-20,-20,20,20))])
        group=s.save_group(p,"내부 건물",["inside"],confirmed=True)
        with self.assertRaises(ValueError): s.import_group(p,group["group_id"])
        self.assertEqual(len(s.survey(p)["objects"]),1)

    def test_boundary_or_data_changes_require_group_reconfirmation(self):
        p=project()
        group=s.save_group(p,"시설",["outside"],confirmed=True)
        s.import_group(p,group["group_id"])
        s.save_boundary(p,geo(-90,-90,90,90),"수정한 도면",confirmed=True)
        self.assertFalse(s.saved_groups(p)[0]["current"])
        with self.assertRaises(ValueError): s.import_group(p,group["group_id"])
        s.save_group(p,"시설",["outside"],confirmed=True)
        s.save_survey(p,[obj("outside",geometry=geo(250,0,270,20))],center=CENTER)
        self.assertFalse(s.saved_groups(p)[0]["current"])
        self.assertEqual(p.get_field(f8.SITE_KEY).status,"HOLD")

    def test_address_change_does_not_reuse_boundary_or_import(self):
        p=project()
        group=s.save_group(p,"시설",["outside"],confirmed=True)
        p.set_field("business.address","주소","다른 주소","USER_CONFIRMED")
        self.assertFalse(s.is_current(p))
        self.assertIsNone(s.boundary(p))
        self.assertFalse(s.saved_groups(p)[0]["current"])
        with self.assertRaises(ValueError): s.import_group(p,group["group_id"])

    def test_boundary_validation_does_not_silently_repair_shapes(self):
        p=project()
        invalid={"type":"Polygon","coordinates":[[[129,35],[130,36],[129,36],[130,35],[129,35]]]}
        with self.assertRaises(ValueError): s.save_boundary(p,invalid,"도면",confirmed=True)
        with self.assertRaises(ValueError): s.save_boundary(p,geo(0,0),"도면",confirmed=True)
        with self.assertRaises(ValueError): s.save_boundary(p,geo(-10,-10,10,10),"",confirmed=True)
        with self.assertRaises(ValueError): s.save_boundary(p,geo(-10,-10,10,10),"도면",confirmed=False)
        with self.assertRaises(ValueError): s.checked_geometry({"type":"Point","coordinates":[float('nan'),35]})

    def test_radius_expands_to_cover_boundary_in_metric_coordinates(self):
        p=project()
        s.save_boundary(p,geo(-700,-100,700,100),"넓은 가상 부지",confirmed=True)
        self.assertGreater(s.required_radius(p,CENTER),1200)
        self.assertIn("포함하지 못",s.coverage_warning(p))
        from engine.stage2 import cap_vworld_lookup as vworld
        with patch.object(vworld,"api_key",return_value="fake"), patch.object(vworld,"geocode",return_value=CENTER), \
             patch.object(vworld,"search",return_value=([obj("outside")],[])) as search:
            s.collect(p,expand_to_boundary=True)
        self.assertGreater(search.call_args.kwargs["radius_m"],1200)
        self.assertIn("기하학적으로 포함",s.coverage_warning(p))

    def test_geojson_and_storage_keep_original_geometry_and_provenance(self):
        raw=obj("outside")
        p=project([raw])
        group=s.save_group(p,"외부 시설",["outside"],confirmed=True)
        exported=s.geojson_export(p)
        found=next(f for f in exported["features"] if f["id"]=="outside")
        self.assertEqual(found["properties"]["attributes"],raw.attributes)
        self.assertEqual(found["properties"]["group_id"],group["group_id"])
        self.assertEqual(found["geometry"],raw.geometry)
        self.assertEqual(found["properties"]["legal_classification"],"미확정")
        json.dumps(exported,allow_nan=False)
        with tempfile.TemporaryDirectory() as tmp:
            save_project(p,Path(tmp))
            restored=load_project(p.project_id,Path(tmp))
        self.assertTrue(s.saved_groups(restored)[0]["current"])
        self.assertEqual(s.survey(restored)["objects"][0]["object_id"],"outside")

    def test_legacy_candidates_without_geometry_are_retained(self):
        p=project()
        s.save_survey(p,[Candidate("옛 후보","","","주소",20,"기존 진단")],center=CENTER)
        rows=s.annotate(p)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["relation"],"NO_GEOMETRY")
        self.assertTrue(rows[0]["object_id"])

    def test_drawings_preserve_disconnected_parcels(self):
        combined=s.boundary_from_drawings([geo(-20,-20,20,20),geo(200,0,220,20)])
        self.assertEqual(s.checked_geometry(combined).geom_type,"MultiPolygon")
        with self.assertRaises(ValueError): s.boundary_from_drawings([])

    def test_group_requires_explicit_confirmation_and_known_members(self):
        p=project()
        with self.assertRaises(ValueError): s.save_group(p,"시설",["outside"],confirmed=False)
        with self.assertRaises(ValueError): s.save_group(p,"시설",["missing"],confirmed=True)
        s.clear_boundary(p)
        with self.assertRaises(ValueError): s.save_group(p,"시설",["outside"],confirmed=True)


if __name__=="__main__": unittest.main()
