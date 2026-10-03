import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import config
import server

ROOT = Path(__file__).resolve().parent.parent
SECRET = "e2e-secret"


class RecordingClient:
    def __init__(self):
        self.sent = []

    def send_message(self, action):
        self.sent.append(action)

    def get_webhook_info(self):
        return {"url": "https://example.com/webhook/auto"}


class TestEndToEnd(unittest.TestCase):
    """Full path: real configs + real server + fake Bot API client."""

    def test_request_reaches_owner_chat(self):
        sites = {path.stem: config.load_config(path)
                 for path in sorted((ROOT / "bots").glob("*.json"))}
        for cfg in sites.values():
            cfg["owner_chat_id"] = 424242
        clients = {site_id: RecordingClient() for site_id in sites}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(sites, clients, SECRET))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            update = {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 777},
                       "text": "Пётр, 8 (900) 765-43-21"}}
            request = urllib.request.Request(
                f"{base}/webhook/auto?secret={SECRET}", data=json.dumps(update).encode(),
                method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()
        sent = clients["auto"].sent
        self.assertEqual([a.chat_id for a in sent], [777, 424242])
        self.assertIn("79007654321", sent[1].text)
        self.assertIn("Пётр", sent[1].text)


if __name__ == "__main__":
    unittest.main()
