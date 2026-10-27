"""물질·설비 사실은 한 곳(자료 접수 기록)을 기준으로 유지됩니다.

- 별지 제1·6호에서 고친 값은 자료 접수 기록에 ‘직접 입력’으로 되돌려 적힙니다.
- 자료 접수에서 보낼 때는 별지 표를 덮어쓰지 않고 같은 번호의 행에 합칩니다(별지에서만 적은 칸은 유지).
- 별지에서 지운 행은 자료 접수에서도 제외되고, 되살릴 수 있습니다.
- 자료마다 달라 아직 정하지 않은 값은 옛 값을 남기지 않고 비웁니다.
"""
import unittest

from engine.stage2 import cap_chemical_upload as cu
from engine.stage2 import cap_form6_workspace as f6
from engine.stage2 import cap_workspace as ws
from engine.stage2 import evidence_workspace as ew
from engine.stage2.project import Stage2Project

FACILITIES = "설비번호,설비명,용량(m3),운전압력(MPa),시설유형,물질성상,비중\nTK-1,가상 탱크,10,0.1,저장탱크,액체,0.8\nTK-2,가상 보조탱크,5,0.1,저장탱크,액체,0.8\n"
MATERIALS = "제품코드,제품명,CAS 번호,함량(%)\nP-1,가상 에탄올,64-17-5,95\n"


def _chosen(project, entity, field):
    slot = next((s for s in ew.slots(project) if s["key"] == f"{entity}|{field}"), None)
    return slot["chosen"]["value"] if slot and slot["chosen"] else None


