import unittest

from engine.diagnosis import PreliminaryDiagnosis, followup_questions


class DiagnosisFollowupGateTest(unittest.TestCase):
    def test_missing_excel_inputs_are_not_rendered_as_regulatory_questions(self):
        diagnosis = PreliminaryDiagnosis(
            law_status="",
            cap_result="입력파일 보완 필요",
            psm_result="입력파일 보완 필요",
            missing_items=[
                "사업장 기본정보: '사업장명' 입력 필요",
                "화학물질 목록: 입력된 물질이 없습니다.",
            ],
            messages=[],
            dynamic_questions=["해당 설비가 군사시설에 해당합니까?"],
        )
        self.assertEqual(followup_questions(diagnosis), [])

    def test_regulatory_questions_are_returned_after_input_gate_passes(self):
        diagnosis = PreliminaryDiagnosis(
            law_status="",
            cap_result="",
            psm_result="PSM 대상 후보",
            missing_items=[],
            messages=[],
            dynamic_questions=[
                "해당 설비가 군사시설에 해당합니까?",
                "해당 설비가 군사시설에 해당합니까?",
            ],
        )
        self.assertEqual(
            followup_questions(diagnosis),
            ["해당 설비가 군사시설에 해당합니까?"],
        )


if __name__ == "__main__":
    unittest.main()
