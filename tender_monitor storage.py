from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .models import TenderCandidate


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = database_path
        self.initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tenders (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL DEFAULT '',
                    matched_terms TEXT NOT NULL DEFAULT '',
                    published_at TEXT,
                    rss_observed_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    notified_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    tender_id INTEGER,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(tender_id) REFERENCES tenders(id)
                );
                CREATE TABLE IF NOT EXISTS source_state (
                    source_key TEXT PRIMARY KEY,
                    checked_at TEXT,
                    last_error TEXT,
                    last_status TEXT NOT NULL DEFAULT 'idle',
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    next_check_at TEXT
                );
                CREATE TABLE IF NOT EXISTS source_checks (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    feed_count INTEGER NOT NULL,
                    item_count INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_jobs (
                    id INTEGER PRIMARY KEY,
                    tender_id INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    attempted_at TEXT,
                    acknowledged_at TEXT,
                    UNIQUE(tender_id, channel),
                    FOREIGN KEY(tender_id) REFERENCES tenders(id)
                );
                CREATE INDEX IF NOT EXISTS notification_jobs_due
                ON notification_jobs(state, next_attempt_at, id);
                """
            )
            existing = {row[1] for row in db.execute("PRAGMA table_info(source_state)")}
            for column, definition in (
                ("last_status", "TEXT NOT NULL DEFAULT 'idle'"),
                ("failure_count", "INTEGER NOT NULL DEFAULT 0"),
                ("next_check_at", "TEXT"),
            ):
                if column not in existing:
                    db.execute(f"ALTER TABLE source_state ADD COLUMN {column} {definition}")
            tender_columns = {row[1] for row in db.execute("PRAGMA table_info(tenders)")}
            if "matched_terms" not in tender_columns:
                db.execute("ALTER TABLE tenders ADD COLUMN matched_terms TEXT NOT NULL DEFAULT ''")
            if "rss_observed_at" not in tender_columns:
                db.execute("ALTER TABLE tenders ADD COLUMN rss_observed_at TEXT")

    def insert_tender(self, item: TenderCandidate) -> int | None:
        with self.connection() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO tenders
                (source_key, source_name, title, url, summary, matched_terms, published_at, rss_observed_at, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.source_key, item.source_name, item.title, item.url, item.summary, item.matched_terms, item.published_at, item.rss_observed_at, now()),
            )
            if not cursor.rowcount:
                return None
            tender_id = int(cursor.lastrowid)
            db.execute("INSERT INTO events(tender_id, created_at, kind) VALUES (?, ?, ?)", (tender_id, now(), "found"))
            return tender_id

    def recent_tenders(self, limit: int = 200) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tenders ORDER BY id DESC LIMIT ?", (limit,))]

    def get_tender(self, tender_id: int) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()
            return dict(row) if row else None

    def set_status(self, tender_id: int, status: str, details: str = "") -> bool:
        allowed = {"new", "in_progress", "not_interesting", "remind"}
        if status not in allowed:
            return False
        with self.connection() as db:
            cursor = db.execute("UPDATE tenders SET status = ? WHERE id = ?", (status, tender_id))
            if cursor.rowcount:
                db.execute("INSERT INTO events(tender_id, created_at, kind, details) VALUES (?, ?, ?, ?)", (tender_id, now(), "status", status + (":" + details if details else "")))
                return True
        return False

    def mark_notified(self, tender_id: int) -> None:
        with self.connection() as db:
            db.execute("UPDATE tenders SET notified_at = ? WHERE id = ?", (now(), tender_id))

    def enqueue_notifications(self, tender_id: int, channels: set[str], suppressed: bool = False) -> None:
        state = "suppressed" if suppressed else "pending"
        timestamp = now()
        with self.connection() as db:
            for channel in sorted(channels):
                db.execute(
                    """INSERT OR IGNORE INTO notification_jobs
                    (tender_id, channel, state, next_attempt_at, created_at, acknowledged_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (tender_id, channel, state, None if suppressed else timestamp, timestamp, timestamp if suppressed else None),
                )
                db.execute(
                    "INSERT INTO events(tender_id, created_at, kind, details) VALUES (?, ?, ?, ?)",
                    (tender_id, timestamp, "notification_suppressed" if suppressed else "notification_queued", channel),
                )

    def claim_notification_jobs(self, limit: int = 10) -> list[dict]:
        """Claim due jobs. The monitor has one worker; interrupted jobs are recovered at startup."""
        timestamp = now()
        with self.connection() as db:
            rows = db.execute(
                """SELECT jobs.*, tenders.source_key, tenders.source_name, tenders.title, tenders.url,
                          tenders.summary, tenders.matched_terms, tenders.published_at, tenders.first_seen_at
                   FROM notification_jobs AS jobs
                   JOIN tenders ON tenders.id = jobs.tender_id
                   WHERE jobs.state = 'pending' AND jobs.next_attempt_at <= ?
                   ORDER BY jobs.id LIMIT ?""",
                (timestamp, max(1, limit)),
            ).fetchall()
            job_ids = [int(row["id"]) for row in rows]
            if job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                db.execute(
                    f"UPDATE notification_jobs SET state = 'sending', attempts = attempts + 1, attempted_at = ? WHERE id IN ({placeholders})",
                    (timestamp, *job_ids),
                )
            return [dict(row) for row in rows]

    def recover_interrupted_notification_jobs(self) -> int:
        """Make jobs claimed before a process stop eligible for a fresh delivery attempt."""
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE notification_jobs SET state = 'pending', next_attempt_at = ? WHERE state = 'sending'",
                (now(),),
            )
            return cursor.rowcount

    def mark_notification_sent(self, job_id: int) -> None:
        timestamp = now()
        with self.connection() as db:
            job = db.execute("SELECT tender_id, channel FROM notification_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return
            db.execute(
                "UPDATE notification_jobs SET state = 'sent', acknowledged_at = ?, next_attempt_at = NULL, last_error = '' WHERE id = ?",
                (timestamp, job_id),
            )
            if job["channel"] == "telegram":
                db.execute("UPDATE tenders SET notified_at = ? WHERE id = ?", (timestamp, job["tender_id"]))
            db.execute(
                "INSERT INTO events(tender_id, created_at, kind, details) VALUES (?, ?, ?, ?)",
                (job["tender_id"], timestamp, "notification_sent", job["channel"]),
            )

    def reschedule_notification(self, job_id: int, error: str, max_attempts: int = 6) -> None:
        with self.connection() as db:
            job = db.execute("SELECT tender_id, channel, attempts FROM notification_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                return
            attempts = int(job["attempts"])
            failed = attempts >= max_attempts
            delays = (5, 15, 45, 120, 300)
            delay = delays[min(max(attempts - 1, 0), len(delays) - 1)]
            next_attempt = None if failed else (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
            db.execute(
                "UPDATE notification_jobs SET state = ?, next_attempt_at = ?, last_error = ? WHERE id = ?",
                ("failed" if failed else "pending", next_attempt, error[:500], job_id),
            )
            db.execute(
                "INSERT INTO events(tender_id, created_at, kind, details) VALUES (?, ?, ?, ?)",
                (job["tender_id"], now(), "notification_failed" if failed else "notification_retry", f"{job['channel']}: {error[:300]}"),
            )

    def notification_summary(self) -> dict[str, int]:
        with self.connection() as db:
            rows = db.execute("SELECT state, COUNT(*) AS count FROM notification_jobs GROUP BY state").fetchall()
        return {row["state"]: int(row["count"]) for row in rows}

    def source_checked(self, source_key: str) -> None:
        with self.connection() as db:
            db.execute(
                """INSERT INTO source_state(source_key, checked_at, last_error, last_status, failure_count, next_check_at)
                VALUES (?, ?, '', 'ok', 0, NULL)
                ON CONFLICT(source_key) DO UPDATE SET checked_at = excluded.checked_at, last_error = '',
                last_status = 'ok', failure_count = 0, next_check_at = NULL""",
                (source_key, now()),
            )

    def record_source_check(self, source_key: str, feed_count: int, item_count: int, error_count: int, duration_ms: int) -> None:
        self.source_checked(source_key)
        with self.connection() as db:
            db.execute(
                """INSERT INTO source_checks(source_key, checked_at, feed_count, item_count, error_count, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (source_key, now(), max(0, feed_count), max(0, item_count), max(0, error_count), max(0, duration_ms)),
            )

    def latency_summary(self, source_key: str, limit: int = 100) -> dict:
        with self.connection() as db:
            rows = db.execute(
                """SELECT published_at, rss_observed_at, first_seen_at, notified_at FROM tenders
                WHERE source_key = ?
                ORDER BY id DESC LIMIT ?""",
                (source_key, limit),
            ).fetchall()
            checks = db.execute(
                """SELECT checked_at, feed_count, item_count, error_count, duration_ms FROM source_checks
                WHERE source_key = ? ORDER BY id DESC LIMIT 20""",
                (source_key,),
            ).fetchall()
        publication_delays: list[float] = []
        rss_to_intake: list[float] = []
        intake_to_telegram: list[float] = []
        rss_to_telegram: list[float] = []
        for row in rows:
            try:
                seen = datetime.fromisoformat(row["first_seen_at"]).astimezone(timezone.utc)
                if row["published_at"]:
                    published = parsedate_to_datetime(row["published_at"]).astimezone(timezone.utc)
                    delay = (seen - published).total_seconds()
                    if delay >= 0:
                        publication_delays.append(delay)
                if row["rss_observed_at"]:
                    observed = datetime.fromisoformat(row["rss_observed_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                    bridge_delay = (seen - observed).total_seconds()
                    if bridge_delay >= 0:
                        rss_to_intake.append(bridge_delay)
                    if row["notified_at"]:
                        acknowledged = datetime.fromisoformat(row["notified_at"]).astimezone(timezone.utc)
                        telegram_delay = (acknowledged - seen).total_seconds()
                        complete_delay = (acknowledged - observed).total_seconds()
                        if telegram_delay >= 0:
                            intake_to_telegram.append(telegram_delay)
                        if complete_delay >= 0:
                            rss_to_telegram.append(complete_delay)
            except (TypeError, ValueError):
                continue
        return {
            "publication_to_intake_proxy": self._delay_stats(publication_delays),
            "rss_to_intake": self._delay_stats(rss_to_intake),
            "intake_to_telegram": self._delay_stats(intake_to_telegram),
            "rss_to_telegram": self._delay_stats(rss_to_telegram),
            "recent_checks": [dict(row) for row in checks],
        }

    @staticmethod
    def _delay_stats(delays: list[float]) -> dict:
        if not delays:
            return {"samples": 0, "min_seconds": None, "average_seconds": None, "p95_seconds": None, "max_seconds": None, "over_60_seconds": 0}
        ordered = sorted(delays)
        p95 = ordered[max(0, int((len(ordered) - 1) * 0.95))]
        return {
            "samples": len(delays),
            "min_seconds": round(min(delays)),
            "average_seconds": round(sum(delays) / len(delays)),
            "p95_seconds": round(p95),
            "max_seconds": round(max(delays)),
            "over_60_seconds": sum(delay > 60 for delay in delays),
        }

    def source_error(self, source_key: str, status: str, message: str) -> int:
        with self.connection() as db:
            row = db.execute("SELECT failure_count FROM source_state WHERE source_key = ?", (source_key,)).fetchone()
            failures = (int(row["failure_count"]) if row else 0) + 1
            base_pause = 300 if status in {"rate_limited", "challenge"} else 60
            pause_seconds = min(base_pause * (2 ** min(failures - 1, 4)), 1800)
            next_check = (datetime.now(timezone.utc) + timedelta(seconds=pause_seconds)).isoformat(timespec="seconds")
            db.execute(
                """INSERT INTO source_state(source_key, checked_at, last_error, last_status, failure_count, next_check_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET checked_at = excluded.checked_at, last_error = excluded.last_error,
                last_status = excluded.last_status, failure_count = excluded.failure_count, next_check_at = excluded.next_check_at""",
                (source_key, now(), message[:500], status, failures, next_check),
            )
            return pause_seconds

    def may_check_source(self, source_key: str) -> bool:
        with self.connection() as db:
            row = db.execute("SELECT next_check_at FROM source_state WHERE source_key = ?", (source_key,)).fetchone()
        if not row or not row["next_check_at"]:
            return True
        return datetime.fromisoformat(row["next_check_at"]) <= datetime.now(timezone.utc)

    def source_states(self) -> dict[str, dict]:
        with self.connection() as db:
            return {row["source_key"]: dict(row) for row in db.execute("SELECT * FROM source_state")}
