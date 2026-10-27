"""사실 카탈로그(data/stage2/cap_fact_catalog.json)가 서식·읽기 코드와 어긋나지 않는지 확인합니다."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from engine.stage2 import cap_fact_catalog as cat
from engine.stage2 import evidence_workspace as ew

ROOT = Path(__file__).resolve().parents[1]
CORE_GRAPH_FIELDS = {"name", "product", "cas", "capacity", "pressure", "design_pressure", "temperature", "inventory",
                     "concentration", "facility_type", "substance_state", "density", "process_type"}


class CatalogShapeTests(unittest.TestCase):
    def test_catalog_loads_and_has_no_problems(self):
        facts = cat.all_facts()
        self.assertGreater(len(facts), 80)
        self.assertEqual(cat.validate(facts, cat.load_raw()), [])

    def test_every_target_form_has_company_facts(self):
        for form in (1, 3, 4, 5, 6, 7, 9, 10, 11):
            self.assertTrue(cat.facts(forms=[form], company=True), f"별지 제{form}호")
        # 별지 제8호는 지도 조회로 채우는 보호대상 사실로 따로 둡니다
        self.assertTrue(all(f.source == "survey" for f in cat.facts(forms=[8], kinds=["target"])))

    def test_repeated_fact_appears_once(self):
        seen = {}
        for fact in cat.facts(company=True):
            if fact.identifier or fact.field_key.startswith("@"):
                continue
            key = (fact.kind, fact.field_key, fact.column)
            self.assertNotIn(key, seen, f"{fact.id}와 {seen.get(key)}가 같은 칸입니다")
            seen[key] = fact.id
        representative = cat.get("site.representative")
        self.assertEqual(representative.forms, (3, 16))
        self.assertEqual(cat.get("material.cas").used_in_text, "별지 제1·4·5·6·7·9호")

    def test_derived_values_are_kept_apart_from_company_facts(self):
        derived = cat.facts(company=False)
        self.assertTrue({"computed", "legal", "survey"} >= {f.source for f in derived})
        self.assertTrue(all(f.source in cat.COMPANY_SOURCES for f in cat.facts(company=True)))
        self.assertTrue(cat.facts(kinds=["computed"]))
        self.assertTrue(cat.facts(kinds=["legal"]))
        for fact in derived:
            self.assertNotEqual(fact.source, "company")

    def test_group_filter(self):
        everything = cat.facts()
        self.assertEqual({f.id for f in cat.facts(group="1군")} | {f.id for f in cat.facts(group="2군")},
                         {f.id for f in everything})

    def test_forms_text(self):
        self.assertEqual(cat.forms_text([16, 3, 4, 3]), "별지 제3·4·16호")
        self.assertEqual(cat.forms_text([]), "")

    def test_validate_reports_common_mistakes(self):
        broken = cat.Fact(id="x", name="", kind="what", source="company", used_in=())
        problems = cat.validate([broken])
        for word in ("이름", "종류", "used_in", "머리글", "식별자"):
            self.assertTrue(any(word in p for p in problems), word)
        a = cat.Fact(id="a", name="A", kind="site", source="company", evidence_field="a", headers=("같은 이름",),
                     file="site_info", field_key="k.a", used_in=(cat.Use(3, "A"),))
        b = cat.Fact(id="b", name="B", kind="site", source="company", evidence_field="b", headers=("같은이름",),
                     file="site_info", field_key="k.b", used_in=(cat.Use(3, "B"),))
        self.assertTrue(any("다른 사실도" in p for p in cat.validate([a, b])))


class CatalogMatchesReaderTests(unittest.TestCase):
    def test_header_key_matches_reader_normalization(self):
        for fact in cat.all_facts():
            for header in fact.headers:
                self.assertEqual(cat.header_key(header), ew.norm(header))

    def test_headers_agree_with_existing_reader_aliases(self):
        for kind in ("facility", "material"):
            for key, field in cat.header_map(kind).items():
                if key in ew.ALIASES:
                    self.assertEqual(ew.ALIASES[key], field, f"{kind}: {key}")

    def test_core_graph_fields_keep_their_names(self):
        fields = {f.evidence_field for f in cat.facts(kinds=["facility", "material"]) if f.evidence_field}
        self.assertTrue(CORE_GRAPH_FIELDS - {"inventory"} <= fields | {"inventory"})
        new_fields = fields - CORE_GRAPH_FIELDS
        self.assertTrue(new_fields)
        self.assertFalse(new_fields & set(ew.CHOICES))

    def test_identifier_headers_include_reader_ids(self):
        self.assertTrue({"설비번호", "시설번호", "장치번호"} <= cat.identifier_headers("facility"))
        self.assertTrue({"제품코드", "물질코드"} <= cat.identifier_headers("material"))
        self.assertIn("감지기번호", cat.identifier_headers("detector"))


class CatalogCoversFormSourcesTests(unittest.TestCase):
    """카탈로그는 별지 서식 정의·작성요건·항목 점검에서 만들었으므로, 그 재료의 키가 모두 사실이나 제외 목록에 있어야 합니다."""

    def _known_keys(self):
        keys = set(cat.excluded_keys())
        for fact in cat.all_facts():
            keys.add(fact.field_key)
            keys.update(k for k, _ in fact.targets)
        return keys

    def test_form3_schema_fields_are_facts(self):
        schema = json.loads((ROOT / "data" / "stage2" / "cap_forms" / "form03.json").read_text(encoding="utf-8"))
        keys = {f["key"] for s in schema["sections"] for f in s.get("fields", [])}
        self.assertTrue(keys)
        self.assertEqual(keys - self._known_keys(), set())

    def test_form1_facility_columns_are_facts(self):
        schema = json.loads((ROOT / "data" / "stage2" / "cap_forms" / "form01.json").read_text(encoding="utf-8"))
        columns = {c["id"] for c in schema["sections"][0]["columns"]}
        known = {f.column for f in cat.facts(kinds=["facility"])} | {"용량단위"}   # 용량 단위는 머리글 단위로 읽음
        self.assertEqual(columns - known, set())

    def test_coverage_audit_keys_for_forms_1_and_3_to_11_are_facts(self):
        from engine.stage2 import cap_form_coverage as cov
        from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

        project = CAPForm1EngineTests()._project()
        items = [i for i in cov.audit_cap_form_coverage(project) if i.form_no in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11)]
        keys = {k for i in items for k in i.field_keys}
        self.assertTrue(keys)
        self.assertEqual(keys - self._known_keys(), set())

    def test_requirement_field_keys_for_basic_and_facility_items_are_facts(self):
        from engine.stage2.requirements import cap_requirement_specs

        wanted = {"cap.basic.business", "cap.basic.facility_overview", "cap.basic.chemical_inventory",
                  "cap.basic.hazard_info", "cap.facility.process_overview", "cap.facility.equipment_specs",
                  "cap.safety.detectors"}
        specs = [s for s in cap_requirement_specs("1군") if s.key in wanted]
        self.assertEqual({s.key for s in specs}, wanted)
        keys = {k for s in specs for k in s.field_keys} - {"business.company_name"}
        self.assertEqual(keys - self._known_keys(), set())


if __name__ == "__main__":
    unittest.main()
