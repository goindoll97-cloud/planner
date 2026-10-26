import unittest
from io import BytesIO
from zipfile import ZipFile
from engine.stage2 import evidence_workspace as e
from engine.stage2.project import Stage2Project

class EvidenceTests(unittest.TestCase):
    def setUp(self):self.p=Stage2Project('evidence-test','가상 회사')
    def upload(self,name,text,kind='facility'):return e.ingest(self.p,name,text.encode('utf-8'),kind)
    def approve_all(self):
        for s in e.slots(self.p):e.approve(self.p,s['key'],s['facts'][0]['id'])
    def test_conflicts_units_and_provenance(self):
        self.upload('a.csv','설비번호,용량(L)\nTK-1,10000\n')
        self.upload('b.csv','설비번호,용량(m3)\nTK-1,12\n')
        slot=e.slots(self.p)[0]
        self.assertEqual(slot['status'],'값 충돌');self.assertEqual([f['value'] for f in slot['facts']],[10,12])
        e.approve(self.p,slot['key'],slot['facts'][0]['id'])
        self.assertEqual(e.confirmed_entities(self.p)['facility:TK-1']['capacity'],10)
        self.assertIn('행 2 열 2',slot['facts'][0]['location'])
        self.upload('c.csv','설비번호,용량(m3)\nTK-1,15\n')
        self.assertEqual(e.slots(self.p)[0]['status'],'값 충돌')
    def test_identical_values_are_not_conflicts_but_still_need_review(self):
        self.upload('a.csv','설비번호,용량(L)\nTK,10000\n')
        self.upload('b.csv','설비번호,용량(m3)\nTK,10\n')
        self.assertEqual(e.slots(self.p)[0]['status'],'담당자 확인')
    def test_ranges_and_unspecified_units_not_silently_accepted(self):
        for text in ['設','10~20','10']:
            self.p=Stage2Project('test','test')
            self.upload('a.csv',f'설비번호,운전압력\nTK,{text}\n')
            slot=e.slots(self.p)[0]
            with self.assertRaises(ValueError):e.approve(self.p,slot['key'],slot['facts'][0]['id'])
    def test_publish_is_atomic_and_invalidated_on_source_change(self):
        self.upload('a.csv','설비번호,설비명,용량(m3)\nTK,가상 탱크,10\n');self.approve_all()
        e.publish(self.p)
        self.assertEqual(self.p.get_field('inventory.facilities').status,'USER_CONFIRMED')
        self.upload('b.csv','설비번호,용량(m3)\nTK,12\n')
        self.assertEqual(self.p.get_field('inventory.facilities').status,'HOLD')
        with self.assertRaises(ValueError):e.publish(self.p)
    def test_same_file_dedup_and_material_identity(self):
        text='제품코드,제품명,CAS 번호\nP1,제품 A,64-17-5\nP2,제품 B,64-17-5\n'
        self.upload('a.csv',text,'material');self.approve_all()
        self.assertEqual(self.upload('copy.csv',text,'material'),0)
        self.assertEqual(len(e.confirmed_entities(self.p)),2)
    def test_unparsed_document_and_missing_scenario_inputs_are_tasks(self):
        e.ingest(self.p,'sds.txt',b'Unstructured safety document','material','P1')
        self.upload('a.csv','설비번호,설비명\nTK,가상 탱크\n')
        self.assertTrue(any('연결하지 못' in t['task'] for t in e.tasks(self.p)))
        self.assertTrue(any('운전압력' in t['task'] for t in e.tasks(self.p)))
    def test_manual_corrections_cas_validation_and_report(self):
        e.add_manual(self.p,'material:P1','cas','64-17-5','시험 SDS p.3')
        self.approve_all();self.assertIn('시험 SDS p.3',e.report(self.p))
        e.add_manual(self.p,'material:P1','cas','64-17-6','오류 시험')
        slot=e.slots(self.p)[0]
        with self.assertRaises(ValueError):e.approve(self.p,slot['key'],slot['facts'][-1]['id'])
    def test_demo_end_to_end(self):
        with ZipFile(BytesIO(e.demo_zip())) as z:
            for name in z.namelist():
                if name.endswith('.csv'):e.ingest(self.p,name,z.read(name),'material' if 'materials' in name else 'facility')
        self.assertEqual(sum(s['status']=='값 충돌' for s in e.slots(self.p)),1)
        self.approve_all();self.assertEqual(e.tasks(self.p),[])
        self.assertEqual(set(e.publish(self.p)),{'inventory.chemicals','inventory.facilities'})
    def test_invalid_file_leaves_graph_unchanged(self):
        before=e.graph(self.p)
        with self.assertRaises(ValueError):e.ingest(self.p,'bad.hwp',b'data')
        self.assertEqual(e.graph(self.p),before)

if __name__=='__main__':unittest.main()
