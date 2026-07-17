"""Send one explicit Telegram test message; email is intentionally not part of the urgent path."""

from pathlib import Path

from dotenv import load_dotenv

from tender_monitor.notifiers import Notifier

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

notifier = Notifier()
if "telegram" not in notifier.configured_channels():
    raise SystemExit("Telegram is not configured.")
notifier.send("telegram", {"id": 0, "source_name": "Open Tender Monitor", "title": "\u0422\u0435\u0441\u0442 \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f: \u043a\u0430\u043d\u0430\u043b \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d", "url": "http://localhost:8081"})
print("One Telegram test notification was sent.")
