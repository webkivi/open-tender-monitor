from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup, Tag


def telegram_message(tender: dict) -> str:
    if tender["source_key"] != "eis":
        return f"Найдена закупка\n\n{tender['title']}\n\nСсылка: {tender['url']}"

    fields = eis_fields(tender.get("summary", ""))
    name = first_value(fields, "Наименование объекта закупки") or tender["title"]
    section = first_value(fields, "Размещение выполняется по") or "ЕИС"
    customer = first_value(fields, "Наименование заказчика")
    price = first_value(fields, "Начальная (максимальная) цена контракта", "Начальная цена", "Цена")
    published = first_value(fields, "Дата и время размещения", "Дата размещения", "Размещено") or format_rss_date(tender.get("published_at"))
    deadline = first_value(fields, "Дата и время окончания подачи заявок", "Окончание подачи заявок", "Срок подачи заявок")

    lines = ["Найдена закупка: 1", "", f"1. {name}", f"Раздел: {section}", f"Ссылка: {tender['url']}"]
    if customer:
        lines.append(f"Заказчик: {customer}")
    lines.append(f"Тип: {section}")
    if price:
        lines.append(f"Цена: {price}")
    if published:
        lines.append(f"Опубликовано: {published}")
    if deadline:
        lines.append(f"Срок подачи: {deadline}")
    if tender.get("matched_terms"):
        lines.append(f"Ключи: {tender['matched_terms']}")
    return "\n".join(lines)


def eis_fields(summary: str) -> dict[str, str]:
    soup = BeautifulSoup(html.unescape(summary), "html.parser")
    fields: dict[str, str] = {}
    for label_tag in soup.find_all("strong"):
        label = clean(label_tag.get_text(" ", strip=True)).rstrip(":")
        if not label or label in {"Найденный результат", "№"}:
            continue
        values: list[str] = []
        for sibling in label_tag.next_siblings:
            if isinstance(sibling, Tag) and sibling.name == "strong":
                break
            value = clean(sibling.get_text(" ", strip=True) if isinstance(sibling, Tag) else str(sibling))
            if value:
                values.append(value)
        if values:
            fields[label] = clean(" ".join(values))
    return fields


def first_value(fields: dict[str, str], *names: str) -> str:
    for name in names:
        for key, value in fields.items():
            if key.casefold() == name.casefold() and value:
                return value
    return ""


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def format_rss_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%d.%m.%Y %H:%M UTC")
    except (TypeError, ValueError):
        return value
