"""Copy only SMTP settings from the legacy local configuration.

The script never prints credentials. It is intentionally a one-way local
import so the open-source monitor can be tested without retyping secrets.
"""

from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parents[1]
legacy = dotenv_values(BASE_DIR.parent / ".env")
target_path = BASE_DIR / ".env"
target = dotenv_values(target_path)

mapping = {
    "SMTP_HOST": "SMTP_HOST",
    "SMTP_PORT": "SMTP_PORT",
    "SMTP_USERNAME": "SMTP_USERNAME",
    "SMTP_PASSWORD": "SMTP_PASSWORD",
    "EMAIL_FROM": "EMAIL_FROM",
    "EMAIL_TO": "EMAIL_TO",
    "SMTP_USE_TLS": "SMTP_USE_TLS",
    "SMTP_USE_SSL": "SMTP_USE_SSL",
}

values = {key: value for key, value in target.items() if value is not None}
for destination, source in mapping.items():
    if legacy.get(source):
        values[destination] = legacy[source]

ordered = [
    "APP_HOST", "APP_PORT", "POLL_INTERVAL_SECONDS", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM", "EMAIL_TO", "SMTP_USE_TLS", "SMTP_USE_SSL",
]
target_path.write_text("\n".join(f"{key}={values.get(key, '')}" for key in ordered) + "\n", encoding="utf-8")
print("SMTP settings imported locally. Credentials were not displayed.")
