import tempfile
import unittest
from pathlib import Path

from tender_monitor.models import SourceConfig, TenderCandidate
from tender_monitor.sources import matches
from tender_monitor.storage import Storage


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.source = SourceConfig("eis", "ЕИС", True, "https://example.test", 45, ["битрикс"], ["вакансия"])

    def test_matching_uses_include_and_exclude_terms(self):
        self.assertTrue(matches(self.source, "Поддержка Битрикс"))
        self.assertFalse(matches(self.source, "Вакансия разработчика Битрикс"))

    def test_storage_deduplicates_by_url(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "monitor.db")
            item = TenderCandidate("eis", "ЕИС", "Поддержка Битрикс", "https://example.test/1")
            self.assertIsNotNone(storage.insert_tender(item))
            self.assertIsNone(storage.insert_tender(item))

    def test_source_error_postpones_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "monitor.db")
            pause = storage.source_error("eis", "challenge", "CAPTCHA")
            self.assertEqual(pause, 300)
            self.assertFalse(storage.may_check_source("eis"))


if __name__ == "__main__":
    unittest.main()
