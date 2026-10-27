"""‘계획서 끝까지 연습 자료’(demo_full_company)로 안내서대로 처음부터 내려받기까지 가 봅니다.

사람이 문서를 보고 화면에 적는 일을 엔진 함수로 흉내 냅니다. 이 환경에는 법령 기준표(별표 1~4) 승인 DB가 없으므로
- 사고시나리오 대상 판정(별지 제12호 제안 목록)은 승인 DB가 있어야 나옵니다. 여기서는 그 다음 단계부터 보려고
  시나리오 목록을 직접 저장합니다(화면에서는 제안된 목록에 같은 값을 넣고 저장하는 단계).
- 끝에 남는 것은 승인 DB가 필요한 항목과 검토 안내뿐이어야 합니다.
"""
import unittest
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from docx import Document

from engine.stage2 import (cap_form2_workspace as f2, cap_form3_workspace as f3, cap_form4_workspace as f4,
                           cap_form5_workspace as f5, cap_form6_workspace as f6, cap_form7_workspace as f7,
                           cap_form8_workspace as f8, cap_form9_workspace as f9, cap_form10_workspace as f10,
                           cap_form11_workspace as f11, cap_form14_workspace as f14, cap_form16_workspace as f16,
                           cap_impact_workspace as iw, cap_narrative_workspace as nw, cap_scenario_workspace as sc,
                           cap_workspace as ws, demo_full_company as d, evidence_workspace as ew,
                           psm_narrative_workspace as pn, report_export as rx)
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.project import EvidenceRef

D, C = d.DATA, d.DATA["company"]
# 승인 DB(법령 기준표)가 있어야 풀리는 것과, 최종 제출 전 사람이 확인하라는 안내
ALLOWED = ("승인 DB", "법령 DB", "별표 2", "별표 3", "Stage 1 판정", "적용하지 않습니다")


def _ref(name):
    content = d.files()[name]
    return EvidenceRef(source_type="COMPANY_EVIDENCE", source_name=name, sha256=sha256(content).hexdigest(), location=name)


def walk():
    p = create_direct_cap_project(d.COMPANY, address=C["주소"], cap_group="")
    for name, kind in d.UPLOAD.items():                                              # ① 자료 올리기
        ew.ingest(p, name, d.files()[name], kind)
    questions = [i for i in ew.review_queue(p) if i["kind"] != "확인 필요"] + ew.problems(p)
    ew.approve_bulk(p)                                                                # ② 확인
    ew.confirm_auto(p, [s["key"] for s in ew.slots(p) if s["method"] == "AUTO"])     # ④ 마지막 확인
    ew.publish(p, replace_existing=True)                                              # ④ 보내기
    p.cap_group = C["작성수준"]                                                        # 작성수준 확인
    p.set_field("cap.business.writing_level", "작성수준", f"{p.cap_group} 사업장", "USER_CONFIRMED", note="회사 확인값")
    rows = ws.facility_editor_rows(p)                                                 # 별지 제1호
    extra = {f["id"]: f["form1"] for f in D["facilities"]}
    for row in rows:
        row.update(extra.get(row.get("설비번호"), {}))
    ws.save_facility_rows(p, rows)
    f2.save_submission(p, C["제출구분"], C["제출 사유"], C["단위공장명"])                 # 별지 제2호
    f3.save_fields(p, {f["id"]: C.get(f["id"], C["주소"] if f["id"] == "address" else "") for f in f3.fields()})
    f4.save_inputs(p, D["process"]["총괄 개요"], D["process"]["공정개요"], D["process"]["입출하 시설 수"])
    f5.save_overview(p, D["process"]["단위공장 개요"])
    f6.save_properties(p, [{"CAS 번호": pr["cas"], "물질상태": d._sds_state(pr["state"]), "비중": str(pr["density"]), **pr["props"]}
                           for pr in D["products"]])
    reps = [pr for pr in D["products"] if pr["code"] in ("P-01", "P-03")]
    f7.save_rows(p, [{**f7.draft_row(p, pr["cas"], pr["name"], pr["hazard"]["선정 사유"]), **pr["hazard"],
                      "SDS 파일명": pr["props"]["SDS 파일명"], "SDS 개정일": pr["props"]["SDS 개정일"]} for pr in reps])
    imported, _ = f8.import_company_rows(D["surroundings"], [])                       # 별지 제8호
    f8.save(p, imported, no_target=False, scope_reviewed=True)
    f8.save_review(p, {key: True for key, _ in f8.REVIEW_ITEMS}, D["survey"]["source"], D["survey"]["method"],
                   D["survey"]["map_numbers"], [_ref("07_주변보호대상_지도.png")])
    specs = {f["id"]: f["spec"] for f in D["facilities"]}                             # 별지 제9·10·11호
    f9.save_specs(p, [{**r, **specs.get(r["구분기호"], {})} for r in f9.rows(p)])
    dikes = {f["id"]: f["dike"] for f in D["facilities"]}
    f10.save(p, [{**r, **dikes.get(r.get("구분기호"), {})} for r in f10.edit_rows(p)], D["dike_rule"]["비율(%)"], D["dike_rule"]["근거"])
    f11.save(p, D["detectors"])
    f11.attach_evidence(p, [_ref("06_가스감지기_배치도.png")])
    for fact in nw.DECISION_FACTS:                                                    # 서술형 결정사항
        values = D["narrative"].get(fact.key.split(".")[-1])
        if values:
            pn.save_fact(p, fact, values)
    for item in f16.items("internal"):                                                # 별지 제16호
        if item["id"] in D["emergency"]:
            f16.save_text(p, item, D["emergency"][item["id"]])
    return p, questions


