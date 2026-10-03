import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bot
import tg


class StubHandler(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        StubHandler.calls.append((self.path, body))
        if self.path.endswith("/fail"):
            payload = {"ok": False, "description": "chat not found"}
        else:
            payload = {"ok": True, "result": {"url": self.path, "echo": body}}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class TestTelegramClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        StubHandler.calls = []

    def client(self):
        client = tg.TelegramClient("TOKEN")
        client.base_url = self.base + "/botTOKEN"
        return client

    def test_call_posts_json_and_returns_result(self):
        client = self.client()
        result = client.call("getMe", {"a": 1})
        self.assertEqual(StubHandler.calls[0][0], "/botTOKEN/getMe")
        self.assertEqual(StubHandler.calls[0][1], {"a": 1})
        self.assertEqual(result["echo"], {"a": 1})

    def test_api_error_raises_with_description(self):
        client = self.client()
        with self.assertRaises(tg.TelegramError) as ctx:
            client.call("fail")
        self.assertIn("chat not found", str(ctx.exception))

    def test_send_message_sets_html_and_sends_verbatim(self):
        client = self.client()
        client.send_message(bot.Action(42, "Имя: &lt;b&gt;Иван&lt;/b&gt;"))
        payload = StubHandler.calls[0][1]
        self.assertEqual(payload["chat_id"], 42)
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["text"], "Имя: &lt;b&gt;Иван&lt;/b&gt;")

    def test_send_message_includes_reply_markup(self):
        client = self.client()
        markup = {"inline_keyboard": [[{"text": "a", "callback_data": "b"}]]}
        client.send_message(bot.Action(42, "text", markup))
        self.assertEqual(StubHandler.calls[0][1]["reply_markup"], markup)

    def test_transport_failure_raises_telegram_error(self):
        client = tg.TelegramClient("TOKEN")
        client.base_url = "http://127.0.0.1:1/botTOKEN"
        with self.assertRaises(tg.TelegramError):
            client.call("getMe")


if __name__ == "__main__":
    unittest.main()
