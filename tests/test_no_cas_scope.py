import unittest

import pandas as pd

from engine.no_cas_scope import build_no_cas_scope_index, primary_candidate, screen_no_cas_scopes


class NoCasScopeScreeningTest(unittest.TestCase):
    def test_reaction_product_component_cas_is_found_but_held(self):
        master = pd.DataFrame([
            {
                "designation_id": "RULE-RXN-1",
                "regime": "CAP_APP2",
                "substance_name": "Reaction product of A and B",
                "scope_type": "REACTION_PRODUCT",
                "direct_cas": "",
                "all_cas_in_row": "32588-54-8;68892-28-4",
                "source_text": "Reaction product of A(32588-54-8) and B(68892-28-4)",
            }
        ])
        inventory = pd.DataFrame([
            {"No.": 1, "제품명": "원료 A", "물질명(알면 입력)": "A", "CAS No.": "32588-54-8"}
        ])
        index = build_no_cas_scope_index(master)
        found = screen_no_cas_scopes(inventory, index)
        self.assertFalse(found.empty)
        self.assertEqual(found.loc[0, "candidate_match_type"], "COMPONENT_CAS_CANDIDATE")
        self.assertTrue(str(found.loc[0, "candidate_status"]).startswith("판정보류"))

    def test_broad_salt_family_name_is_candidate_not_auto_match(self):
        master = pd.DataFrame([
            {
                "designation_id": "RULE-SALT-1",
                "regime": "CAP_APP2",
                "substance_name": "Chromic acid and its salts",
                "direct_cas": "",
                "source_text": "Chromic acid and its salts",
            }
        ])
        inventory = pd.DataFrame([
            {"No.": 1, "제품명": "Sodium dichromate", "물질명(알면 입력)": "Sodium dichromate", "CAS No.": "10588-01-9"}
        ])
        index = build_no_cas_scope_index(master)
        found = screen_no_cas_scopes(inventory, index)
        self.assertFalse(found.empty)
        self.assertEqual(found.loc[0, "candidate_match_type"], "NAME_SCOPE_CANDIDATE")
        self.assertTrue(str(found.loc[0, "candidate_status"]).startswith("판정보류"))

    def test_explicit_exception_cas_has_highest_priority(self):
        master = pd.DataFrame([
            {
                "designation_id": "RULE-EX-1",
                "regime": "CAP_APP2",
                "substance_name": "Toluenediamines excluding 2,6-toluenediamine",
                "direct_cas": "",
                "source_text": "Toluenediamines excluding 2,6-toluenediamine (823-40-5)",
            },
            {
                "designation_id": "RULE-NAME-2",
                "regime": "CAP_APP2",
                "substance_name": "Toluenediamine compounds",
                "direct_cas": "",
                "source_text": "Toluenediamine compounds",
            },
        ])
        inventory = pd.DataFrame([
            {"No.": 1, "제품명": "2,6-Diaminotoluene", "물질명(알면 입력)": "2,6-Diaminotoluene", "CAS No.": "823-40-5"}
        ])
        index = build_no_cas_scope_index(master)
        found = screen_no_cas_scopes(inventory, index)
        primary = primary_candidate(found, "1")
        self.assertIsNotNone(primary)
        self.assertEqual(primary["candidate_match_type"], "EXPLICIT_EXCEPTION_CAS")
        self.assertTrue(primary["is_explicit_exception"])

    def test_direct_cas_rows_are_not_duplicated_as_no_cas_scope(self):
        master = pd.DataFrame([
            {
                "designation_id": "DIRECT-1",
                "regime": "CAP_APP2",
                "substance_name": "Formaldehyde",
                "scope_type": "DIRECT_CAS",
                "direct_cas": "50-00-0",
                "source_text": "Formaldehyde (50-00-0)",
            }
        ])
        index = build_no_cas_scope_index(master)
        self.assertTrue(index.empty)


if __name__ == "__main__":
    unittest.main()
