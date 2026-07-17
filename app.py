from __future__ import annotations

import atexit
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

from tender_monitor.service import MonitorService
from tender_monitor.models import SourceConfig
from tender_monitor.sources import load_sources, matches, matching_terms, save_sources, tender_match_text
from tender_monitor.models import TenderCandidate
from tender_monitor.storage import Storage

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
storage = Storage(BASE_DIR / "data" / "monitor.db")
service = MonitorService(storage, BASE_DIR / "config" / "sources.json")
service.start()
atexit.register(service.stop)

app = Flask(__name__)


@app.after_request
def allow_extension_ingest(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Ingest-Token"
    return response


@app.get("/")
def index():
    return render_template("index.html", tenders=storage.recent_tenders(), sources=load_sources(service.sources_path), states=storage.source_states())


@app.post("/scan")
def scan():
    service.scan_now()
    return redirect(url_for("index"))


@app.post("/sources/save")
def save_source_settings():
    configured: list[SourceConfig] = []
    for source in load_sources(service.sources_path):
        key = source.key
        configured.append(
            SourceConfig(
                key=key,
                name=source.name,
                enabled=request.form.get(f"{key}_enabled") == "on",
                search_url=request.form.get(f"{key}_search_url", "").strip(),
                poll_seconds=max(20, min(3600, int(request.form.get(f"{key}_poll_seconds", source.poll_seconds)))),
                include_terms=[term.strip() for term in request.form.get(f"{key}_include_terms", "").split(",") if term.strip()],
                exclude_terms=[term.strip() for term in request.form.get(f"{key}_exclude_terms", "").split(",") if term.strip()],
                rss_url=request.form.get(f"{key}_rss_url", "").strip(),
            )
        )
    save_sources(service.sources_path, configured)
    return redirect(url_for("index"))


@app.post("/tenders/<int:tender_id>/status")
def set_status(tender_id: int):
    storage.set_status(tender_id, request.form.get("status", "new"), "dashboard")
    return redirect(url_for("index"))


@app.get("/api/status")
def status():
    return jsonify({"sources": storage.source_states(), "latency": {"eis": storage.latency_summary("eis")}, "notifications": storage.notification_summary(), "tenders": storage.recent_tenders(30)})


@app.post("/api/heartbeat/<source_key>")
def heartbeat(source_key: str):
    token = os.getenv("INGEST_TOKEN", "")
    if not token or request.headers.get("X-Ingest-Token", "") != token:
        return jsonify({"error": "unauthorized"}), 401
    source = next((item for item in load_sources(service.sources_path) if item.key == source_key), None)
    if not source:
        return jsonify({"error": "unknown_source"}), 404
    payload = request.get_json(silent=True) or {}
    storage.record_source_check(
        source_key,
        int(payload.get("feed_count", 0)),
        int(payload.get("item_count", 0)),
        int(payload.get("error_count", 0)),
        int(payload.get("duration_ms", 0)),
    )
    return jsonify({"ok": True})


@app.post("/api/intake/<source_key>")
def intake(source_key: str):
    token = os.getenv("INGEST_TOKEN", "")
    if not token or request.headers.get("X-Ingest-Token", "") != token:
        return jsonify({"error": "unauthorized"}), 401
    source = next((item for item in load_sources(service.sources_path) if item.key == source_key), None)
    if not source:
        return jsonify({"error": "unknown_source"}), 404
    payload = request.get_json(silent=True) or {}
    suppress_notifications = bool(payload.get("suppress_notifications", False))
    title = str(payload.get("title", "")).strip()
    url = str(payload.get("url", "")).strip()
    if not title or not url.startswith(("https://", "http://")):
        return jsonify({"error": "invalid_item"}), 400
    storage.source_checked(source.key)
    summary = str(payload.get("summary", ""))
    match_text = tender_match_text(source.key, title, summary)
    if not matches(source, match_text):
        return jsonify({"accepted": False, "reason": "does_not_match_rules"}), 202
    observed_at = str(payload.get("rss_observed_at") or "").strip() or None
    tender_id = storage.insert_tender(TenderCandidate(source.key, source.name, title, url, str(payload.get("published_at") or "") or None, summary[:12000], ", ".join(matching_terms(source, match_text)), observed_at))
    if tender_id:
        service.enqueue_tender_notifications(tender_id, suppressed=suppress_notifications)
    return jsonify({"accepted": True, "new": bool(tender_id), "tender_id": tender_id})


if __name__ == "__main__":
    app.run(host=os.getenv("APP_HOST", "127.0.0.1"), port=int(os.getenv("APP_PORT", "8081")), debug=False)
