from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    key: str
    name: str
    enabled: bool
    search_url: str
    poll_seconds: int
    include_terms: list[str]
    exclude_terms: list[str]
    rss_url: str = ""


@dataclass(frozen=True)
class TenderCandidate:
    source_key: str
    source_name: str
    title: str
    url: str
    published_at: str | None = None
    summary: str = ""
    matched_terms: str = ""
    rss_observed_at: str | None = None
