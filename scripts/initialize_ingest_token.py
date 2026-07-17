"""Create a local shared token for browser-extension to dashboard delivery."""

import secrets
from pathlib import Path

from dotenv import dotenv_values

path = Path(__file__).resolve().parents[1] / ".env"
values = dotenv_values(path)
if values.get("INGEST_TOKEN"):
    print("Ingest token is already configured.")
else:
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.append(f"INGEST_TOKEN={secrets.token_urlsafe(32)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Ingest token configured locally. It was not displayed.")