def scenarios(p):
    names = {pr["code"]: pr["name"] for pr in D["products"]}
    rows = []
    for f in D["facilities"]:
        kind = sc.FIRE if f["product"] == "P-01" else sc.TOXIC
        rows.append({"단위공장": C["단위공장명"], "사고시나리오명": f"{f['id']} {names[f['product']]} {'화재' if kind == sc.FIRE else '누출'}",
                     "대상 설비번호": f["id"], "유해화학물질명": names[f["product"]], "사고유형": kind,
                     "취급량(kg)": f["inventory_kg"], **D["scenario_inputs"][f["id"]], "선정 근거": "연습"})
    sc.save_scenarios(p, rows)
    f14.save(p, [{**r, **D["frequency"][r["사고시나리오명"].split()[0]]} for r in f14.rows(p)])
    impacts = iw.evaluate(p)
    report = iw.report_docx(p, impacts)
    ref = EvidenceRef(source_type="PROGRAM_OUTPUT", source_name="영향범위_분석_근거서.docx", sha256=sha256(report).hexdigest())
    return impacts, iw.apply_to_forms(p, impacts, evidence_refs=[ref])


class FullDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.questions = walk()
        cls.impacts, cls.applied = scenarios(cls.p)

    def test_package_has_every_document_the_guide_names(self):
        with ZipFile(BytesIO(d.full_demo_zip())) as z:
            names = set(z.namelist())
            guide = z.read("README_테스트_안내서.txt").decode("utf-8")
        self.assertEqual(names, set(d.files()) | {"README_테스트_안내서.txt"})
        for name in d.files():
            self.assertIn(name, guide, name)
        for name, kind in d.UPLOAD.items():
            self.assertEqual(ew.classify_document(name, d.files()[name]), kind)

    def test_clean_company_data_raises_no_questions(self):
        self.assertEqual(self.questions, [])

    def test_every_company_input_form_is_complete(self):
        p = self.p
        self.assertEqual(f3.missing_labels(p), [])
        self.assertEqual(f4.missing(p), [])
        self.assertEqual(f5.missing(p), [])
        self.assertEqual(f8.needs(p), [])
        self.assertEqual(f9.needs(p), [])
        self.assertEqual(f10.needs(p), [])
        self.assertEqual(f11.needs(p), [])
        self.assertEqual(f14.needs(p), [])
        self.assertEqual(f16.missing(p), [])
        self.assertTrue(all(any(word in need for word in ALLOWED) for need in f7.needs(p)), f7.needs(p))

    def test_scenarios_compute_from_the_package_values(self):
        self.assertEqual(len(self.impacts), 4)
        self.assertTrue(all(i.radius_m and not i.problems for i in self.impacts), [(i.name, i.problems) for i in self.impacts])
        self.assertGreaterEqual(self.applied["scenarios"], 1)

    def test_only_legal_db_items_remain(self):
        state = rx.evaluate(self.p, "CAP")
        left = [i.message for i in list(state.text_issues) + list(state.manual_issues) if i.status != "PASS"]
        self.assertTrue(left)
        self.assertEqual([m for m in left if not any(word in m for word in ALLOWED)], [])

    def test_docx_contains_the_company_values(self):
        doc = Document(BytesIO(build_cap_baseline_draft(self.p)))
        text = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        for value in (C["representative"], C["registration_no"], "GD-01", "가상 아파트 단지", "TK-01", "CY-01 가상 액화암모니아 누출"):
            self.assertIn(value, text)

    def test_evidence_survives_resave(self):
        f8.save(self.p, f8.saved_rows(self.p), no_target=False, scope_reviewed=True)
        f11.save(self.p, f11.saved_rows(self.p))
        self.assertTrue(self.p.get_field(f8.SITE_KEY).evidence)
        self.assertTrue(self.p.get_field(f11.GAS_KEY).evidence)


if __name__ == "__main__":
    unittest.main()
