"""HTTP layer: Telegram webhook, health check, webhook status."""
import json
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bot

log = logging.getLogger("tg-bots")


def make_handler(sites, clients, secret):
    """Build a request handler class bound to the given sites, clients and secret."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "tg-bots/1.0"

        def _respond(self, code, payload):
            raw = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/health":
                self._respond(200, {"status": "ok", "bots": sorted(sites)})
            elif path == "/webhook-status":
                info = {}
                for site_id, client in clients.items():
                    try:
                        info[site_id] = client.get_webhook_info()
                    except Exception as e:  # noqa: BLE001 - status must never fail
                        info[site_id] = {"error": str(e)}
                self._respond(200, info)
            else:
                self._respond(404, {"error": "not found"})

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) != 2 or parts[0] != "webhook":
                self._respond(404, {"error": "not found"})
                return
            site_id = parts[1]
            if site_id not in sites:
                self._respond(404, {"error": f"unknown bot {site_id}"})
                return
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("secret", [""])[0] != secret:
                log.warning("webhook for %s rejected: bad secret", site_id)
                self._respond(403, {"error": "forbidden"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                update = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid json"})
                return
            if not isinstance(update, dict):
                self._respond(400, {"error": "update must be an object"})
                return
            cfg = sites[site_id]
            actions = bot.handle_update(update, cfg, cfg.get("owner_chat_id"))
            for action in actions:
                try:
                    clients[site_id].send_message(action)
                except Exception:  # noqa: BLE001 - answer 200 so Telegram stops retrying
                    log.exception("send failed for %s", site_id)
            self._respond(200, {"ok": True, "actions": len(actions)})

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def serve(sites, clients, secret, port):
    """Run the HTTP server until interrupted."""
    handler = make_handler(sites, clients, secret)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    log.info("listening on 0.0.0.0:%d for bots: %s", port, ", ".join(sorted(sites)))
    httpd.serve_forever()
