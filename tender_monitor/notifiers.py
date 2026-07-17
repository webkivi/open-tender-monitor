from __future__ import annotations

import json
import os
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage

from .presentation import telegram_message


class Notifier:
    def configured_channels(self) -> set[str]:
        channels: set[str] = set()
        if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_IDS", "").strip():
            channels.add("telegram")
        if all(os.getenv(name, "").strip() for name in ("SMTP_HOST", "EMAIL_FROM", "EMAIL_TO")):
            channels.add("email")
        return channels

    def send(self, channel: str, tender: dict) -> None:
        if channel == "telegram":
            self._telegram(tender)
            return
        if channel == "email":
            self._email(tender)
            return
        raise ValueError(f"Unknown notification channel: {channel}")

    def _telegram(self, tender: dict) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_ids = [value.strip() for value in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if value.strip()]
        if not token or not chat_ids:
            raise RuntimeError("Telegram is not configured")
        text = telegram_message(tender)
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
        for chat_id in chat_ids:
            payload = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode("utf-8")
            request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=15):
                pass

    def _email(self, tender: dict) -> None:
        host = os.getenv("SMTP_HOST", "").strip()
        recipient = os.getenv("EMAIL_TO", "").strip()
        sender = os.getenv("EMAIL_FROM", "").strip()
        if not host or not recipient or not sender:
            raise RuntimeError("Email is not configured")
        message = EmailMessage()
        message["Subject"] = f"\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u043a\u0443\u043f\u043a\u0430: {tender['title'][:100]}"
        message["From"] = sender
        message["To"] = recipient
        message.set_content(f"{tender['source_name']}\n\n{tender['title']}\n\n{tender['url']}")
        port = int(os.getenv("SMTP_PORT", "465"))
        username = os.getenv("SMTP_USERNAME", "")
        password = os.getenv("SMTP_PASSWORD", "")
        if os.getenv("SMTP_USE_SSL", "true").lower() == "true":
            with smtplib.SMTP_SSL(host, port, timeout=20) as client:
                if username:
                    client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as client:
                if os.getenv("SMTP_USE_TLS", "false").lower() == "true":
                    client.starttls()
                if username:
                    client.login(username, password)
                client.send_message(message)
