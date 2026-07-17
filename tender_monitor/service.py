from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .notifiers import Notifier
from .sources import PublicPageAdapter, SourceAccessError, load_sources
from .storage import Storage


class MonitorService:
    def __init__(self, storage: Storage, sources_path: Path) -> None:
        self.storage = storage
        self.sources_path = sources_path
        self.adapter = PublicPageAdapter()
        self.notifier = Notifier()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="tender-monitor", daemon=True)
        self.delivery_thread = threading.Thread(target=self._delivery_loop, name="notification-delivery", daemon=True)
        self.telegram_thread = threading.Thread(target=self._telegram_loop, name="telegram-actions", daemon=True)
        self.last_checked: dict[str, float] = {}

    def start(self) -> None:
        self.storage.recover_interrupted_notification_jobs()
        self.thread.start()
        self.delivery_thread.start()
        self.telegram_thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def scan_now(self) -> None:
        for source in load_sources(self.sources_path):
            if source.enabled and self.storage.may_check_source(source.key):
                self._scan(source)

    def _loop(self) -> None:
        while not self.stop_event.wait(1):
            for source in load_sources(self.sources_path):
                if not source.enabled:
                    continue
                if self.storage.may_check_source(source.key) and time.monotonic() - self.last_checked.get(source.key, 0) >= max(source.poll_seconds, 20):
                    self._scan(source)

    def _scan(self, source) -> None:
        self.last_checked[source.key] = time.monotonic()
        try:
            for candidate in self.adapter.fetch(source):
                tender_id = self.storage.insert_tender(candidate)
                if tender_id:
                    tender = self.storage.get_tender(tender_id)
                    if tender:
                        self.storage.enqueue_notifications(tender_id, self.notifier.configured_channels())
            self.storage.source_checked(source.key)
        except SourceAccessError as error:
            self.storage.source_error(source.key, error.status, str(error))
        except Exception as error:
            self.storage.source_error(source.key, "error", str(error))

    def enqueue_tender_notifications(self, tender_id: int, suppressed: bool = False) -> None:
        self.storage.enqueue_notifications(tender_id, self.notifier.configured_channels(), suppressed=suppressed)

    def _delivery_loop(self) -> None:
        while not self.stop_event.wait(1):
            for job in self.storage.claim_notification_jobs():
                try:
                    self.notifier.send(job["channel"], job)
                    self.storage.mark_notification_sent(int(job["id"]))
                except Exception as error:
                    self.storage.reschedule_notification(int(job["id"]), str(error))

    def _telegram_loop(self) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return
        offset = 0
        while not self.stop_event.is_set():
            try:
                query = urllib.parse.urlencode({"timeout": 20, "offset": offset})
                with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates?{query}", timeout=30) as response:
                    updates = json.loads(response.read())
                for update in updates.get("result", []):
                    offset = int(update["update_id"]) + 1
                    callback = update.get("callback_query")
                    if not callback:
                        continue
                    parts = callback.get("data", "").split(":")
                    if len(parts) == 3 and parts[0] == "status":
                        self.storage.set_status(int(parts[1]), parts[2], "telegram")
                    callback_id = callback.get("id")
                    if callback_id:
                        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/answerCallbackQuery?" + urllib.parse.urlencode({"callback_query_id": callback_id}), timeout=10).close()
            except Exception:
                self.stop_event.wait(5)
