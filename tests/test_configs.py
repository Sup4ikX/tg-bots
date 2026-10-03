import json
import tempfile
import unittest
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent.parent


def make_cfg(**over):
    cfg = {
        "id": "auto",
        "name": "АвтоПрофи",
        "tagline": "ТО и ремонт",
        "phone": "+7 900 111-22-33",
        "address": "Москва",
        "hours": "пн–сб 9:00–20:00",
        "services": [{"name": "Замена масла", "price": "от 1 200 ₽"}],
        "owner_chat_id": None,
        "landing_url": "https://example.com/",
        "welcome": "Рады видеть!",
    }
    cfg.update(over)
    return cfg


class TestValidate(unittest.TestCase):
    def check(self, cfg, *expected):
        with self.assertRaises(config.ConfigError) as ctx:
            config.validate(cfg, "bots/demo.json")
        message = str(ctx.exception)
        self.assertIn("bots/demo.json", message)
        for fragment in expected:
            self.assertIn(fragment, message)

    def test_valid_config_passes(self):
        config.validate(make_cfg(), "bots/demo.json")

    def test_missing_name(self):
        cfg = make_cfg()
        del cfg["name"]
        self.check(cfg, "отсутствует поле", "name")

    def test_bad_phone_digits(self):
        self.check(make_cfg(phone="123"), "11 цифр")

    def test_phone_must_be_string(self):
        self.check(make_cfg(phone=79001112233), "11 цифр")

    def test_services_entry_without_price(self):
        self.check(make_cfg(services=[{"name": "Масло"}]), "services[0].price")

    def test_services_must_be_non_empty_list(self):
        self.check(make_cfg(services={}), "services")

    def test_owner_chat_id_must_be_int_or_null(self):
        self.check(make_cfg(owner_chat_id="nine"), "owner_chat_id")

    def test_landing_url_must_be_https(self):
        self.check(make_cfg(landing_url="http://example.com/"), "landing_url")

    def test_load_config_reads_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.json"
            path.write_text(json.dumps(make_cfg(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(config.load_config(path)["name"], "АвтоПрофи")

    def test_load_config_reports_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.json"
            path.write_text("{oops", encoding="utf-8")
            with self.assertRaises(config.ConfigError) as ctx:
                config.load_config(path)
            self.assertIn("невалидный JSON", str(ctx.exception))


class TestRealConfigs(unittest.TestCase):
    def test_shipped_configs_are_valid(self):
        files = sorted((ROOT / "bots").glob("*.json"))
        self.assertEqual(len(files), 2)
        for path in files:
            config.load_config(path)

    def test_shipped_configs_have_prices_and_owner_placeholders(self):
        for site in ("auto", "cafe"):
            cfg = config.load_config(ROOT / "bots" / f"{site}.json")
            self.assertEqual(cfg["id"], site)
            self.assertIn("₽", " ".join(s["price"] for s in cfg["services"]))
            self.assertIsNone(cfg["owner_chat_id"])


if __name__ == "__main__":
    unittest.main()
