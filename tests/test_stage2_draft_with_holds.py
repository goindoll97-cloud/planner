from __future__ import annotations

import unittest

from engine.stage2.project import Stage2Project
from engine.stage2.workflow import (
    ATTACHMENT_MODE_PROGRAM,
    draft_authoring_allowed,
    draft_with_holds_acknowledged,
    mark_draft_with_holds_acknowledged,
    mark_intake_confirmed,
    mark_validation_confirmed,
    reset_after_intake_change,
    set_attachment_mode,
    validation_confirmed,
)


class DraftWithHoldsWorkflowTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        return Stage2Project(project_id="S2-DRAFT-HOLD", company_name="가상회사")

    def test_explicit_ack_allows_draft_without_marking_validation_complete(self):
        project = self._project()

        self.assertFalse(validation_confirmed(project))
        self.assertFalse(draft_authoring_allowed(project))

        mark_draft_with_holds_acknowledged(project, True)

        self.assertTrue(draft_with_holds_acknowledged(project))
        self.assertTrue(draft_authoring_allowed(project))
        self.assertFalse(validation_confirmed(project))

    def test_clean_validation_clears_draft_only_override(self):
        project = self._project()
        mark_draft_with_holds_acknowledged(project, True)

        mark_validation_confirmed(project, True)

        self.assertTrue(validation_confirmed(project))
        self.assertFalse(draft_with_holds_acknowledged(project))
        self.assertTrue(draft_authoring_allowed(project))

    def test_intake_invalidation_clears_draft_only_override(self):
        project = self._project()
        mark_draft_with_holds_acknowledged(project, True)

        mark_intake_confirmed(project, False)

        self.assertFalse(draft_with_holds_acknowledged(project))
        self.assertFalse(draft_authoring_allowed(project))

    def test_reset_after_intake_change_clears_draft_only_override(self):
        project = self._project()
        mark_draft_with_holds_acknowledged(project, True)

        reset_after_intake_change(project)

        self.assertFalse(draft_with_holds_acknowledged(project))
        self.assertFalse(draft_authoring_allowed(project))

    def test_attachment_mode_change_clears_draft_only_override(self):
        project = self._project()
        mark_draft_with_holds_acknowledged(project, True)

        set_attachment_mode(project, ATTACHMENT_MODE_PROGRAM)

        self.assertFalse(draft_with_holds_acknowledged(project))
        self.assertFalse(draft_authoring_allowed(project))


if __name__ == "__main__":
    unittest.main()
