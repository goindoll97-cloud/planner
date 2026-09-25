"""Article 29 suggestion rules are pure and must fail closed on missing facts."""
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'engine' / 'stage2' / 'cap_article29.py'
spec = importlib.util.spec_from_file_location('article29_standalone', MODULE)
article29 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(article29)


class Article29Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = article29.load_rules()

    def check(self, status, events, facts):
        return article29.assess(status, events, facts, data=self.rules, law_current=True)

    def test_licensed_quantity_bands_have_separate_legal_basis(self):
        facts = dict(transport=False, trial=False, quantity_band='minimum_to_lower')
        report = self.check('영업허가', ['material'], facts)
        self.assertEqual(report['state'], '후보 제안')
        self.assertEqual([(r['action'], r['clause']) for r in report['candidates']],
                         [('변경신고', '제29조제1항제2호바목')])
        facts['quantity_band'] = 'lower_or_above'
        permit = self.check('영업허가', ['material'], facts)
        self.assertEqual([(r['action'], r['clause']) for r in permit['candidates']],
                         [('변경허가', '제29조제1항제1호다목')])

    def test_facility_requires_impact_and_scenario_for_report(self):
        facts = dict(same_site=True, cap_submission=False, boundary_or_other=True,
                     scenario_amount=True, impact_expanded=None)
        pending = self.check('영업허가', ['facility'], facts)
        self.assertEqual(pending['state'], '확인 필요')
        self.assertIn('총괄영향범위 확대 여부', pending['missing'])
        facts['impact_expanded'] = False
        self.assertEqual(self.check('영업허가', ['facility'], facts)['candidates'][0]['clause'], '제29조제1항제2호다목')
        facts['cap_submission'] = True
        self.assertEqual(self.check('영업허가', ['facility'], facts)['candidates'][0]['action'], '변경허가')

    def test_accumulated_increase_uses_original_baseline(self):
        self.assertAlmostEqual(article29.cumulative_ratio(100, 150), 0.5)
        self.assertIsNone(article29.cumulative_ratio(0, 150))
        result = self.check('영업허가', ['holding_total'], {'holding_ratio': article29.cumulative_ratio(100, 150)})
        self.assertEqual(result['candidates'][0]['clause'], '제29조제1항제1호나목')
        self.assertEqual(self.check('영업신고', ['holding_total'],
                                    {'holding_ratio': 0.5, 'permit_transition': False})['candidates'][0]['clause'],
                         '제29조제1항제3호다목')

    def test_unconfirmed_and_changed_law_never_offer_a_candidate(self):
        facts = dict(transport=False, trial=False, quantity_band='lower_or_above')
        self.assertEqual(self.check('미확인', ['material'], facts)['candidates'], [])
        self.assertEqual(article29.assess('영업허가', ['material'], facts, data=self.rules)['state'], '법령 변경 확인 필요')
        self.assertFalse(article29.law_ready(self.rules, {'observation_valid': True, 'serial': 'new',
                                                          'effective_date': '20251001'}, True))

    def test_registered_business_requires_permit_transition_and_storage_kind(self):
        pending = self.check('영업신고', ['storage_capacity'], {'storage_ratio': 0.6, 'storage_kind': 'storage'})
        self.assertEqual(pending['state'], '확인 필요')
        self.assertEqual(self.check('영업신고', ['storage_capacity'],
                                    {'storage_ratio': 0.6, 'storage_kind': 'transport', 'permit_transition': False})['candidates'], [])
        confirmed = self.check('영업신고', ['storage_capacity'],
                               {'storage_ratio': 0.6, 'storage_kind': 'storage', 'permit_transition': False})
        self.assertEqual(confirmed['candidates'][0]['clause'], '제29조제1항제3호나목')

    def test_vehicle_50_percent_threshold_changes_action(self):
        permit = self.check('영업허가', ['vehicle'], {'capacity_threshold_applies': True})
        self.assertEqual(permit['candidates'][0]['action'], '변경허가')
        report = self.check('영업허가', ['vehicle'], {'capacity_threshold_applies': False})
        self.assertEqual(report['candidates'][0]['action'], '변경신고')
        self.assertEqual(self.check('영업허가', ['vehicle'], {})['state'], '확인 필요')

    def test_representative_deadline_and_trial_exception(self):
        self.assertEqual(self.check('영업허가', ['representative'], {})['candidates'][0]['due'], '변경일부터 60일 이내')
        self.assertEqual(self.check('영업허가', ['trial'],
                                    dict(market_unrelated=True, trial_days=60, temporary_material=True,
                                         scenario_amount=True))['candidates'][0]['due'], '변경 전')


if __name__ == '__main__':
    unittest.main()
