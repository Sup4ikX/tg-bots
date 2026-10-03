import importlib
import os
import sys
import unittest

import server as server_mod
import tg

REQUIRED_ENV = ["BOT_TOKEN_AUTO", "BOT_TOKEN_CAFE", "WEBHOOK_SECRET", "WEBHOOK_BASE"]


class TestRun(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        self.saved_serve = server_mod.serve
        self.saved_client = tg.TelegramClient
        sys.modules.pop("run", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        server_mod.serve = self.saved_serve
        tg.TelegramClient = self.saved_client
        sys.modules.pop("run", None)

    def set_env(self, **extra):
        for key in REQUIRED_ENV:
            os.environ.pop(key, None)
        os.environ.update({"BOT_TOKEN_AUTO": "t1", "BOT_TOKEN_CAFE": "t2",
                           "WEBHOOK_SECRET": "s", "WEBHOOK_BASE": "https://x.onrender.com",
                           "PORT": "8123"})
        os.environ.update(extra)

    def test_missing_token_exits_nonzero(self):
        for key in REQUIRED_ENV:
            os.environ.pop(key, None)
        run = importlib.import_module("run")
        self.assertEqual(run.main(["check-config"]), 1)

    def test_check_config_ok_without_network(self):
        self.set_env()
        run = importlib.import_module("run")
        self.assertEqual(run.main(["check-config"]), 0)

    def test_start_registers_webhooks_and_serves(self):
        self.set_env()
        run = importlib.import_module("run")
        webhooks = []
        served = []

        class FakeClient:
            def __init__(self, token):
                self.token = token

            def get_me(self):
                return {"username": "test_bot"}

            def set_webhook(self, url):
                webhooks.append(url)

        tg.TelegramClient = FakeClient
        server_mod.serve = lambda sites, clients, secret, port: served.append(port)
        self.assertEqual(run.main([]), 0)
        self.assertEqual(len(webhooks), 2)
        self.assertIn("https://x.onrender.com/webhook/auto?secret=s", webhooks)
        self.assertIn("https://x.onrender.com/webhook/cafe?secret=s", webhooks)
        self.assertEqual(served, [8123])


if __name__ == "__main__":
    unittest.main()
