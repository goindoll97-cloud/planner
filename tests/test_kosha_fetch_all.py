from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import unittest

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_chemical_upload as up
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import kosha_candidates as kc
from tests.test_upload_products_and_mixtures import MIX1, MIX2, SINGLE, _pending, _products

ROOT = Path(__file__).resolve().parents[1]
ACETONE = ["아세톤", "단일물질", "67-64-1", None, 10, 20, "kg", "액체", None]


def _project():
    project = _pending()
    up.add_to_project(project, _products([SINGLE, ACETONE, MIX1, MIX2]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
    return project


def _found(cas_list):
    out = {}
    for cas in cas_list:
        if cas == "67-64-1":
            out[cas] = kc.Candidate(cas, "NO_APP1_MATCH", text="인화성 액체 : 구분2", chemical_name="아세톤")
        elif cas == "108-88-3":
            out[cas] = kc.Candidate(cas, "API_ERROR", message="TimeoutError")
        else:
            out[cas] = kc.Candidate(cas, "NO_MATCH", message="자료 없음")
    return out


class FetchAllTests(unittest.TestCase):
    def _run(self, project, seen):
        rows = [{"project_id": project.project_id, "company_name": project.company_name}]

        def fake_fetch(cas_list, *args, **kwargs):
            seen.append(list(cas_list))
            return _found(cas_list)

        patches = [patch("engine.stage2.storage.list_projects", return_value=rows),
                   patch("engine.stage2.storage.load_project", return_value=project),
                   patch("engine.stage2.storage.save_project"),
                   patch("streamlit.page_link"),
                   patch("ui.cap_start_panel._gate_hold", return_value=False),
                   patch("engine.stage2.kosha_candidates.fetch", side_effect=fake_fetch)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        at = AppTest.from_file(str(ROOT / "ui/judgement_page.py"), default_timeout=90)
        at.session_state["_stage2_active_project_id"] = project.project_id
        return at.run()

    def test_one_click_looks_up_every_single_substance_and_skips_mixtures(self):
        project = _project()
        singles = chem.single_substance_cas(project)
        self.assertIn("67-64-1", singles)
        self.assertEqual(len(singles), len(set(singles)))
        seen: list = []
        at = self._run(project, seen)
        self.assertFalse(at.exception)
        button = at.button(key=f"judge_kosha_all_{project.project_id}")
        self.assertEqual(button.label, "KOSHA에서 전체 물질 SDS 분류 조회")
        button.click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(seen), 1)
        self.assertEqual(sorted(seen[0]), sorted(singles))            # 단일물질 전체를 한 번에
        self.assertNotIn("", seen[0])                                  # 혼합제품(CAS 없음)은 보내지 않는다
        stored = at.session_state[f"judge_kosha_{project.project_id}"]
        self.assertTrue(stored["67-64-1"].usable)

    def test_the_result_summary_and_the_retry_button_only_cover_what_failed(self):
        project = _project()
        seen: list = []
        at = self._run(project, seen)
        at.button(key=f"judge_kosha_all_{project.project_id}").click().run()
        captions = " ".join(c.value for c in at.caption)
        self.assertIn("분류 후보 1건", captions)
        self.assertIn("108-88-3(TimeoutError)", captions)
        button = at.button(key=f"judge_kosha_all_{project.project_id}")
        self.assertEqual(button.label, "조회하지 못한 물질만 다시 조회")
        button.click().run()
        self.assertEqual(seen[1], ["108-88-3"])   # 네트워크 오류로 실패한 것만 다시. 자료가 없는 물질은 다시 묻지 않는다
        self.assertEqual(at.button(key=f"judge_kosha_all_{project.project_id}").label, "조회하지 못한 물질만 다시 조회")  # 또 실패했으니 계속 재시도 가능

    def test_mixture_products_are_mentioned_but_not_sent(self):
        project = _project()
        at = self._run(project, [])
        self.assertTrue(any("혼합제품 1건은 CAS가 없어 조회하지 않습니다" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