class SingleSourceTests(unittest.TestCase):
    def setUp(self):
        self.p = Stage2Project(project_id="one", company_name="가상")
        ew.ingest(self.p, "f.csv", FACILITIES.encode(), "facility")
        ew.ingest(self.p, "m.csv", MATERIALS.encode(), "material")
        ew.confirm_auto(self.p, [s["key"] for s in ew.slots(self.p) if s["method"] == "AUTO"])
        ew.approve_bulk(self.p)
        ew.publish(self.p, replace_existing=True)

    def workspace_rows(self):
        return ws.facility_editor_rows(self.p)

    def test_edit_in_form1_flows_back_and_is_not_undone_by_the_next_send(self):
        rows = self.workspace_rows()
        rows[0]["용량"] = 12
        ws.save_facility_rows(self.p, rows)
        self.assertEqual(_chosen(self.p, "facility:TK-1", "capacity"), 12.0)
        fact = next(s for s in ew.slots(self.p) if s["key"] == "facility:TK-1|capacity")["chosen"]
        self.assertEqual(fact["document"], "별지 제1호 직접 입력")
        ew.publish(self.p, replace_existing=True)                 # 다시 보내도 별지에서 고친 값이 유지됨
        self.assertEqual(float(next(r for r in self.workspace_rows() if r["설비번호"] == "TK-1")["용량"]), 12.0)
        self.assertEqual(next(r for r in self.p.get_field("inventory.facilities").value if r["설비번호"] == "TK-1")["용량"], 12.0)

    def test_send_merges_into_form1_table_and_keeps_form_only_columns(self):
        rows = self.workspace_rows()
        rows[0]["분자량"] = 46.07                                   # 별지에서만 적는 값
        ws.save_facility_rows(self.p, rows)
        ew.ingest(self.p, "g.csv", "설비번호,운전온도(℃)\nTK-1,30\nTK-3,25\n".encode(), "facility")
        ew.confirm_auto(self.p, [s["key"] for s in ew.slots(self.p) if s["method"] == "AUTO"])
        ew.approve_bulk(self.p)
        ew.publish(self.p, replace_existing=True)
        saved = {r["설비번호"]: r for r in self.p.get_field(ew.WORKSPACE_FACILITIES_KEY).value}
        self.assertEqual(float(saved["TK-1"]["운전온도(℃)"]), 30.0)    # 새 자료가 별지 표에 조용히 무시되지 않음
        self.assertEqual(float(saved["TK-1"]["분자량"]), 46.07)       # 별지에서만 적은 칸은 그대로
        self.assertIn("TK-3", saved)                                 # 새 설비는 별지 표에 추가됨

    def test_row_deleted_in_form1_is_excluded_and_can_be_restored(self):
        rows = [r for r in self.workspace_rows() if r["설비번호"] != "TK-2"] if self.p.get_field(ew.WORKSPACE_FACILITIES_KEY) else None
        if rows is None:                                             # 별지 표가 아직 없으면 먼저 한 번 저장
            ws.save_facility_rows(self.p, self.workspace_rows())
            rows = [r for r in self.workspace_rows() if r["설비번호"] != "TK-2"]
        ws.save_facility_rows(self.p, rows)
        self.assertIn("facility:TK-2", ew.excluded(self.p))
        self.assertFalse(any(s["entity"] == "facility:TK-2" for s in ew.slots(self.p)))
        ew.publish(self.p, replace_existing=True)
        self.assertNotIn("TK-2", {r["설비번호"] for r in self.p.get_field("inventory.facilities").value})   # 다시 보내도 되살아나지 않음
        ew.restore(self.p, "facility:TK-2")
        self.assertTrue(any(s["entity"] == "facility:TK-2" for s in ew.slots(self.p)))

    def test_disputed_value_is_cleared_not_silently_kept(self):
        ws.save_facility_rows(self.p, self.workspace_rows())
        ew.ingest(self.p, "old.csv", "설비번호,용량(m3)\nTK-2,7\n".encode(), "facility")   # 자료끼리 다름
        ew.publish(self.p, replace_existing=True)
        published = next(r for r in self.p.get_field("inventory.facilities").value if r["설비번호"] == "TK-2")
        self.assertEqual(published["용량"], "")

    def test_later_document_against_a_form_edit_becomes_a_question(self):
        rows = self.workspace_rows()
        rows[0]["용량"] = 12
        ws.save_facility_rows(self.p, rows)
        ew.ingest(self.p, "new.csv", "설비번호,용량(m3)\nTK-1,15\n".encode(), "facility")
        conflicts = {(i["entity"], i["field"]) for i in ew.review_queue(self.p) if i["kind"] == "충돌"}
        self.assertIn(("facility:TK-1", "capacity"), conflicts)

    def test_form6_upload_edit_and_delete_flow_back_by_cas(self):
        rows = cu.to_inventory_rows([{"제품명": "가상 톨루엔", "CAS No.": "108-88-3", "함량(%)": "99", "_ok": True}])
        current = self.p.get_field("inventory.chemicals").value
        self.p.set_field("inventory.chemicals", "화학물질 목록", [*current, *rows], "USER_CONFIRMED")
        ew.sync_from_form(self.p, "material", rows, "물질 목록 파일 t.csv")
        self.assertEqual(_chosen(self.p, "material:108-88-3", "cas"), "108-88-3")
        # 같은 CAS를 가진 기존 대상(P-1)은 CAS로 찾아 같은 대상에 적음
        self.p.set_field("cap.chemical.details", "화학물질 상세", [dict(r) for r in self.p.get_field("inventory.chemicals").value], "USER_CONFIRMED")
        f6.save_properties(self.p, [{"CAS 번호": "64-17-5", "물질상태": "액체", "비중": "0.79"}])
        self.assertEqual(_chosen(self.p, "material:P-1", "density"), 0.79)
        ew.sync_from_form(self.p, "material", [], "별지 제6호 물질 삭제", removed_ids=["108-88-3"])
        self.assertIn("material:108-88-3", ew.excluded(self.p))

    def test_sync_never_breaks_a_form_save(self):
        project = Stage2Project(project_id="empty", company_name="가상")
        self.assertEqual(ew.sync_from_form(project, "facility", [{"설비번호": "X", "용량": "글자"}], "별지 제1호 직접 입력"), 0)
        self.assertEqual(ew.sync_from_form(project, "unknown", [], "x"), 0)


if __name__ == "__main__":
    unittest.main()


class NoSpuriousEditsTests(unittest.TestCase):
    def test_saving_form1_unchanged_adds_nothing_even_when_product_was_a_code(self):
        p = Stage2Project(project_id="code", company_name="가상")
        ew.ingest(p, "m.csv", MATERIALS.encode(), "material")
        ew.ingest(p, "f.csv", "설비번호,설비명,취급제품,용량(m3)\nTK-1,가상 탱크,P-1,10\n".encode(), "facility")
        ew.confirm_auto(p, [s["key"] for s in ew.slots(p) if s["method"] == "AUTO"])
        ew.approve_bulk(p)
        ew.publish(p, replace_existing=True)
        before = len(ew.graph_facts(p))
        ws.save_facility_rows(p, ws.facility_editor_rows(p))        # 아무것도 고치지 않고 저장
        self.assertEqual(len(ew.graph_facts(p)), before)
        self.assertFalse(any(f["method"] == "manual" for f in ew.graph_facts(p)))
