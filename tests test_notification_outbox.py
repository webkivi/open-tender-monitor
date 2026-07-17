import tempfile
import unittest
from pathlib import Path

from tender_monitor.models import TenderCandidate
from tender_monitor.storage import Storage


class NotificationOutboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.directory.name) / "monitor.db")
        self.tender_id = self.storage.insert_tender(
            TenderCandidate("eis", "EIS", "Relevant tender", "https://example.test/tender/1")
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_enqueue_is_idempotent_and_claims_a_job(self):
        self.storage.enqueue_notifications(self.tender_id, {"telegram"})
        self.storage.enqueue_notifications(self.tender_id, {"telegram"})

        jobs = self.storage.claim_notification_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["channel"], "telegram")
        self.assertEqual(jobs[0]["attempts"], 0)
        self.assertEqual(self.storage.notification_summary(), {"sending": 1})

    def test_telegram_ack_marks_tender_notified(self):
        self.storage.enqueue_notifications(self.tender_id, {"telegram", "email"})
        jobs = self.storage.claim_notification_jobs()
        telegram_job = next(job for job in jobs if job["channel"] == "telegram")

        self.storage.mark_notification_sent(telegram_job["id"])

        self.assertIsNotNone(self.storage.get_tender(self.tender_id)["notified_at"])
        self.assertEqual(self.storage.notification_summary()["sent"], 1)

    def test_failed_delivery_is_rescheduled_before_final_failure(self):
        self.storage.enqueue_notifications(self.tender_id, {"telegram"})
        job = self.storage.claim_notification_jobs()[0]

        self.storage.reschedule_notification(job["id"], "temporary network failure")

        self.assertEqual(self.storage.notification_summary(), {"pending": 1})

    def test_suppressed_first_sync_never_becomes_due(self):
        self.storage.enqueue_notifications(self.tender_id, {"telegram"}, suppressed=True)

        self.assertEqual(self.storage.claim_notification_jobs(), [])
        self.assertEqual(self.storage.notification_summary(), {"suppressed": 1})

    def test_interrupted_job_is_recovered_after_restart(self):
        self.storage.enqueue_notifications(self.tender_id, {"telegram"})
        self.storage.claim_notification_jobs()

        recovered = self.storage.recover_interrupted_notification_jobs()

        self.assertEqual(recovered, 1)
        self.assertEqual(self.storage.notification_summary(), {"pending": 1})

    def test_latency_uses_rss_observation_and_telegram_ack(self):
        tender_id = self.storage.insert_tender(
            TenderCandidate(
                "eis",
                "EIS",
                "Measured tender",
                "https://example.test/tender/2",
                published_at="Fri, 17 Jul 2026 06:00:00 GMT",
                rss_observed_at="2026-07-17T06:00:45+00:00",
            )
        )
        with self.storage.connection() as db:
            db.execute(
                "UPDATE tenders SET first_seen_at = ?, notified_at = ? WHERE id = ?",
                ("2026-07-17T06:00:46+00:00", "2026-07-17T06:00:48+00:00", tender_id),
            )

        latency = self.storage.latency_summary("eis")

        self.assertEqual(latency["rss_to_intake"]["average_seconds"], 1)
        self.assertEqual(latency["intake_to_telegram"]["average_seconds"], 2)
        self.assertEqual(latency["rss_to_telegram"]["average_seconds"], 3)


if __name__ == "__main__":
    unittest.main()
