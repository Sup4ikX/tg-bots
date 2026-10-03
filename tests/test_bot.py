import unittest

import bot


def make_cfg(**over):
    cfg = {
        "id": "auto",
        "name": "АвтоПрофи",
        "tagline": "ТО и ремонт в Москве",
        "phone": "+7 900 111-22-33",
        "address": "Москва, ул. Электрозаводская, 21к2",
        "hours": "пн–сб 9:00–20:00",
        "services": [
            {"name": "Замена масла", "price": "от 1 200 ₽"},
            {"name": "ТО-1", "price": "от 4 500 ₽"},
        ],
        "owner_chat_id": None,
        "landing_url": "https://sup4ikx.github.io/landing-pages/auto/",
        "welcome": "Рады видеть! Выберите, что вам нужно.",
    }
    cfg.update(over)
    return cfg


def message(text=None, chat_id=555):
    msg = {"message_id": 1, "chat": {"id": chat_id}}
    if text is not None:
        msg["text"] = text
    return {"update_id": 1, "message": msg}


def callback(data, chat_id=555):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "1",
            "from": {"id": chat_id},
            "message": {"message_id": 1, "chat": {"id": chat_id}},
            "data": data,
        },
    }


class TestNormalizePhone(unittest.TestCase):
    def test_plus_seven(self):
        self.assertEqual(bot.normalize_phone("+7 900 111-22-33"), "79001112233")

    def test_eight_prefix_with_parens(self):
        self.assertEqual(bot.normalize_phone("8 (900) 111-22-33"), "79001112233")

    def test_ten_digits(self):
        self.assertEqual(bot.normalize_phone("900 111-22-33"), "79001112233")

    def test_garbage(self):
        self.assertEqual(bot.normalize_phone("позвоните завтра"), "")


class TestParseRequest(unittest.TestCase):
    def test_name_then_phone(self):
        self.assertEqual(bot.parse_request("Иван, +7 900 123-45-67"), ("Иван", "79001234567"))

    def test_phone_first_with_comment(self):
        name, phone = bot.parse_request("+79001234567 Иван переборол двигатель")
        self.assertEqual(phone, "79001234567")
        self.assertEqual(name, "Иван переборол двигатель")

    def test_no_phone_returns_none(self):
        self.assertIsNone(bot.parse_request("хочу записаться"))

    def test_html_is_kept_raw_for_escaping_at_composition(self):
        name, phone = bot.parse_request("<b>Иван</b> +7 900 123-45-67")
        self.assertEqual(name, "<b>Иван</b>")
        self.assertEqual(phone, "79001234567")


class TestStart(unittest.TestCase):
    def test_start_sends_one_keyboard_message(self):
        actions = bot.handle_update(message("/start"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        self.assertIn("АвтоПрофи", actions[0].text)
        labels = [b["text"] for row in actions[0].reply_markup["inline_keyboard"] for b in row]
        self.assertEqual(labels, ["Услуги и цены", "Оставить заявку", "Позвонить"])

    def test_deep_link_marks_landing_source(self):
        actions = bot.handle_update(message("/start landing_cafe"), make_cfg(), None)
        self.assertEqual(bot.get_source(555), "с лендинга")
        self.assertEqual(len(actions), 1)

    def test_plain_start_marks_direct_source(self):
        bot.handle_update(message("/start"), make_cfg(), None)
        self.assertEqual(bot.get_source(555), "напрямую")

    def test_myid_replies_with_chat_id(self):
        actions = bot.handle_update(message("/myid"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        self.assertIn("555", actions[0].text)


class TestCallbacks(unittest.TestCase):
    def test_prices(self):
        actions = bot.handle_update(callback("prices"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        self.assertIn("Замена масла", actions[0].text)
        self.assertIn("1 200 ₽", actions[0].text)

    def test_phone_button_links_to_digits(self):
        actions = bot.handle_update(callback("phone"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        url = actions[0].reply_markup["inline_keyboard"][0][0]["url"]
        self.assertEqual(url, "tel:79001112233")

    def test_request_button_asks_for_name_and_phone(self):
        actions = bot.handle_update(callback("req|landing_auto"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        self.assertIn("имя и телефон", actions[0].text)
        self.assertEqual(bot.get_source(555), "с лендинга")

    def test_unknown_callback_falls_back_to_menu(self):
        actions = bot.handle_update(callback("wat"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        self.assertIn("АвтоПрофи", actions[0].text)


class TestRequestFlow(unittest.TestCase):
    def test_valid_request_confirms_and_forwards(self):
        actions = bot.handle_update(message("Иван, +7 900 123-45-67"), make_cfg(), 999)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].chat_id, 555)
        self.assertIn("Заявка принята", actions[0].text)
        self.assertEqual(actions[1].chat_id, 999)
        self.assertIn("Иван", actions[1].text)
        self.assertIn("79001234567", actions[1].text)
        self.assertEqual(actions[1].reply_markup["inline_keyboard"][0][0]["url"], "tel:79001234567")

    def test_forward_contains_source_marker(self):
        bot.mark_source(555, "с лендинга")
        actions = bot.handle_update(message("Иван, +7 900 123-45-67"), make_cfg(), 999)
        self.assertIn("с лендинга", actions[1].text)

    def test_request_without_phone_asks_again(self):
        actions = bot.handle_update(message("хочу записаться"), make_cfg(), 999)
        self.assertEqual(len(actions), 1)
        self.assertIn("не нашёл", actions[0].text.lower())

    def test_request_without_owner_is_logged_to_client(self):
        actions = bot.handle_update(message("Иван, +7 900 123-45-67"), make_cfg(), None)
        self.assertEqual(len(actions), 1)
        self.assertIn("Заявка принята", actions[0].text)
        self.assertIn("Иван · 79001234567", actions[0].text)

    def test_forwarded_html_is_escaped(self):
        actions = bot.handle_update(message("<b>Иван</b> +7 900 123-45-67"), make_cfg(), 999)
        self.assertNotIn("<b>", actions[1].text)
        self.assertIn("&lt;b&gt;", actions[1].text)

    def test_menu_escapes_config_values(self):
        actions = bot.handle_update(message("/start"), make_cfg(name="<b>Кафе</b>"), None)
        self.assertIn("&lt;b&gt;Кафе&lt;/b&gt;", actions[0].text)


class TestEdgeCases(unittest.TestCase):
    def test_update_without_text_or_callback(self):
        self.assertEqual(bot.handle_update(message(), make_cfg(), 999), [])

    def test_update_without_message_or_callback(self):
        self.assertEqual(bot.handle_update({"update_id": 3}, make_cfg(), 999), [])

    def test_unknown_command_shows_menu(self):
        actions = bot.handle_update(message("/wat"), make_cfg(), 999)
        self.assertEqual(len(actions), 1)
        self.assertIn("АвтоПрофи", actions[0].text)


if __name__ == "__main__":
    unittest.main()
