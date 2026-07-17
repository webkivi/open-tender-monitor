import unittest

from tender_monitor.presentation import telegram_message
from tender_monitor.sources import tender_match_text


class PresentationTests(unittest.TestCase):
    def test_eis_matching_ignores_rss_search_parameters(self):
        summary = "&lt;strong&gt;Искать в прикрепленных файлах: &lt;/strong&gt;1с-битрикс&lt;br&gt;" \
            "&lt;strong&gt;Наименование объекта закупки: &lt;/strong&gt;Вывоз твердых коммунальных отходов"
        self.assertNotIn("1с-битрикс", tender_match_text("eis", "Электронный аукцион", summary))

    def test_eis_message_uses_structured_fields(self):
        message = telegram_message(
            {
                "source_key": "eis",
                "title": "Fallback title",
                "url": "https://example.test/tender",
                "published_at": "Thu, 09 Jul 2026 09:23:02 GMT",
                "matched_terms": "эвм, ЭВМ",
                "summary": "&lt;strong&gt;Наименование объекта закупки:&lt;/strong&gt; Поставка ПО&lt;br/&gt;"
                "&lt;strong&gt;Размещение выполняется по:&lt;/strong&gt; 44-ФЗ&lt;br/&gt;"
                "&lt;strong&gt;Наименование заказчика:&lt;/strong&gt; Заказчик&lt;br/&gt;"
                "&lt;strong&gt;Цена:&lt;/strong&gt; 135 333,33 ₽&lt;br/&gt;"
                "&lt;strong&gt;Срок подачи заявок:&lt;/strong&gt; 17.07.2026 10:00",
            }
        )
        self.assertIn("Поставка ПО", message)
        self.assertIn("Раздел: 44-ФЗ", message)
        self.assertIn("Заказчик: Заказчик", message)
        self.assertIn("Цена: 135 333,33 ₽", message)
        self.assertIn("Ключи: эвм, ЭВМ", message)
