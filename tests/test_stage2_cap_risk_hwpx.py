from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from hwpx import HwpxDocument

from engine.stage2 import cap_hwpx
from engine.stage2.cap_multi_form_runtime import (
    CAPOfficialForm,
    CAPOfficialFormBundle,
    _build_bundle_zip,
    preflight_cap_risk_hwpx,
)
from engine.stage2.cap_risk_engine import (
    CAPForm14Data,
    CAPForm15Data,
    build_cap_form14_data,
    build_cap_form15_data,
)
from engine.stage2.cap_risk_hwpx import (
    render_form14_single_scenario,
    render_form15_risk,
)
from engine.stage2.project import Stage2Project


M14 = "[별지 제14호서식]"
M15 = "[별지 제15호서식]"


def _save_doc(doc: HwpxDocument, name: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        doc.save_to_path(path)
        return path.read_bytes()


def _all_text(data: bytes) -> str:
    with ZipFile(BytesIO(data), "r") as zf:
        values = []
        for name in zf.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            raw = zf.read(name).decode("utf-8", errors="ignore")
            values.extend(
                re.findall(
                    r"<(?:[A-Za-z_][\w.-]*:)?t(?:\s[^>]*)?>(.*?)</(?:[A-Za-z_][\w.-]*:)?t>",
                    raw,
                    flags=re.S,
                )
            )
        return " ".join(re.sub(r"<[^>]+>", "", value) for value in values)


def _form14_hwpx() -> bytes:
    doc = HwpxDocument.new()
    doc.add_paragraph(M14)
    doc.add_paragraph("사고시나리오별 시설빈도")
    doc.add_paragraph("1) 사고시나리오")

    table = doc.add_table(rows=12, cols=5)
    for col, text in enumerate(("연번", "개시사건", "빈도", "개수", "사고빈도")):
        table.set_cell_text(0, col, text)
    for row in range(1, 11):
        table.set_cell_text(row, 0, str(row))
    table.set_cell_text(11, 0, "합")

    doc.add_paragraph("안전성확보설비")
    safety = doc.add_table(rows=4, cols=1)
    safety.set_cell_text(0, 0, "수동적 완화장치 종류")
    safety.set_cell_text(1, 0, "")
    safety.set_cell_text(2, 0, "능동적 완화장치의 종류")
    safety.set_cell_text(3, 0, "")

    doc.add_paragraph("보호대상 명세")
    protected = doc.add_table(rows=2, cols=1)
    protected.set_cell_text(0, 0, "보호대상 포함 여부")
    protected.set_cell_text(1, 0, "")
    return _save_doc(doc, "form14.hwpx")


def _form15_hwpx() -> bytes:
    doc = HwpxDocument.new()
    doc.add_paragraph(M15)
    doc.add_paragraph("위험도 분석")

    scenario = doc.add_table(rows=2, cols=5)
    for col, text in enumerate(
        ("연번", "사고시나리오 명", "사고시나리오 시설빈도", "사고시나리오 거리(장외)", "주민수")
    ):
        scenario.set_cell_text(0, col, text)

    doc.add_paragraph("위험도 판단 요소 점수")
    totals = doc.add_table(rows=3, cols=4)
    for col, text in enumerate(
        (
            "사고시나리오 총 개수 (A)",
            "사고시나리오 시설 빈도의 합 (B)",
            "사고시나리오 거리의 합(C)",
            "주민수 합 (D)",
        )
    ):
        totals.set_cell_text(0, col, text)

    doc.add_paragraph("사고빈도 및 사고영향 점수")
    scores = doc.add_table(rows=2, cols=2)
    scores.set_cell_text(0, 0, "사고빈도점수(A+B)")
    scores.set_cell_text(0, 1, "")
    scores.set_cell_text(1, 0, "사고영향점수(C+D)")
    scores.set_cell_text(1, 1, "")
    return _save_doc(doc, "form15.hwpx")


def _single_form14_data() -> CAPForm14Data:
    scenario = "염소 독성누출-1"
    events = []
    names = (
        "고압용기파열", "배관파열", "배관누출", "상압 탱크 파열 및 누출",
        "플랜지 등의 가스켓 파손", "펌프/컴프레서 누출",
        "안전밸브 오작동 및 조기개방", "냉각수 손실",
        "입/출하 시설 누출 사고", "외부화재",
    )
    for index, name in enumerate(names):
        events.append(
            {
                "사고시나리오명": scenario,
                "개시사건": name,
                "기준빈도(/연)": f"{10 ** -(index % 4 + 1):g}",
                "개수": index,
                "사고빈도(/연)": f"{index * 0.001:g}",
            }
        )
    return CAPForm14Data(
        scenario_rows=(
            {
                "사고시나리오명": scenario,
                "시설빈도(/연)": "0.123",
                "수동적 완화장치": "방류벽",
                "능동적 완화장치": "가스감지기와 자동차단밸브의 연동",
                "안전성확보설비 증빙": "GA-201/PID-201",
                "개수 산정근거": "PID-201",
            },
        ),
        event_rows=tuple(events),
        blockers=(),
        messages=(),
    )


def _single_form15_data() -> CAPForm15Data:
    return CAPForm15Data(
        scenario_rows=(
            {
                "연번": 1,
                "사고시나리오 명": "염소 독성누출-1",
                "사고시나리오 시설빈도": "0.123",
                "사고시나리오 거리(장외)": "180",
                "거주민수": 25,
                "근로자수": 10,
                "위험도 주민수": 35,
                "갑종 보호대상 수": 1,
                "을종 보호대상 수": 0,
                "환경수용체 수": 1,
                "KORA/GIS 근거": "KORA-01",
            },
        ),
        totals={
            "사고시나리오 총 개수(A)": 1,
            "사고시나리오 시설빈도의 합(B)": 0.123,
            "사고시나리오 거리의 합(C)": 180.0,
            "주민수 합(D)": 35,
        },
        scores={
            "사고시나리오 개수 구간점수": 0,
            "시설빈도 구간점수": 1,
            "거리 구간점수": 2,
            "주민수 구간점수": 1,
            "사고빈도점수(A+B)": 1,
            "사고영향점수(C+D)": 3,
            "위험도 판정표 점수(증감 전)": 4,
            "증감 전 위험도": "다",
            "최종 위험도": "안전원 최종결정 전",
        },
        blockers=(),
        messages=(),
        no_offsite_scenario=False,
    )


def _project_two_scenarios() -> Stage2Project:
    project = Stage2Project(
        project_id="S2-RISK-HWPX",
        company_name="위험도테스트화학",
        cap_required=True,
        cap_group="1군",
        scope_confirmed=True,
        cap_selected=True,
    )
    project.set_field("cap.business.industrial_complex", "산업단지", "해당 없음", "USER_CONFIRMED")

    def freq(name: str, basis: str):
        return {
            "사고시나리오명": name,
            "고압용기파열": 1,
            "배관파열": 1,
            "배관누출": 2,
            "상압 탱크 파열 및 누출": 0,
            "플랜지 등의 가스켓 파손": 1,
            "펌프/컴프레서 누출": 1,
            "안전밸브 오작동 및 조기개방": 0,
            "냉각수 손실": 0,
            "입/출하 시설 누출 사고": 0,
            "외부화재": 0,
            "개수 산정근거": basis,
            "수동적 완화장치": "방류벽",
            "능동적 완화장치": "가스감지기와 자동차단밸브의 연동",
            "안전성확보설비 증빙": basis,
        }

    project.set_field(
        "cap.offsite.scenario_frequency",
        "사고시나리오 시설빈도",
        [freq("염소 독성누출-1", "PID-201"), freq("암모니아 독성누출-2", "PID-401")],
        "USER_CONFIRMED",
    )
    project.set_field(
        "cap.offsite.scenario_impact_table",
        "사고시나리오 영향평가",
        [
            {
                "사고시나리오명": "염소 독성누출-1",
                "장외거리(m)": 180,
                "거주민수": 25,
                "근로자수": 10,
                "갑종 보호대상 수": 1,
                "을종 보호대상 수": 0,
                "환경수용체 수": 1,
                "KORA/GIS 근거": "KORA-01",
            },
            {
                "사고시나리오명": "암모니아 독성누출-2",
                "장외거리(m)": 320,
                "거주민수": 45,
                "근로자수": 15,
                "갑종 보호대상 수": 0,
                "을종 보호대상 수": 1,
                "환경수용체 수": 0,
                "KORA/GIS 근거": "KORA-02",
            },
        ],
        "USER_CONFIRMED",
    )
    return project


class CAPRiskHwpxRendererTests(unittest.TestCase):
    def test_global_structured_table_resolver_really_targets_below_not_right(self):
        doc = HwpxDocument.new()
        doc.add_paragraph("테스트 표")
        table = doc.add_table(rows=2, cols=2)
        table.set_cell_text(0, 0, "A")
        table.set_cell_text(0, 1, "B")
        data = _save_doc(doc, "below.hwpx")

        target = cap_hwpx._resolve_down(data, "테스트 표", "A")

        self.assertEqual(target.logical_row, 1)
        self.assertEqual(target.logical_col, 0)

    def test_form14_fills_ten_events_total_safety_and_protected_target(self):
        result = render_form14_single_scenario(
            _form14_hwpx(),
            _single_form14_data(),
            _single_form15_data(),
        )
        text = _all_text(result.data)

        self.assertEqual(result.warnings, ())
        self.assertGreaterEqual(result.applied_count, 45)
        self.assertIn("염소 독성누출-1", text)
        self.assertIn("고압용기파열", text)
        self.assertIn("외부화재", text)
        self.assertIn("0.123", text)
        self.assertIn("☒ 방류벽", text)
        self.assertIn("☒ 공공수용체", text)

    def test_form15_clones_scenario_row_and_fills_totals_and_scores(self):
        base = _single_form15_data()
        second = dict(base.scenario_rows[0])
        second.update(
            {
                "연번": 2,
                "사고시나리오 명": "암모니아 독성누출-2",
                "사고시나리오 시설빈도": "0.456",
                "사고시나리오 거리(장외)": "320",
                "위험도 주민수": 60,
            }
        )
        data = CAPForm15Data(
            scenario_rows=(base.scenario_rows[0], second),
            totals={
                "사고시나리오 총 개수(A)": 2,
                "사고시나리오 시설빈도의 합(B)": 0.579,
                "사고시나리오 거리의 합(C)": 500.0,
                "주민수 합(D)": 95,
            },
            scores={
                "사고시나리오 개수 구간점수": 0,
                "시설빈도 구간점수": 1,
                "거리 구간점수": 2,
                "주민수 구간점수": 1,
                "사고빈도점수(A+B)": 1,
                "사고영향점수(C+D)": 3,
            },
            blockers=(),
            messages=(),
            no_offsite_scenario=False,
        )

        result = render_form15_risk(_form15_hwpx(), data)
        text = _all_text(result.data)

        self.assertEqual(result.warnings, ())
        self.assertIn("염소 독성누출-1", text)
        self.assertIn("암모니아 독성누출-2", text)
        self.assertIn("0.579", text)
        self.assertIn("500.0", text)
        self.assertIn("95", text)

    @patch("engine.stage2.cap_risk_engine.approved_source_is_current", return_value=True)
    def test_bundle_writes_one_form14_copy_per_scenario_and_one_form15(self, _current):
        project = _project_two_scenarios()
        form14_bytes = _form14_hwpx()
        form15_bytes = _form15_hwpx()
        form14 = CAPOfficialForm(
            path=Path("별지14.hwpx"),
            hwpx_data=form14_bytes,
            markers=(M14,),
            source_sha256=sha256(form14_bytes).hexdigest(),
            source_format="HWPX",
        )
        form15 = CAPOfficialForm(
            path=Path("별지15.hwpx"),
            hwpx_data=form15_bytes,
            markers=(M15,),
            source_sha256=sha256(form15_bytes).hexdigest(),
            source_format="HWPX",
        )
        bundle = CAPOfficialFormBundle(
            status="READY",
            forms=(form14, form15),
            required_markers=(M14, M15),
            found_markers=(M14, M15),
            missing_markers=(),
            issues=(),
        )

        result = _build_bundle_zip(project, bundle, cap_hwpx.build_cap_hwpx_draft)

        self.assertEqual(result.warnings, ())
        with ZipFile(BytesIO(result.data), "r") as zf:
            hwpx_names = [name for name in zf.namelist() if name.endswith(".hwpx")]
            self.assertEqual(len(hwpx_names), 3)
            self.assertEqual(len([name for name in hwpx_names if "별지14" in name]), 2)
            self.assertEqual(len([name for name in hwpx_names if "별지15" in name]), 1)
            combined_text = " ".join(_all_text(zf.read(name)) for name in hwpx_names)
            self.assertIn("염소 독성누출-1", combined_text)
            self.assertIn("암모니아 독성누출-2", combined_text)
            guide = zf.read("원본서식_자동작성_안내.txt").decode("utf-8")
            self.assertIn("사고시나리오별 공식 원본 1부씩", guide)

    @patch("engine.stage2.cap_multi_form_runtime.resolve_current_cap_form_bundle")
    @patch("engine.stage2.cap_risk_engine.approved_source_is_current", return_value=True)
    def test_preflight_releases_renderer_hold_only_when_current_templates_render(
        self, _current, bundle_mock
    ):
        project = _project_two_scenarios()
        form14_bytes = _form14_hwpx()
        form15_bytes = _form15_hwpx()
        bundle_mock.return_value = CAPOfficialFormBundle(
            status="READY",
            forms=(
                CAPOfficialForm(
                    Path("별지14.hwpx"), form14_bytes, (M14,),
                    sha256(form14_bytes).hexdigest(), "HWPX"
                ),
                CAPOfficialForm(
                    Path("별지15.hwpx"), form15_bytes, (M15,),
                    sha256(form15_bytes).hexdigest(), "HWPX"
                ),
            ),
            required_markers=(M14, M15),
            found_markers=(M14, M15),
            missing_markers=(),
            issues=(),
        )

        result = preflight_cap_risk_hwpx(project)

        self.assertTrue(result.ready)
        self.assertEqual(result.blockers, ())
        self.assertTrue(any("별지 제14호" in message for message in result.messages))
        self.assertTrue(any("별지 제15호" in message for message in result.messages))


if __name__ == "__main__":
    unittest.main()
