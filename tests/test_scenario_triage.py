import time
import unittest

from engine.stage2 import evidence_workspace as ew, evidence_llm, scenario_triage
from engine.stage2.project import Stage2Project


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.p = Stage2Project('triage-test', '가상 사업장')

    def upload(self, name, content, kind='facility', hint=''):
        return ew.ingest(self.p, name, content.encode(), kind, hint)

    def confirm(self):
        for slot in ew.slots(self.p):
            if not slot['chosen']:
                ew.approve(self.p, slot['key'], slot['facts'][0]['id'])

    def row(self, result, facility, material=None):
        return next(r for r in result['rows'] if r['facility'] == facility and (material is None or r['material'] == material))

    def test_cartesian_pairs_and_incompatible_relation_held(self):
        self.upload('m.csv', '제품코드,제품명,CAS 번호\nA,제품 A,64-17-5\nB,제품 B,67-56-1\n', 'material')
        self.upload('f.csv', '설비번호,설비명,취급제품,최대보유량(kg),운전압력(MPa)\nT1,탱크1,제품 A,100,0.1\nT2,탱크2,제품 B,200,0.1\n')
        self.confirm()
        result = scenario_triage.evaluate(self.p)
        self.assertEqual(len(result['rows']), 4)
        self.assertEqual(sum(r['linked'] for r in result['rows']), 2)
        self.assertTrue(all(r['state'] == '보류' for r in result['rows'] if not r['linked']))
        self.assertTrue(all(r['sources']['inventory']['sha256'] for r in result['rows'] if r['linked']))
        # 연결된 조합이 먼저, 연결되지 않은 조합은 가정 점수가 커도 뒤에 둡니다.
        self.assertEqual([r['linked'] for r in result['rows']], [True, True, False, False])

    def test_missing_assumption_can_change_rank_and_is_not_published(self):
        self.upload('m.csv', '제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n', 'material')
        self.upload('f.csv', '설비번호,취급제품,최대보유량(kg),운전압력(MPa)\nT1,제품,,0\nT2,제품,8000,0\n')
        self.confirm()
        result = scenario_triage.evaluate(self.p)
        first = self.row(result, 'facility:T1')
        self.assertEqual(first['assumptions']['inventory']['value'], 12000)
        self.assertEqual(first['value_states']['inventory'], 'assumed')
        self.assertEqual(first['rank'], 1)
        self.assertIn('inventory', first['rank_sensitive'])
        self.assertEqual(first['state'], '보류')
        self.assertNotIn('최대보유량(kg)', ew.publishing_plan(self.p)['inventory.facilities'][0])

    def test_unconfirmed_candidates_rank_as_provisional_before_any_approval(self):
        self.upload('m.csv', '제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n', 'material')
        self.upload('f.csv', '설비명,취급제품,최대보유량(kg),운전압력(MPa),운전온도(C)\n이름 탱크,제품,9000,0.5,20\n')  # 식별번호 없음 → 자동 기입 안 됨
        self.assertFalse(any(s['chosen'] for s in ew.slots(self.p) if s['entity'].startswith('facility:') and s['field'] == 'inventory'))
        row = self.row(scenario_triage.evaluate(self.p), 'facility:이름 탱크')
        self.assertTrue(row['linked'])
        self.assertEqual(row['rank'], 1)
        self.assertEqual(row['value_states']['inventory'], 'provisional')
        self.assertEqual(row['assumptions'], {})
        self.assertEqual(row['state'], '잠정')

    def test_conflicting_values_use_the_larger_value_and_hold_the_row(self):
        self.upload('m.csv', '제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n', 'material')
        self.upload('a.csv', '설비번호,취급제품,최대보유량(kg),운전압력(MPa)\nT1,제품,1000,0.1\n')
        self.upload('b.csv', '설비번호,최대보유량(kg)\nT1,4000\n')
        row = self.row(scenario_triage.evaluate(self.p), 'facility:T1')
        self.assertEqual(row['values']['inventory'], 4000)
        self.assertEqual(row['conflicts'], {'inventory': ['1000.0', '4000.0']})
        self.assertEqual(row['assumptions']['inventory']['basis'], '충돌한 값 중 큰 값(보수적)')
        self.assertEqual(row['state'], '보류')

    def test_rank_critical_values_are_found_and_exported_as_slot_keys(self):
        self.upload('m.csv', '제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n', 'material')
        self.upload('f.csv', '설비번호,취급제품,최대보유량(kg),운전압력(MPa),운전온도(C)\nT1,제품,9000,0.5,20\nT2,제품,8000,0.5,20\nT3,제품,100,0.5,20\n')
        result = scenario_triage.evaluate(self.p)
        critical = {(c['facility'], c['field']) for c in result['critical_values']}
        self.assertIn(('facility:T1', 'inventory'), critical)      # 0.5배면 T2에게 1위를 내줌
        self.assertIn(('facility:T2', 'inventory'), critical)      # 2배면 T1을 앞지름
        self.assertNotIn(('facility:T3', 'inventory'), critical)   # 0.5배·2배여도 3위 그대로
        keys = scenario_triage.critical_slot_keys(self.p)
        self.assertIn('facility:T1|inventory', keys)
        self.assertNotIn('facility:T3|inventory', keys)
        self.assertEqual({k for k in keys if k.endswith('|concentration')}, {'material:P|concentration'})

    def test_single_candidate_has_no_rank_sensitivity(self):
        self.upload('m.csv', '제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n', 'material')
        self.upload('f.csv', '설비번호,취급제품,최대보유량(kg),운전압력(MPa)\nT1,제품,9000,0.5\n')
        result = scenario_triage.evaluate(self.p)
        self.assertEqual(result['critical_values'], [])
        self.assertEqual(result['questions'], [])

    def test_gate_holds_values_that_could_change_the_result(self):
        # 같은 신뢰도(병합 셀 0.90)라도 순위를 바꾸는 핵심값은 자동 기입하지 않습니다.
        self.upload('m.csv', '제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n', 'material')
        self.upload('f.csv', '설비번호,취급제품,최대보유량(kg),운전압력(MPa),운전온도(C)\nT1,제품,9000,0.5,20\nT2,제품,8000,0.5,20\n')
        critical = scenario_triage.critical_slot_keys(self.p)
        slot = next(s for s in ew.slots(self.p) if s['key'] == 'facility:T1|pressure')
        self.assertIn(slot['key'], critical)
        self.assertEqual(ew.review_gate(slot), [])               # 일반 항목이면 통과하는 값
        slot['facts'][0]['confidence'] = 0.90
        self.assertEqual(ew.review_gate(slot), [])
        self.assertIn('핵심값', ew.review_gate(slot, critical)[0])

    def test_llm_candidates_need_literal_quote_and_person_approval(self):
        self.upload('notes.txt', '운전압력(MPa): 0.5\n탱크의 설계용량은 10m3입니다.\n', 'facility', 'T')
        sha = ew.graph(self.p)['documents'][0]['sha256']

        class Stub:
            def generate_json(self, *, instructions, prompt):
                return {'items': [
                    {'field': 'capacity', 'raw': '10', 'header': '용량(m3)', 'quote': '설계용량은 10m3', 'location': '줄 2'},
                    {'field': 'pressure', 'raw': '7', 'header': '운전압력(MPa)', 'quote': '운전압력(MPa): 0.5', 'location': '줄 1'},
                    {'field': 'pressure', 'raw': '0.5', 'header': '운전압력(kPa)', 'quote': '운전압력(MPa): 0.5', 'location': '줄 1'},
                ]}

        output = evidence_llm.propose(self.p, sha, Stub())
        self.assertEqual(output, {'accepted': 1, 'rejected': 2})
        slot = next(s for s in ew.slots(self.p) if s['field'] == 'capacity')
        self.assertFalse(slot['chosen'])
        self.assertEqual(slot['facts'][0]['method'], 'llm')
        self.assertEqual(slot['facts'][0]['value'], 10)
        self.assertIn('AI', ew.review_gate(slot)[0])
        self.assertEqual(ew.approve_bulk(self.p, [slot['key']])['approved'], 0)   # 일괄 확인에서도 제외
        self.assertEqual(evidence_llm.propose(self.p, sha, Stub())['accepted'], 0)

    def test_large_site_stays_responsive(self):
        materials = '제품코드,제품명,CAS 번호,함량(%)\n' + ''.join(f'P{i},제품{i},64-17-5,{50 + i}\n' for i in range(30))
        facilities = '설비번호,취급제품,최대보유량(kg),운전압력(MPa),운전온도(C)\n' + ''.join(
            f'T{i},제품{i % 30},{1000 + i * 37},{0.1 + (i % 7) / 10},20\n' for i in range(200))
        self.upload('m.csv', materials, 'material')
        started = time.perf_counter()
        self.upload('f.csv', facilities)
        result = scenario_triage.evaluate(self.p)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(result['rows']), 6000)
        self.assertEqual(sum(r['linked'] for r in result['rows']), 200)
        self.assertLess(elapsed, 15)


if __name__ == '__main__':
    unittest.main()
