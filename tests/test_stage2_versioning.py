from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from engine.stage2.project import Stage2Project
from engine.stage2.versioning import (
    UnfrozenChangesError,
    diff_versions,
    freeze_version,
    has_unfrozen_changes,
    list_versions,
    load_version_fields,
    start_from_version,
)


def _project() -> Stage2Project:
    project = Stage2Project(project_id="p1", company_name="한빛화학")
    project.set_field("facility.reactor.volume", "반응기 용량", 5, "USER_CONFIRMED")
    project.set_field("business.address", "주소", "울산", "USER_CONFIRMED")
    return project


class VersioningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_version_numbers_follow_submission_kind(self):
        project = _project()
        ids = [
            freeze_version(project, "CAP", kind, root=self.root).version_id
            for kind in ("신규", "변경", "변경", "재제출")
        ]
        self.assertEqual(ids, ["CAP-v1.0", "CAP-v1.1", "CAP-v1.2", "CAP-v2.0"])
        # 문서별로 번호가 따로 매겨진다.
        self.assertEqual(freeze_version(project, "PSM", "신규", root=self.root).version_id, "PSM-v1.0")
        metas = list_versions("p1", "CAP", self.root)
        self.assertEqual(metas[1].parent_id, "CAP-v1.0")

    def test_cap_statutory_submission_kinds_drive_version_numbers(self):
        project = _project()
        ids = [
            freeze_version(project, "CAP", kind, root=self.root).version_id
            for kind in ("신규제출", "변경제출", "변경제출", "5년 재제출")
        ]
        self.assertEqual(ids, ["CAP-v1.0", "CAP-v1.1", "CAP-v1.2", "CAP-v2.0"])

    def test_diff_reports_added_removed_and_changed_but_ignores_timestamps(self):
        project = _project()
        freeze_version(project, "CAP", "신규", root=self.root)
        project.set_field("facility.reactor.volume", "반응기 용량", 8, "USER_CONFIRMED")
        project.set_field("business.address", "주소", "울산", "USER_CONFIRMED")  # 값 동일, 시각만 갱신
        project.set_field("facility.tank.count", "탱크 수", 2, "USER_CONFIRMED")
        del project.fields["business.address"]
        changes = {c.key: c for c in diff_versions(project, "CAP-v1.0", None, self.root)}
        self.assertEqual(changes["facility.reactor.volume"].change, "CHANGED")
        self.assertEqual((changes["facility.reactor.volume"].old, changes["facility.reactor.volume"].new), (5, 8))
        self.assertEqual(changes["facility.tank.count"].change, "ADDED")
        self.assertEqual(changes["business.address"].change, "REMOVED")

        project = _project()
        freeze_version(project, "CAP", "신규", root=self.root)
        project.set_field("business.address", "주소", "울산", "USER_CONFIRMED")
        self.assertEqual(diff_versions(project, "CAP-v1.0", None, self.root), [])

    def test_snapshot_is_immutable_after_working_copy_changes(self):
        project = _project()
        freeze_version(project, "CAP", "신규", root=self.root)
        project.set_field("facility.reactor.volume", "반응기 용량", 99, "USER_CONFIRMED")
        self.assertEqual(load_version_fields("p1", "CAP-v1.0", self.root)["facility.reactor.volume"].value, 5)

    def test_start_from_version_restores_fields_and_protects_unsaved_work(self):
        project = _project()
        freeze_version(project, "CAP", "신규", root=self.root)
        self.assertFalse(has_unfrozen_changes(project, "CAP", self.root))
        project.set_field("facility.reactor.volume", "반응기 용량", 8, "USER_CONFIRMED")
        self.assertTrue(has_unfrozen_changes(project, "CAP", self.root))
        with self.assertRaises(UnfrozenChangesError):
            start_from_version(project, "CAP-v1.0", doc="CAP", root=self.root)
        self.assertEqual(project.fields["facility.reactor.volume"].value, 8)  # 거부 시 작업본 유지
        start_from_version(project, "CAP-v1.0", doc="CAP", force=True, root=self.root)
        self.assertEqual(project.fields["facility.reactor.volume"].value, 5)

    def test_unsupported_doc_type_is_rejected(self):
        with self.assertRaises(ValueError):
            freeze_version(_project(), "XYZ", "신규", root=self.root)


if __name__ == "__main__":
    unittest.main()
