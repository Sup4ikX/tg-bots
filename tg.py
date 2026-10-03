"""Thin Telegram Bot API client over urllib."""
import json
import urllib.error
import urllib.request


class TelegramError(Exception):
    """The API rejected the call or the transport failed."""


class TelegramClient:
    """JSON client for one bot token; base_url is overridable for tests."""

    def __init__(self, token, timeout=10):
        self.token = token
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{token}"

    def call(self, method, payload=None):
        """POST JSON to a Bot API method and return its `result`."""
        data = json.dumps(payload or {}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/{method}", data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise TelegramError(f"{method}: {e}") from e
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'unknown error')}")
        return body.get("result")

    def send_message(self, action):
        """Send one bot.Action; text is already HTML-escaped by bot.py."""
        payload = {"chat_id": action.chat_id, "text": action.text, "parse_mode": "HTML"}
        if action.reply_markup:
            payload["reply_markup"] = action.reply_markup
        return self.call("sendMessage", payload)

    def set_webhook(self, url):
        """Point Telegram at our webhook endpoint."""
        return self.call("setWebhook", {"url": url})

    def get_me(self):
        """Return this bot's identity (logged at startup)."""
        return self.call("getMe")

    def get_webhook_info(self):
        """Return webhook status (served by /webhook-status)."""
        return self.call("getWebhookInfo")
