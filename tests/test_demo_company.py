"""큰 가상 회사 자료를 정답표로 채점하고, 처음 보는 표기에도 같은 방식으로 대처하는지 확인합니다.

원칙
- 자동으로 채운 값은 정답과 달라서는 안 됩니다.
- 그대로 쓸 수 없는 값은 원인을 추측하지 않고 ‘어떤 검사에 걸렸는지’로 묶어 묻습니다.
- 같은 표기·같은 열·같은 머리글은 한 번만 묻고, 답은 같은 경우 전체에 적용합니다.
이 자료는 프로그램을 만든 쪽이 만든 것이므로 실제 정확도가 아니라 회귀 시험입니다.
"""
import json
import math
import unittest
from io import BytesIO
from zipfile import ZipFile

from engine.stage2 import demo_company as dc
from engine.stage2 import evidence_workspace as ew
from engine.stage2 import scenario_triage
from engine.stage2.project import Stage2Project


def _same(got, expected):
    if isinstance(expected, float) and isinstance(got, (int, float)) and not isinstance(got, bool):
        return math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-9)
    return got == expected


def _load_demo(project):
    for name, content in dc.files().items():
        kind, hint = dc.UPLOAD[name]
        ew.ingest(project, name, content, kind, hint)


class LargeDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.truth = dc.truth()
        cls.codes = {v["name"]: e.split(":", 1)[1] for e, v in cls.truth.items() if e.startswith("material:")}

    def setUp(self):
        self.p = Stage2Project(project_id="large", company_name="가상")
        _load_demo(self.p)

    def value(self, slot):
        got = slot["chosen"]["value"]
        return self.codes.get(got, got) if slot["field"] == "product" else got

    def slot(self, entity, field):
        return next((s for s in ew.slots(self.p) if s["key"] == f"{entity}|{field}"), None)

    def wrong_auto(self):
        wrong = []
        for slot in ew.slots(self.p):
            if not slot["chosen"] or slot["entity"] not in self.truth:
                continue
            expected = self.truth[slot["entity"]].get(slot["field"])
            if expected is None or not _same(self.value(slot), expected):
                wrong.append((slot["entity"], slot["field"], self.value(slot), expected))
        return wrong

    # ---- 자료 자체
    def test_zip_has_seven_files_readme_and_answer_key_with_valid_cas(self):
        with ZipFile(BytesIO(dc.large_demo_zip())) as z:
            names = set(z.namelist())
            key = json.loads(z.read("answer_key.json"))
        self.assertEqual(names, set(dc.files()) | {"README.txt", "answer_key.json"})
        self.assertGreaterEqual(len(dc.PLANTED), 30)
        for entity, values in key["truth"].items():
            if "cas" in values:
                self.assertTrue(ew.cas_valid(values["cas"]), entity)

    def test_files_are_classified_without_asking_except_scan(self):
        for name, content in dc.files().items():
            if name.endswith(".pdf"):
                with self.assertRaises(ValueError):
                    ew.classify_document(name, content)
            else:
                self.assertEqual(ew.classify_document(name, content), dc.UPLOAD[name][0], name)

    # ---- 처음 읽었을 때
    def test_no_auto_filled_value_disagrees_with_answer_key(self):
        # 유일한 예외는 일부러 넣은 띄어쓰기 오류: 값은 자료 그대로이고, 물질 목록과 연결이 안 된다고 따로 알립니다.
        self.assertEqual(self.wrong_auto(), [("facility:TK-104", "product", "가상자일렌", "P-04")])
        self.assertTrue(any("TK-104" in t["entity"] and "연결할 수 없습니다" in t["task"] for t in ew.tasks(self.p)))

    def test_problems_are_grouped_by_the_check_they_failed(self):
        groups = {(g["kind"], g["field"], g["raw"]): g for g in ew.problems(self.p)}
        self.assertEqual(len(groups[("text", "substance_state", "액상")]["facts"]), 29)    # 29칸 → 질문 1개
        self.assertEqual(len(groups[("text", "pressure", "상압")]["facts"]), 2)
        column = groups[("column", "pressure", "0.1")]
        self.assertEqual((column["header"], len(column["facts"])), ("운전압력", 10))         # 단위 없는 열 → 질문 1개
        for key in [("single", "inventory", "=50*0.79*1000*0.85"), ("single", "inventory", "=E15*1.84*1000*0.85"),
                    ("single", "pressure", "101.3"), ("single", "cas", "78-93-8"), ("text", "pressure", "200~400"),
                    ("text", "density", "1.41(액화)"), ("text", "facility_type", "저장조")]:
            self.assertIn(key, groups)
        reasons = {g["reason"] for g in groups.values()}
        self.assertLessEqual(reasons, {"항목 이름에 단위가 없어요", "숫자가 아니에요", "선택지에 없는 말이에요",
                                       "엑셀 계산식만 있고 계산 결과가 파일에 저장돼 있지 않아요",
                                       "CAS 번호의 형식이나 검산 숫자가 맞지 않아요", "허용 범위(0~100) 밖의 숫자예요"})
        self.assertLess(len(groups), 15)

    def test_conflicts_are_only_between_usable_values(self):
        conflicts = {(i["entity"], i["field"]) for i in ew.review_queue(self.p) if i["kind"] == "충돌"}
        self.assertEqual(conflicts, {("facility:TK-103", "capacity"), ("facility:TK-105", "name"),
                                     ("facility:TK-107", "inventory"), ("facility:RX-204", "temperature")})

    def test_reading_report_says_where_and_why(self):
        docs = {d["name"]: d for d in ew.documents(self.p)}
        ledger = docs["03_설비대장_2026.xlsx"]
        skipped = [s for t in ledger["tables"] for s in t["skipped"]]
        self.assertEqual([(s["row"], s["text"], s["reason"]) for s in skipped], [(22, "합계", "번호 칸이 비어 있음")])
        sheet = next(t for t in ledger["tables"] if t["location"] == "저장시설")
        self.assertEqual(sheet["header_row"], 3)
        self.assertIn({"header": "설비번호", "field": "id"}, sheet["columns"])
        operating = [s for t in docs["05_운전조건표_2026Q1.csv"]["tables"] for s in t["skipped"]]
        self.assertEqual([s["text"] for s in operating], ["가상 혼합조 7", "가상 혼합조 8"])   # 추측해 붙이지 않음
        self.assertIn("함량(wt%)", docs["01_제품목록_2026.xlsx"]["unmapped_columns"])
        self.assertIn("스캔본", docs["07_정기점검표_스캔.pdf"]["problem"])
        self.assertFalse(any(s["entity"].startswith("facility:가상 혼합조") for s in ew.slots(self.p)))

    # ---- 한 번씩 답했을 때
    def answer_once_per_question(self):
        """사람이 질문마다 한 번씩만 답하는 흐름. 답은 정답표에서 가져옵니다."""
        files = dc.files()
        for sha in ew.learn_column(self.p, "함량(wt%)", "concentration"):
            name = next(d["name"] for d in ew.documents(self.p) if d["sha256"] == sha)
            ew.reingest(self.p, sha, files[name])
        asked = 0
        while True:
            groups = ew.problems(self.p)
            if not groups:
                break
            group = groups[0]
            asked += 1
            entity, field = group["facts"][0]["entity"], group["field"]
            expected = self.truth[entity][field]
            if group["kind"] == "column":
                ew.learn_unit(self.p, group["sha256"], group["header"], "MPa")
            elif group["kind"] == "text":
                ew.learn_value(self.p, field, group["raw"], str(expected))
            else:
                ew.add_manual(self.p, entity, field, str(expected), "정답표", confirm=True)
        for item in ew.review_queue(self.p):
            if item["kind"] == "충돌":
                asked += 1
                ew.add_manual(self.p, item["entity"], item["field"], str(self.truth[item["entity"]][item["field"]]), "정답표", confirm=True)
        return asked

    def test_one_answer_per_question_fixes_every_place(self):
        before = sum(len(g["facts"]) for g in ew.problems(self.p))
        asked = self.answer_once_per_question()
        self.assertGreater(before, 50)
        self.assertLess(asked, 25)                                   # 칸이 아니라 질문 수만큼만 답함
        self.assertEqual(ew.problems(self.p), [])
        self.assertEqual(self.wrong_auto(), [("facility:TK-104", "product", "가상자일렌", "P-04")])
        self.assertTrue(_same(self.value(self.slot("material:P-10", "concentration")), 50.0))   # 머리글을 지정하자 개정 MSDS와의 차이가 드러나 해결됨
        self.assertTrue(_same(self.value(self.slot("facility:TK-101", "pressure")), 0.1))       # 단위를 정하자 두 자료가 교차 확인됨
        self.assertEqual(len(self.slot("facility:TK-101", "pressure")["facts"]), 2)

    def test_learned_rules_apply_to_files_uploaded_later(self):
        ew.learn_value(self.p, "substance_state", "액상", "액체")
        ew.ingest(self.p, "later.csv", "설비번호,물질상태\nTK-999,액상\n".encode(), "facility")
        self.assertEqual(self.value(self.slot("facility:TK-999", "substance_state")), "액체")

    def test_answering_everything_leaves_only_expected_gaps(self):
        self.answer_once_per_question()
        for entity, field in [("facility:TK-118", "pressure"), ("facility:TK-118", "temperature"), ("facility:RX-206", "inventory")]:
            ew.add_manual(self.p, entity, field, str(self.truth[entity][field]), "정답표", confirm=True)
        triage = scenario_triage.evaluate(self.p)
        linked = [r for r in triage["rows"] if r["linked"]]
        self.assertGreaterEqual(len(linked), 37)
        still_assumed = {r["facility"] for r in linked if "assumed" in r["value_states"].values()}
        self.assertEqual(still_assumed, {"facility:TK-190"})        # 폐기예정 탱크는 운전압력이 없는 게 정상

    def test_numbered_document_hint_is_not_applied_to_tables_with_number_column(self):
        p = Stage2Project(project_id="hint", company_name="가상")
        name = "03_설비대장_2026.xlsx"
        ew.ingest(p, name, dc.files()[name], "facility", "RX-205")
        self.assertFalse(any(f["raw"].startswith("=SUM") for f in ew.graph_facts(p)))


