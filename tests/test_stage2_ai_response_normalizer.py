from __future__ import annotations

from dataclasses import dataclass
import unittest

from engine.stage2.ai_response_normalizer import normalize_draft_response


@dataclass(frozen=True)
class Spec:
    key: str


class Stage2AIResponseNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.specs = [Spec("cap.prevention.safety"), Spec("cap.internal.emergency")]

    def test_accepts_requested_drafts_array(self):
        profile, rows = normalize_draft_response(
            {
                "profile_summary": "확인된 사업장 특성",
                "drafts": [
                    {"requirement_key": "cap.prevention.safety", "draft_text": "문장 1"},
                    {"requirement_key": "cap.internal.emergency", "draft_text": "문장 2"},
                ],
            },
            self.specs,
        )
        self.assertEqual(profile, "확인된 사업장 특성")
        self.assertEqual([row["requirement_key"] for row in rows], [spec.key for spec in self.specs])

    def test_accepts_items_or_sentences_instead_of_drafts(self):
        _, rows = normalize_draft_response(
            {
                "items": [
                    {"key": "cap.prevention.safety", "text": "문장 1"},
                    {"key": "cap.internal.emergency", "content": "문장 2"},
                ]
            },
            self.specs,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["draft_text"], "문장 1")
        self.assertEqual(rows[1]["draft_text"], "문장 2")

    def test_accepts_requirement_keyed_object(self):
        _, rows = normalize_draft_response(
            {
                "drafts": {
                    "cap.prevention.safety": {"text": "문장 1"},
                    "cap.internal.emergency": {"text": "문장 2"},
                }
            },
            self.specs,
        )
        self.assertEqual({row["requirement_key"] for row in rows}, {spec.key for spec in self.specs})

    def test_accepts_direct_single_item_object(self):
        _, rows = normalize_draft_response(
            {"draft_text": "단일 항목 문장", "suggestions": "추가 확인"},
            [Spec("cap.prevention.safety")],
        )
        self.assertEqual(rows[0]["requirement_key"], "cap.prevention.safety")
        self.assertEqual(rows[0]["suggested_additions"], ["추가 확인"])

    def test_does_not_accept_unknown_requirement_key(self):
        with self.assertRaisesRegex(ValueError, "요청한 작성항목"):
            normalize_draft_response(
                {"items": [{"key": "invented.key", "text": "임의 문장"}]},
                self.specs,
            )


if __name__ == "__main__":
    unittest.main()
