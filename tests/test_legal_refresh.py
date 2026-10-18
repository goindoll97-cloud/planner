from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.stage2 import legal_baseline_stamp as stamp
from engine.stage2 import legal_refresh as lr
from engine.stage2 import versioning as ver
from engine.stage2.project import Stage2Project


def _source(key, title, regime, effective, hashes=None, serial="1"):
    return {
        "key": key, "title": title, "regime": regime, "serial": serial,
        "effective_date": effective, "issue_date": effective, "issue_number": "제1호",
        "attachment_hashes": hashes or {}, "attachment_titles": {},
    }


OLD = {
    "CAP_DRAFT": _source("CAP_DRAFT", "화학사고예방관리계획서 작성 등에 관한 규정", "화학사고예방관리계획서",
                         "20250807", {"별지1": "aaa"}),
    "CAP_QTY": _source("CAP_QTY", "유해화학물질의 규정수량에 관한 규정", "화학사고예방관리계획서", "20250807"),
    "CAP_IMPL": _source("CAP_IMPL", "화학사고예방관리계획서 이행 등에 관한 규정", "화학사고예방관리계획서", "20250807"),
    "PSM_NOTICE": _source("PSM_NOTICE", "공정안전보고서 고시", "공정안전보고서", "20250101"),
}


def _new_sources(**changes):
    sources = json.loads(json.dumps(OLD))
    for key, patch_values in changes.items():
        sources[key].update(patch_values)
    return sources


def _project() -> Stage2Project:
    project = Stage2Project(project_id="p1", company_name="한빛화학")
    project.cap_group = "2군"
    project.set_field("cap.business.representative", "대표자", "홍길동", "USER_CONFIRMED")
    project.set_field("cap.internal.facility_response_plan", "시설별 대응계획", "누출 시 차단", "USER_CONFIRMED")
    project.set_field("cap.external.warning_system", "경보체계", "", "HOLD")
    project.set_field("cap.implementation.period", "자체점검 기간", "2026", "USER_CONFIRMED")
    project.set_field("business.address", "주소", "울산", "USER_CONFIRMED")
    return project


FORM1_OLD = [{"물질명": "톨루엔", "CAS No.": "108-88-3", "물질구분": "사고대비물질", "하위규정수량(ton)": "20",
              "상위규정수량(ton)": "200", "규정수량 비교": "하위 이상·상위 미만", "법령DB": "CAP_QTY_APP3", "법령항목": "1"}]
FORM1_NEW = [dict(FORM1_OLD[0], **{"상위규정수량(ton)": "50", "규정수량 비교": "상위 규정수량 이상"})]


class LegalRefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _freeze(self, project, sources=OLD, form1=FORM1_OLD):
        with patch.object(stamp, "approved_law_sources", return_value=sources), \
             patch.object(stamp, "_form1_rows", return_value=form1):
            return ver.freeze_version(project, "CAP", "신규제출", root=self.root)

    def test_freeze_records_law_edition_and_rule_results(self):
        meta = self._freeze(_project())
        snap = ver.load_version_snapshot("p1", meta.version_id, self.root)
        self.assertEqual(snap["legal_baseline"]["laws"]["CAP_QTY"]["effective_date"], "20250807")
        self.assertTrue(snap["legal_baseline"]["laws"]["CAP_DRAFT"]["attachment_fingerprint"])
        self.assertEqual(snap["derived"]["cap_group"], "2군")
        self.assertEqual(snap["derived"]["cap_form1"][0]["규정수량 비교"], "하위 이상·상위 미만")

    def test_no_amendment_means_nothing_to_refresh(self):
        meta = self._freeze(_project())
        plan = lr.build_refresh_plan(_project(), meta.version_id, root=self.root, approved_sources=OLD)
        self.assertTrue(plan.stamped)
        self.assertFalse(plan.has_changes)
        self.assertEqual(plan.affected_fields, [])

    def test_form_rule_amendment_flags_only_confirmed_cap_fields(self):
        meta = self._freeze(_project())
        new = _new_sources(CAP_DRAFT={"effective_date": "20261201", "attachment_hashes": {"별지1": "bbb"}})
        with patch.object(stamp, "_form1_rows", return_value=FORM1_OLD):
            plan = lr.build_refresh_plan(_project(), meta.version_id, root=self.root, approved_sources=new)
        self.assertEqual([c.key for c in plan.law_changes], ["CAP_DRAFT"])
        details = " ".join(plan.law_changes[0].details)
        self.assertIn("2025.08.07 → 2026.12.01", details)
        self.assertIn("첨부원본", details)
        keys = [f.key for f in plan.affected_fields]
        # 작성규정 범위의 확인 완료 칸만; 이미 HOLD인 칸·이행규정 칸·공유 사업장 칸은 제외
        self.assertEqual(keys, ["cap.business.representative", "cap.internal.facility_response_plan"])
        self.assertEqual(plan.recomputed, [])

    def test_psm_amendment_does_not_touch_cap_version(self):
        meta = self._freeze(_project())
        new = _new_sources(PSM_NOTICE={"effective_date": "20261201"})
        plan = lr.build_refresh_plan(_project(), meta.version_id, root=self.root, approved_sources=new)
        self.assertFalse(plan.has_changes)

    def test_quantity_amendment_recomputes_form1_and_asks_for_group_review(self):
        meta = self._freeze(_project())
        new = _new_sources(CAP_QTY={"effective_date": "20261201", "serial": "2"})
        with patch.object(stamp, "_form1_rows", return_value=FORM1_NEW):
            plan = lr.build_refresh_plan(_project(), meta.version_id, root=self.root, approved_sources=new)
        self.assertEqual(len(plan.recomputed), 1)
        row = plan.recomputed[0]
        self.assertEqual((row.change, row.before["상위규정수량(ton)"], row.after["상위규정수량(ton)"]),
                         ("CHANGED", "200", "50"))
        self.assertTrue(plan.group_review)
        self.assertEqual(plan.affected_fields, [])  # 규정수량 개정은 회사 입력칸을 건드리지 않는다

    def test_apply_copies_version_and_puts_affected_fields_on_hold_without_erasing(self):
        project = _project()
        meta = self._freeze(project)
        project.set_field("cap.business.representative", "대표자", "작업 중 바꾼 값", "USER_CONFIRMED")
        new = _new_sources(CAP_DRAFT={"effective_date": "20261201"})
        with patch.object(stamp, "_form1_rows", return_value=FORM1_OLD):
            plan = lr.build_refresh_plan(project, meta.version_id, root=self.root, approved_sources=new)
        changed = lr.apply_refresh(project, plan, root=self.root, now="2026-12-02")
        self.assertEqual(changed, 2)
        rec = project.fields["cap.business.representative"]
        self.assertEqual(rec.value, "홍길동")  # 기준 버전 값으로 복제
        self.assertEqual(rec.status, "HOLD")
        self.assertTrue(rec.note.startswith(lr.REVIEW_NOTE_PREFIX))
        self.assertIn("이전 상태 USER_CONFIRMED", rec.note)
        self.assertEqual(project.fields["cap.implementation.period"].status, "USER_CONFIRMED")
        self.assertIn("작성본 최신화", project.notes[-1])
        candidate = lr.change_log_candidate(plan, today="2026-12-02")
        self.assertEqual(candidate["변경의 종류"], "㈓ 정보 현행화")

    def test_old_version_without_record_uses_effective_date_after_save(self):
        project = _project()
        meta = self._freeze(project)
        path = ver._snapshot_path("p1", meta.version_id, self.root)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("legal_baseline"), raw.pop("derived")
        raw["meta"]["created_at"] = "2026-03-01T00:00:00+00:00"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        new = _new_sources(CAP_IMPL={"effective_date": "20260601"})
        plan = lr.build_refresh_plan(project, meta.version_id, root=self.root, approved_sources=new)
        self.assertFalse(plan.stamped)
        self.assertEqual([c.key for c in plan.law_changes], ["CAP_IMPL"])  # 2025년 시행 법령은 제외
        self.assertTrue(plan.law_changes[0].inferred)
        self.assertEqual([f.key for f in plan.affected_fields], ["cap.implementation.period"])
        self.assertTrue(any("법령판 기록" in n for n in plan.notices))

    def test_missing_approved_baseline_holds(self):
        meta = self._freeze(_project())
        plan = lr.build_refresh_plan(_project(), meta.version_id, root=self.root, approved_sources={})
        self.assertFalse(plan.baseline_ready)
        self.assertFalse(plan.has_changes)

    def test_impact_map_covers_every_monitored_law(self):
        registry = json.loads((lr.PROJECT_ROOT / "data" / "law_registry.json").read_text(encoding="utf-8"))
        rows = registry if isinstance(registry, list) else registry.get("sources", registry)
        keys = {row["key"] for row in rows}
        self.assertEqual(keys, set(lr.load_impact_map()))


if __name__ == "__main__":
    unittest.main()
