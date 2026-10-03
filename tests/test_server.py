import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parent.parent
SECRET = "s3cret"


def make_cfg(**over):
    cfg = {
        "id": "auto",
        "name": "АвтоПрофи",
        "tagline": "ТО и ремонт",
        "phone": "+7 900 111-22-33",
        "address": "Москва",
        "hours": "пн–сб 9:00–20:00",
        "services": [{"name": "Замена масла", "price": "от 1 200 ₽"}],
        "owner_chat_id": 999,
        "landing_url": "https://example.com/",
        "welcome": "Рады видеть!",
    }
    cfg.update(over)
    return cfg


class FakeClient:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_message(self, action):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(action)

    def get_webhook_info(self):
        return {"url": "https://example.com/webhook/auto", "pending_update_count": 0}


class TestServer(unittest.TestCase):
    def setUp(self):
        self.sites = {"auto": make_cfg()}
        self.clients = {"auto": FakeClient()}
        handler = server.make_handler(self.sites, self.clients, SECRET)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def post(self, path, body=None, secret=SECRET, raw=None):
        url = f"{self.base}{path}"
        if secret is not None:
            url += f"?secret={secret}"
        data = raw if raw is not None else json.dumps(body or {}).encode()
        request = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
        return self._send(request)

    def get(self, path):
        return self._send(urllib.request.Request(f"{self.base}{path}"))

    @staticmethod
    def _send(request):
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_health_returns_200(self):
        status, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertIn("auto", body.decode())

    def test_unknown_path_returns_404(self):
        self.assertEqual(self.get("/nope")[0], 404)

    def test_webhook_without_secret_returns_403(self):
        self.assertEqual(self.post("/webhook/auto", {"update_id": 1}, secret=None)[0], 403)

    def test_webhook_with_wrong_secret_returns_403(self):
        self.assertEqual(self.post("/webhook/auto", {"update_id": 1}, secret="nope")[0], 403)

    def test_webhook_unknown_bot_returns_404(self):
        self.assertEqual(self.post("/webhook/cafe", {"update_id": 1})[0], 404)

    def test_start_update_sends_message_and_returns_200(self):
        status, body = self.post("/webhook/auto", {"update_id": 1, "message": {
            "message_id": 1, "chat": {"id": 555}, "text": "/start"}})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.clients["auto"].sent), 1)
        self.assertIn("АвтоПрофи", self.clients["auto"].sent[0].text)
        self.assertIn('"actions": 1', body.decode())

    def test_malformed_json_returns_400(self):
        self.assertEqual(self.post("/webhook/auto", raw=b"{not json")[0], 400)

    def test_non_object_update_returns_400(self):
        self.assertEqual(self.post("/webhook/auto", raw=b"[1,2]")[0], 400)

    def test_request_flow_forwards_to_owner(self):
        status, _ = self.post("/webhook/auto", {"update_id": 1, "message": {
            "message_id": 1, "chat": {"id": 555}, "text": "Иван, +7 900 123-45-67"}})
        self.assertEqual(status, 200)
        self.assertEqual([a.chat_id for a in self.clients["auto"].sent], [555, 999])

    def test_api_failure_still_returns_200(self):
        self.clients["auto"] = FakeClient(fail=True)
        status, _ = self.post("/webhook/auto", {"update_id": 1, "message": {
            "message_id": 1, "chat": {"id": 555}, "text": "/start"}})
        self.assertEqual(status, 200)

    def test_webhook_status_endpoint_reports_bots(self):
        status, body = self.get("/webhook-status")
        self.assertEqual(status, 200)
        self.assertIn("auto", body.decode())


if __name__ == "__main__":
    unittest.main()