class UnseenInputTests(unittest.TestCase):
    """프로그램 코드와 예시 자료 어디에도 없는 표기·머리글·단위로도 같은 방식이 통하는지 확인합니다."""

    def test_never_seen_spellings_headers_and_units(self):
        p = Stage2Project(project_id="unseen", company_name="가상")
        text = ("Tag No.,설비명,운전압력,운전온도(℃),Phase,농도(%)\n"
                "A-1,가상 탑,350,N/A,Liquid,97\n"
                "A-2,가상 드럼,120,30,Liquid,97\n"
                "A-3,가상 펌프,200,확인중,liq.,97\n")
        ew.ingest(p, "plant.csv", text.encode(), "facility")
        doc = ew.documents(p)[0]
        self.assertEqual(set(doc["unmapped_columns"]), {"Phase", "농도(%)"})          # 모르는 머리글은 알려 줌
        groups = {(g["kind"], g["field"], g["raw"]) for g in ew.problems(p)}
        self.assertIn(("column", "pressure", "350"), groups)                            # 단위 없는 열: 한 번 묻기
        self.assertIn(("text", "temperature", "N/A"), groups)                          # 처음 보는 글자: 걸린 검사만 말함
        self.assertIn(("text", "temperature", "확인중"), groups)

        ew.learn_unit(p, doc["sha256"], "운전압력", "kPa")
        pressures = {s["entity"]: s["facts"][0]["value"] for s in ew.slots(p) if s["field"] == "pressure"}
        self.assertEqual(pressures, {"facility:A-1": 0.35, "facility:A-2": 0.12, "facility:A-3": 0.2})

        ew.learn_column(p, "Phase", "substance_state")
        ew.reingest(p, doc["sha256"], text.encode())
        phase = {(g["raw"], len(g["facts"])) for g in ew.problems(p) if g["field"] == "substance_state"}
        self.assertEqual(phase, {("Liquid", 2), ("liq.", 1)})                         # 같은 표기는 묶음
        self.assertEqual(ew.learn_value(p, "substance_state", "Liquid", "액체"), 2)
        self.assertEqual(ew.learn_value(p, "substance_state", "liq.", "액체"), 1)
        states = {s["entity"]: s["chosen"]["value"] for s in ew.slots(p) if s["field"] == "substance_state" and s["chosen"]}
        self.assertEqual(states, {"facility:A-1": "액체", "facility:A-2": "액체", "facility:A-3": "액체"})
        # 다시 읽어도 앞서 정한 단위는 유지됩니다
        self.assertEqual(next(s for s in ew.slots(p) if s["key"] == "facility:A-1|pressure")["facts"][0]["value"], 0.35)


if __name__ == "__main__":
    unittest.main()
