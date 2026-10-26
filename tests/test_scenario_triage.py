import unittest

from engine.stage2 import evidence_workspace as ew, evidence_llm, scenario_triage
from engine.stage2.project import Stage2Project


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.p=Stage2Project('triage-test','가상 사업장')

    def upload(self,name,content,kind='facility',hint=''):
        return ew.ingest(self.p,name,content.encode(),kind,hint)

    def confirm(self):
        for slot in ew.slots(self.p):
            if not slot['chosen']:ew.approve(self.p,slot['key'],slot['facts'][0]['id'])

    def test_cartesian_pairs_and_incompatible_relation_held(self):
        self.upload('m.csv','제품코드,제품명,CAS 번호\nA,제품 A,64-17-5\nB,제품 B,67-56-1\n','material')
        self.upload('f.csv','설비번호,설비명,취급제품,최대보유량(kg),운전압력(MPa)\nT1,탱크1,제품 A,100,0.1\nT2,탱크2,제품 B,200,0.1\n')
        self.confirm();result=scenario_triage.evaluate(self.p)
        self.assertEqual(len(result['rows']),4)
        self.assertEqual(sum(r['linked'] for r in result['rows']),2)
        self.assertTrue(all(r['state']=='보류' for r in result['rows'] if not r['linked']))
        self.assertTrue(all(r['sources']['inventory']['sha256'] for r in result['rows'] if r['linked']))

    def test_missing_assumption_can_change_rank_and_is_not_published(self):
        self.upload('m.csv','제품코드,제품명,CAS 번호,함량(%)\nP,제품,64-17-5,100\n','material')
        self.upload('f.csv','설비번호,취급제품,최대보유량(kg),운전압력(MPa)\nT1,제품,,0\nT2,제품,8000,0\n')
        self.confirm();result=scenario_triage.evaluate(self.p)
        first=next(r for r in result['rows'] if r['facility']=='facility:T1')
        self.assertEqual(first['assumptions']['inventory']['value'],12000)
        self.assertEqual(first['rank'],1)
        self.assertIn('inventory',first['rank_sensitive'])
        self.assertEqual(first['state'],'보류')
        self.assertNotIn('최대보유량(kg)',ew.publishing_plan(self.p)['inventory.facilities'][0])

    def test_rule_gate_auto_fills_only_explicit_facility_name(self):
        self.upload('f.csv','설비번호,설비명,운전압력(MPa)\nT,탱크,1\n')
        slots={s['field']:s for s in ew.slots(self.p)}
        self.assertEqual(slots['name']['status'],'자동 기입')
        self.assertFalse(slots['pressure']['chosen'])
        self.assertIn('운전·물질',ew.review_gate(slots['pressure'])[0])
        self.upload('revision.csv','설비번호,설비명\nT,다른 탱크\n')
        self.assertEqual(next(s for s in ew.slots(self.p) if s['field']=='name')['status'],'값 충돌')

    def test_llm_candidates_need_literal_quote_and_person_approval(self):
        self.upload('notes.txt','운전압력(MPa): 0.5\n탱크의 설계용량은 10m3입니다.\n','facility','T')
        class Stub:
            def generate_json(self,*,instructions,prompt):
                return {'items':[
                    {'field':'capacity','raw':'10','header':'용량(m3)','quote':'설계용량은 10m3','location':'줄 2'},
                    {'field':'pressure','raw':'7','header':'운전압력(MPa)','quote':'운전압력(MPa): 0.5','location':'줄 1'},
                    {'field':'pressure','raw':'0.5','header':'운전압력(kPa)','quote':'운전압력(MPa): 0.5','location':'줄 1'},
                ]}
        sha=ew.graph(self.p)['documents'][0]['sha256']
        output=evidence_llm.propose(self.p,sha,Stub())
        self.assertEqual(output,{'accepted':1,'rejected':2})
        slot=next(s for s in ew.slots(self.p) if s['field']=='capacity')
        self.assertFalse(slot['chosen'])
        self.assertEqual(slot['facts'][0]['method'],'llm')
        self.assertEqual(slot['facts'][0]['value'],10)
        self.assertIn('신뢰도',ew.review_gate(slot)[0])
        self.assertEqual(evidence_llm.propose(self.p,sha,Stub())['accepted'],0)


if __name__=='__main__':unittest.main()
