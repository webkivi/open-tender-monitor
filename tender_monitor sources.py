from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import SourceConfig, TenderCandidate
from .presentation import eis_fields


def load_sources(path: Path) -> list[SourceConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SourceConfig(**item) for item in payload["sources"]]


def save_sources(path: Path, sources: list[SourceConfig]) -> None:
    payload = {"sources": [source.__dict__ for source in sources]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PublicPageAdapter:
    """Extracts candidate procedure links from a user-configured public search page."""

    user_agent = "OpenTenderMonitor/0.1 (+local monitoring)"

    def fetch(self, source: SourceConfig) -> list[TenderCandidate]:
        if not source.search_url.strip():
            return []
        request = urllib.request.Request(source.search_url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if error.code in {403, 429}:
                raise SourceAccessError("rate_limited", f"HTTP {error.code}") from error
            raise SourceAccessError("http_error", f"HTTP {error.code}") from error
        except TimeoutError as error:
            raise SourceAccessError("timeout", "Source response timed out") from error
        if any(marker in html.casefold() for marker in ("captcha", "recaptcha", "hcaptcha", "проверка безопасности")):
            raise SourceAccessError("challenge", "CAPTCHA or an access challenge was detected")
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[TenderCandidate] = []
        seen: set[str] = set()
        for link in soup.select("a[href]"):
            title = " ".join(link.get_text(" ", strip=True).split())
            url = urljoin(source.search_url, link["href"])
            if len(title) < 16 or not url.startswith(("http://", "https://")) or url in seen:
                continue
            surrounding = " ".join(link.parent.get_text(" ", strip=True).split()) if link.parent else title
            if not matches(source, title + " " + surrounding):
                continue
            seen.add(url)
            candidates.append(TenderCandidate(source.key, source.name, title[:500], url, summary=surrounding[:1000], matched_terms=", ".join(matching_terms(source, title + " " + surrounding))))
        return candidates[:100]


class SourceAccessError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def matches(source: SourceConfig, text: str) -> bool:
    return bool(matching_terms(source, text))


def matching_terms(source: SourceConfig, text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).casefold()
    includes = [(item, item.casefold().strip()) for item in source.include_terms if item.strip()]
    excludes = [item.casefold().strip() for item in source.exclude_terms if item.strip()]
    if any(item in normalized for item in excludes):
        return []
    return [original for original, normalized_term in includes if normalized_term in normalized]


def tender_match_text(source_key: str, title: str, summary: str) -> str:
    if source_key != "eis":
        return title + " " + summary
    fields = eis_fields(summary)
    return " ".join((title, fields.get("Наименование объекта закупки", "")))
