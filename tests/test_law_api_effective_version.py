from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

import engine.law_api as api


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 18, 23, 56, tzinfo=tz)


class LawEffectiveVersionTests(unittest.TestCase):
    TITLE = "유해화학물질의 규정수량에 관한 규정"

    def search(self, records):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"records": records}

        with patch.object(api, "get_api_credential", return_value=("test", "test")), \
             patch.object(api.requests, "get", return_value=Response()), \
             patch.object(api, "datetime", FixedDateTime):
            return api.search_current_source(self.TITLE, "admrul")

    def record(self, serial, effective_date):
        return {
            "행정규칙명": self.TITLE,
            "행정규칙일련번호": serial,
            "시행일자": effective_date,
            "발령일자": "20261014",
            "발령번호": "제2026-20호",
        }

    def test_future_announcement_does_not_replace_operative_version(self):
        result = self.search([
            self.record("2100000278502", "20260506"),
            self.record("2100000286916", "20261219"),
        ])
        self.assertEqual(result["api_status"], "FOUND")
        self.assertEqual(result["serial"], "2100000278502")
        self.assertEqual(result["upcoming_versions"][0]["serial"], "2100000286916")

    def test_future_only_does_not_get_approved_as_current(self):
        result = self.search([self.record("2100000286916", "20261219")])
        self.assertEqual(result["api_status"], "NO_EFFECTIVE_MATCH")

    def test_history_supplies_operative_version_when_current_list_only_has_future(self):
        class Response:
            def __init__(self, records):
                self.records = records

            def raise_for_status(self):
                pass

            def json(self):
                return {"records": self.records}

        current = Response([self.record("2100000286916", "20261219")])
        history = Response([self.record("2100000278502", "20260506")])
        with patch.object(api, "get_api_credential", return_value=("test", "test")), \
             patch.object(api.requests, "get", side_effect=[current, history]) as get, \
             patch.object(api, "datetime", FixedDateTime):
            result = api.search_current_source(self.TITLE, "admrul")
        self.assertEqual(result["serial"], "2100000278502")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["nw"], 2)

    def test_unknown_effective_date_does_not_hide_possible_revision(self):
        result = self.search([self.record("old", "20260506"), self.record("new", "")])
        self.assertEqual(result["api_status"], "INVALID_EFFECTIVE_DATE")


if __name__ == "__main__":
    unittest.main()
