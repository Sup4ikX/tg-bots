# Telegram Bots (upsell case) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two stateless Telegram bots (auto service, cafe) that answer `/start`, show services and prices, collect a name + phone from free text, and forward the request to the owner's Telegram chat with a source marker — deployed on a free Render web service via webhook.

**Architecture:** Standard-library Python only. `bot.py` holds pure logic (`handle_update(update, cfg, owner_chat_id) -> list[Action]`, request parser, phone normalization) and performs no I/O, so every behavior is testable offline. `server.py` exposes `POST /webhook/<bot_id>` (secret-checked) and `GET /health` via `ThreadingHTTPServer`; it executes actions through `tg.py`, a thin Bot API client over `urllib`. Per-niche content lives in `bots/*.json`, validated with the same strict message format as sub-project 1. A GitHub Actions workflow pings `/health` every 10 minutes so the free Render service never idles out.

**Tech Stack:** Python 3 (standard library only, zero pip dependencies), `unittest`, `urllib.request`, `http.server`, GitHub Actions (`keepalive.yml`), Render free web service.

**Spec:** `docs/superpowers/specs/2026-10-03-telegram-bots-design.md`

## Global Constraints

- Python standard library only. No pip dependencies, no `requirements.txt`.
- Bot tokens, webhook secret, and `PORT` come from environment variables only. No token, no `.env`, no chat id secret in git; `.env` is gitignored.
- Config error format is exactly `<path>: отсутствует поле <name>`; on any config error the process exits non-zero and nothing is deployed or served.
- The bot is stateless: no dialogue state machine. A free-text message is always parsed as a request; only the source marker (`с лендинга` / `напрямую`) is kept in memory (`chat_id -> source`) and degrades to `напрямую` after a restart.
- Phone normalization: any Russian format normalizes to 11 digits starting with `7` (rules identical to `generate.digits` in `~/Work/landing-pages`).
- HTML escaping happens in exactly one place: `bot.py` escapes every config and user value with `html.escape(..., quote=True)` while composing message text. `tg.send_message` always sends `parse_mode="HTML"` and passes `action.text` verbatim — no double escaping.
- Tests run offline: no external network, no tokens, no Telegram. Local `127.0.0.1` stub servers are allowed.
- UI language: Russian only.
- Deploy artifacts (`dist/`, `.env`) are never committed.

## Review Focus

Five input classes the spec implies but no happy-path task covers; each gets a pinning test in the owning task:

1. Update payload arrives with no `callback_query` and no text (e.g. a stale `message_id`) — must produce zero actions, never a crash.
2. Phone typed in text with `8` prefix or grouped digits (`8 (900) 111-22-33`) — must normalize to `79001112233`.
3. Config `services` entry with an empty price — validation must reject the config, not send a blank line to the user.
4. Webhook request with the correct secret but a malformed JSON body — must return 400, not 500.
5. Request whose text contains HTML (`<b>Иван</b>`) — must arrive escaped in the forwarded message, not rendered as markup.

## File Structure

| File | Responsibility |
|---|---|
| `bot.py` | Pure logic: `Action`, phone normalization, request parsing, message composition, `handle_update` |
| `tg.py` | Bot API client over `urllib`: `send_message`, `set_webhook`, `get_me`, `get_webhook_info` |
| `config.py` | Per-niche config loading and validation |
| `server.py` | `ThreadingHTTPServer`, routing, secret check, action execution |
| `run.py` | Entry point: load configs, read env, register webhooks, serve (and `check-config` mode) |
| `bots/auto.json`, `bots/cafe.json` | Per-niche config: name, tagline, phone, address, hours, services (name + price), owner_chat_id, landing_url, welcome |
| `tests/test_bot.py` | Action logic, parsing, escaping, edge cases (Review Focus 1, 2, 5) |
| `tests/test_tg.py` | `tg.py` request/response handling against a local stub HTTP server |
| `tests/test_configs.py` | Config validation (Review Focus 3) and shipped-config tests |
| `tests/test_server.py` | Endpoints, secret check, routing, malformed body (Review Focus 4) |
| `tests/test_run.py` | Env handling, webhook registration, entry point |
| `.github/workflows/keepalive.yml` | Cron ping to the deployed `/health` |
| `README.md` | Local run, BotFather setup, Render deploy, `owner_chat_id` wiring, fallback without a card |

---

### Task 1: Bot core — actions, phone, parser, message composition

**Files:**
- Create: `bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces (used by Tasks 3, 4, 5):
  - `bot.Action(chat_id: int, text: str, reply_markup: dict | None = None)`.
  - `bot.SOURCE_MEMORY: dict[int, str]`, `bot.mark_source(chat_id: int, source: str) -> None`, `bot.get_source(chat_id: int) -> str`.
  - `bot.normalize_phone(raw: str) -> str` — 11 digits starting with `7`, `""` if impossible.
  - `bot.parse_request(text: str) -> tuple[str, str] | None` — `(name, phone)`, `None` when no phone.
  - `bot.menu_keyboard() -> dict`, `bot.phone_button(phone: str) -> dict`.
  - `bot.handle_update(update: dict, cfg: dict, owner_chat_id: int | None) -> list[Action]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_bot.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot'`

- [ ] **Step 3: Write `bot.py`**

```python
"""Pure bot logic: actions, phone normalization, request parsing, message composition."""
import html
import re
from string import Template

SOURCE_MEMORY = {}

MENU_BUTTONS = [("prices", "Услуги и цены"), ("req", "Оставить заявку"), ("phone", "Позвонить")]
REQUEST_PROMPT = ("Напишите имя и телефон одним сообщением, например:\n"
                  "Иван, +7 900 123-45-67")
REPEAT_PROMPT = ("Не нашёл номер телефона. Напишите имя и телефон одним сообщением, "
                 "например: Иван, +7 900 123-45-67")

PHONE_RE = re.compile(r"(?:\+7|8|7)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}")


class Action:
    """One outgoing message: target chat, HTML text, optional inline keyboard."""

    def __init__(self, chat_id, text, reply_markup=None):
        self.chat_id = chat_id
        self.text = text
        self.reply_markup = reply_markup


def esc(value):
    """Escape a config or user value for Telegram HTML messages (single escape point)."""
    return html.escape(str(value), quote=True)


def mark_source(chat_id, source):
    """Remember where this conversation came from; best-effort, lost on restart."""
    SOURCE_MEMORY[chat_id] = source


def get_source(chat_id):
    """Source marker for a chat, defaulting to a direct visit."""
    return SOURCE_MEMORY.get(chat_id, "напрямую")


def normalize_phone(raw):
    """Normalize a Russian phone to 11 digits starting with 7, or '' if impossible."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return digits
    return ""


def parse_request(text):
    """Split free text into (name, 11-digit phone); None when no phone is present."""
    match = PHONE_RE.search(text)
    if not match:
        return None
    phone = normalize_phone(match.group(0))
    if not phone:
        return None
    name = (text[:match.start()] + " " + text[match.end():]).strip()
    name = re.sub(r"[\s,;:–—-]+$", "", name).strip(" ,;:-")
    return (name, phone)


def menu_keyboard():
    """Inline keyboard for the three main actions."""
    return {"inline_keyboard": [[{"text": label, "callback_data": data}]
                                for data, label in MENU_BUTTONS]}


def phone_button(phone):
    """Inline keyboard with a single tappable call button."""
    return {"inline_keyboard": [[{"text": "Позвонить", "url": "tel:" + phone}]]}


def menu_message(cfg, chat_id):
    """Greeting with the niche name and the three buttons."""
    text = Template("${name}\n${tagline}\n\n${welcome}").substitute(
        name=esc(cfg["name"]), tagline=esc(cfg["tagline"]), welcome=esc(cfg["welcome"]))
    return Action(chat_id, text, menu_keyboard())


def prices_message(cfg, chat_id):
    """Plain-text list of services with prices and a link to the landing page."""
    lines = [esc(s["name"]) + " — " + esc(s["price"]) for s in cfg["services"]]
    return Action(chat_id, "Услуги и цены:\n\n" + "\n".join(lines)
                  + "\n\n" + esc(cfg["landing_url"]))


def phone_message(cfg, chat_id):
    """Message with the phone number and a tappable call button."""
    return Action(chat_id, "Позвоните: " + esc(cfg["phone"]),
                  phone_button(normalize_phone(cfg["phone"])))


def owner_forward(cfg, chat_id, name, phone, source):
    """Message to the owner describing a validated request."""
    text = Template("Новая заявка\n\nКлиент: ${name}\nТелефон: ${phone}\n"
                    "Источник: ${source}\nЧат клиента: ${chat_id}").substitute(
        name=esc(name), phone=esc(phone), source=esc(source), chat_id=esc(chat_id))
    return Action(cfg["owner_chat_id"], text, phone_button(phone))


def handle_update(update, cfg, owner_chat_id):
    """Turn one Telegram update into the list of actions to perform. No I/O."""
    if "callback_query" in update:
        query = update["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        data = query.get("data", "")
        if data == "prices":
            return [prices_message(cfg, chat_id)]
        if data == "phone":
            return [phone_message(cfg, chat_id)]
        if data.startswith("req"):
            if "|" in data:
                mark_source(chat_id, "с лендинга")
            return [Action(chat_id, REQUEST_PROMPT)]
        return [menu_message(cfg, chat_id)]

    message = update.get("message")
    if not message or "text" not in message:
        return []
    chat_id = message["chat"]["id"]
    text = message["text"].strip()
    head = text.split(maxsplit=1)[0] if text else ""

    if head == "/start":
        mark_source(chat_id, "с лендинга" if len(text.split(maxsplit=1)) > 1 else "напрямую")
        return [menu_message(cfg, chat_id)]
    if head == "/myid":
        return [Action(chat_id, f"Ваш chat_id: {chat_id}")]
    if head.startswith("/"):
        return [menu_message(cfg, chat_id)]

    parsed = parse_request(text)
    if parsed is None:
        return [Action(chat_id, REPEAT_PROMPT)]
    name, phone = parsed
    if owner_chat_id is not None:
        return [Action(chat_id, "Заявка принята! Мы свяжемся с вами: " + esc(cfg["hours"])),
                owner_forward({**cfg, "owner_chat_id": owner_chat_id}, chat_id,
                              name, phone, get_source(chat_id))]
    return [Action(chat_id, "Заявка принята! " + esc(cfg["name"]) + " свяжется с вами: "
                  + esc(cfg["hours"]) + "\n[owner_chat_id не задан] " + esc(name)
                  + " · " + esc(phone))]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 25 tests

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot.py
git commit -m "feat: stateless bot core with request parsing and source tracking"
```

---

### Task 2: Bot API client

**Files:**
- Create: `tg.py`
- Test: `tests/test_tg.py`

**Interfaces:**
- Consumes: `bot.Action` (Task 1).
- Produces (used by Task 5):
  - `tg.TelegramError(Exception)`.
  - `tg.TelegramClient(token: str, timeout: int = 10)` with a mutable `base_url`
    attribute (default `https://api.telegram.org/bot<token>`), and:
    - `.call(method: str, payload: dict | None = None) -> dict` — POSTs JSON, returns the API's `result`, raises `TelegramError` with the API `description` when `ok` is false or the transport fails.
    - `.send_message(action: bot.Action) -> dict` — always sets `parse_mode="HTML"`, sends `action.text` verbatim, includes `reply_markup` when present.
    - `.set_webhook(url: str) -> dict`, `.get_me() -> dict`, `.get_webhook_info() -> dict`.

- [ ] **Step 1: Write the failing tests** — `tests/test_tg.py`:

```python
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
        client = self.client("")
        result = client.call("getMe", {"a": 1})
        self.assertEqual(StubHandler.calls[0][0], "/botTOKEN/getMe")
        self.assertEqual(StubHandler.calls[0][1], {"a": 1})
        self.assertEqual(result["echo"], {"a": 1})

    def test_api_error_raises_with_description(self):
        client = self.client("")
        with self.assertRaises(tg.TelegramError) as ctx:
            client.call("fail")
        self.assertIn("chat not found", str(ctx.exception))

    def test_send_message_sets_html_and_sends_verbatim(self):
        client = self.client("")
        client.send_message(bot.Action(42, "Имя: &lt;b&gt;Иван&lt;/b&gt;"))
        payload = StubHandler.calls[0][1]
        self.assertEqual(payload["chat_id"], 42)
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["text"], "Имя: &lt;b&gt;Иван&lt;/b&gt;")

    def test_send_message_includes_reply_markup(self):
        client = self.client("")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tg'`

- [ ] **Step 3: Write `tg.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 30 tests

- [ ] **Step 5: Commit**

```bash
git add tg.py tests/test_tg.py
git commit -m "feat: telegram bot api client with html send and error wrapping"
```

---

### Task 3: Configs and validation

**Files:**
- Create: `config.py`, `bots/auto.json`, `bots/cafe.json`
- Test: `tests/test_configs.py`

**Interfaces:**
- Consumes: `bot.normalize_phone` (Task 1).
- Produces (used by Task 5):
  - `config.ConfigError(Exception)`.
  - `config.REQUIRED: tuple[str, ...]` — `("id", "name", "tagline", "phone", "address", "hours", "services", "landing_url", "welcome")`.
  - `config.validate(cfg: dict, path: str) -> None`.
  - `config.load_config(path) -> dict`.

- [ ] **Step 1: Write the failing tests** — `tests/test_configs.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write `config.py`**

```python
"""Per-niche bot config loading and validation."""
import json
from pathlib import Path

import bot

REQUIRED = ("id", "name", "tagline", "phone", "address", "hours",
            "services", "landing_url", "welcome")


class ConfigError(Exception):
    """A config problem with a user-facing message: <path>: <problem>."""


def _check_services(path, services):
    if not isinstance(services, list) or not services:
        raise ConfigError(f"{path}: поле services должно быть непустым списком")
    for i, item in enumerate(services):
        if not isinstance(item, dict):
            raise ConfigError(f"{path}: services[{i}] должен быть объектом")
        for key in ("name", "price"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{path}: отсутствует поле services[{i}].{key}")


def validate(cfg, path):
    """Raise ConfigError if the config cannot drive the bot correctly."""
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: конфиг должен быть JSON-объектом")
    for field in REQUIRED:
        value = cfg.get(field)
        if value is None or (isinstance(value, (str, list, dict)) and not value):
            raise ConfigError(f"{path}: отсутствует поле {field}")
    if not isinstance(cfg["phone"], str) or bot.normalize_phone(cfg["phone"]) == "":
        raise ConfigError(f"{path}: поле phone должно содержать 11 цифр с кодом страны")
    _check_services(path, cfg["services"])
    owner = cfg.get("owner_chat_id")
    if owner is not None and (isinstance(owner, bool) or not isinstance(owner, int)):
        raise ConfigError(f"{path}: поле owner_chat_id должно быть числом или null")
    if not str(cfg["landing_url"]).startswith("https://"):
        raise ConfigError(f"{path}: поле landing_url должно начинаться с https://")


def load_config(path):
    """Read and validate one bot config."""
    path = Path(path)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: невалидный JSON — {e}") from e
    validate(cfg, str(path).replace("\\", "/"))
    return cfg
```

- [ ] **Step 4: Write `bots/auto.json`**

```json
{
  "id": "auto",
  "name": "АвтоПрофи",
  "tagline": "ТО и ремонт в Москве без лишнего ожидания",
  "phone": "+7 900 111-22-33",
  "address": "Москва, ул. Электрозаводская, 21к2",
  "hours": "пн–сб 9:00–20:00, вс — выходной",
  "services": [
    { "name": "Замена масла", "price": "от 1 200 ₽" },
    { "name": "ТО-1", "price": "от 4 500 ₽" },
    { "name": "Диагностика подвески", "price": "800 ₽" },
    { "name": "Ремонт тормозов", "price": "от 2 500 ₽" },
    { "name": "Шиномонтаж (4 колеса)", "price": "от 1 600 ₽" }
  ],
  "owner_chat_id": null,
  "landing_url": "https://sup4ikx.github.io/landing-pages/auto/",
  "welcome": "Рады видеть! Выберите, что вам нужно."
}
```

- [ ] **Step 5: Write `bots/cafe.json`**

```json
{
  "id": "cafe",
  "name": "Тёплый хлеб",
  "tagline": "Пекарня-кофейня на Пятницкой",
  "phone": "+7 900 111-22-33",
  "address": "Москва, ул. Пятницкая, 14",
  "hours": "ежедневно 8:00–22:00",
  "services": [
    { "name": "Круассан", "price": "190 ₽" },
    { "name": "Хлеб на закваске", "price": "320 ₽" },
    { "name": "Капучино", "price": "260 ₽" },
    { "name": "Раф", "price": "320 ₽" },
    { "name": "Сырники со сметаной", "price": "390 ₽" }
  ],
  "owner_chat_id": null,
  "landing_url": "https://sup4ikx.github.io/landing-pages/cafe/",
  "welcome": "Рады видеть! Выберите, что вам нужно."
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 42 tests

- [ ] **Step 7: Commit**

```bash
git add config.py bots tests/test_configs.py
git commit -m "feat: bot configs with strict validation and error format"
```

---

### Task 4: HTTP server

**Files:**
- Create: `server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `bot.handle_update`, `bot.Action` (Task 1).
- Produces (used by Task 5):
  - `server.make_handler(sites: dict[str, dict], clients: dict[str, object], secret: str) -> type` — handler class factory; `clients` values expose `.send_message(action)` and `.get_webhook_info()`.
  - `server.serve(sites, clients, secret, port: int) -> None` — blocking, threaded, binds `0.0.0.0`.
  - No module-level mutable state: all wiring is passed in.

- [ ] **Step 1: Write the failing tests** — `tests/test_server.py`:

```python
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import config
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'make_handler'`

- [ ] **Step 3: Write `server.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 53 tests

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: webhook server with secret check, health and status endpoints"
```

---

### Task 5: Entry point, keepalive workflow, end-to-end smoke test

**Files:**
- Create: `run.py`, `.github/workflows/keepalive.yml`, `tests/test_run.py`, `tests/test_e2e.py`

**Interfaces:**
- Consumes: `config.load_config` (Task 3), `server.serve` (Task 4), `tg.TelegramClient` (Task 2).
- Produces: `python3 run.py` (serve), `python3 run.py check-config` (offline validation), and the env contract `BOT_TOKEN_AUTO`, `BOT_TOKEN_CAFE`, `WEBHOOK_SECRET`, `WEBHOOK_BASE`, `PORT`.

- [ ] **Step 1: Write the failing tests** — `tests/test_run.py`:

```python
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
```

- [ ] **Step 2: Write the failing test** — `tests/test_e2e.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'run'` (the e2e test already passes once `server.py` exists)

- [ ] **Step 4: Write `run.py`**

```python
"""Entry point: validate configs, read env, register webhooks, serve HTTP."""
import logging
import os
import sys
from pathlib import Path

import config
import server as server_mod
import tg

ROOT = Path(__file__).resolve().parent
ENV_BY_BOT = {"auto": "BOT_TOKEN_AUTO", "cafe": "BOT_TOKEN_CAFE"}
REQUIRED_ENV = ["WEBHOOK_SECRET", "WEBHOOK_BASE"]


def load_configs():
    """Load and validate every bot config from bots/*.json."""
    configs = [config.load_config(path) for path in sorted((ROOT / "bots").glob("*.json"))]
    if not configs:
        raise config.ConfigError("bots/: нет ни одного конфига")
    return configs


def require_env():
    """Return the env values the bot needs, or raise listing what is missing."""
    missing = [name for name in list(ENV_BY_BOT.values()) + REQUIRED_ENV
               if not os.environ.get(name)]
    if missing:
        raise config.ConfigError("переменные окружения не заданы: " + ", ".join(missing))
    return {name: os.environ[name] for name in list(ENV_BY_BOT.values()) + REQUIRED_ENV}


def main(argv=None):
    """Validate, register webhooks and serve; `check-config` stops before any network call."""
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("tg-bots")
    try:
        configs = load_configs()
        env = require_env()
        if argv[:1] == ["check-config"]:
            log.info("configs and environment ok for: %s",
                     ", ".join(cfg["id"] for cfg in configs))
            return 0
        clients = {cfg["id"]: tg.TelegramClient(env[ENV_BY_BOT[cfg["id"]]]) for cfg in configs}
        for cfg in configs:
            client = clients[cfg["id"]]
            log.info("bot %s is @%s", cfg["id"], client.get_me().get("username"))
            url = f"{env['WEBHOOK_BASE'].rstrip('/')}/webhook/{cfg['id']}?secret={env['WEBHOOK_SECRET']}"
            client.set_webhook(url)
            log.info("webhook for %s registered at %s", cfg["id"], url)
        port = int(os.environ.get("PORT") or "8000")
        server_mod.serve({cfg["id"]: cfg for cfg in configs}, clients, env["WEBHOOK_SECRET"], port)
    except (config.ConfigError, tg.TelegramError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Write `.github/workflows/keepalive.yml`**

```yaml
name: Keep bot awake

on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Ping deployed bot health endpoint
        env:
          BOT_HEALTH_URL: ${{ secrets.BOT_HEALTH_URL }}
        run: |
          if [ -z "$BOT_HEALTH_URL" ]; then
            echo "BOT_HEALTH_URL is not set — skipping"; exit 0
          fi
          curl -fsS --max-time 20 "$BOT_HEALTH_URL"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 57 tests

- [ ] **Step 7: Offline smoke test of the entry point**

Run: `python3 run.py check-config; echo exit=$?`
Expected: exit 1 and stderr `переменные окружения не заданы: BOT_TOKEN_AUTO, BOT_TOKEN_CAFE, WEBHOOK_SECRET, WEBHOOK_BASE` (no network call).

Run: `BOT_TOKEN_AUTO=t1 BOT_TOKEN_CAFE=t2 WEBHOOK_SECRET=s WEBHOOK_BASE=https://example.invalid python3 run.py check-config; echo exit=$?`
Expected: exit 0 and one log line `configs and environment ok for: auto, cafe` — still no network access.

- [ ] **Step 8: Commit**

```bash
git add run.py .github tests/test_run.py tests/test_e2e.py
git commit -m "feat: entry point with webhook registration, e2e test and keepalive workflow"
```

---

### Task 6: README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: the real commands and env names from Tasks 3-5.
- Produces: the portfolio case's instructions; no code.

- [ ] **Step 1: Write `README.md`**

```markdown
# tg-bots

Два Telegram-бота (автосервис и кафе) — апсейл к лендингам из `~/Work/landing-pages`.
Только стандартная библиотека Python: ни одной зависимости, тесты работают без сети.

## Что умеет бот

- `/start` (в т.ч. `?start=landing_auto` с лендинга) — приветствие и три кнопки.
- «Услуги и цены» — список услуг с ценами и ссылка на лендинг.
- «Оставить заявку» — бот просит написать имя и телефон одним сообщением.
- Любой свободный текст разбирается как заявка: телефон ищется регуляркой и
  нормализуется к 11 цифрам с 7; имя — остаток текста.
- Валидная заявка → подтверждение клиенту и пересылка владельцу (клиент, телефон с
  кнопкой «Позвонить», источник «с лендинга» / «напрямую»).
- `/myid` — показывает ваш `chat_id`, чтобы вписать его в `owner_chat_id`.
- Бот stateless: перезапуск не ломает диалог, метка источника может сброситься.

## Локальный запуск

```bash
python3 -m unittest discover -s tests -v

BOT_TOKEN_AUTO=... BOT_TOKEN_CAFE=... \
WEBHOOK_SECRET=... WEBHOOK_BASE=https://example.com \
  python3 run.py                # сервер на $PORT (по умолчанию 8000)

python3 run.py check-config    # только проверка конфигов и переменных, без сети
```

Эндпоинты: `GET /health`, `GET /webhook-status`,
`POST /webhook/<bot_id>?secret=<WEBHOOK_SECRET>`.

## Настройка ботов

1. `@BotFather` → `/newbot` дважды: имя и username. Токен → в переменную окружения
   `BOT_TOKEN_AUTO` / `BOT_TOKEN_CAFE`. **Токены не коммитить.**
2. В `bots/<id>.json` вписать свой `owner_chat_id` (узнать его: открыть бота и
   нажать `/myid`).
3. Задеплоить (ниже), затем проверить: `/webhook-status` показывает активный
   вебхук, бот отвечает на `/start`.

## Деплой на Render (бесплатно)

1. Новый Web Service из этого репозитория, region Frankfurt, plan Free.
2. Environment: `BOT_TOKEN_AUTO`, `BOT_TOKEN_CAFE`, `WEBHOOK_SECRET`,
   `WEBHOOK_BASE=https://<service>.onrender.com`. `PORT` Render задаёт сам.
3. Health check path: `/health`.
4. Free-сервис засыпает при простое — пингер из GitHub Actions
   (`.github/workflows/keepalive.yml`) будит его каждые 10 минут.
   Секрет репозитория `BOT_HEALTH_URL` = `https://<service>.onrender.com/health`.

## Связка с лендингами

В `sites/<id>.json` задаётся `submit: {"type": "bot", "bot_username": "<username>"}` —
кнопка формы становится «Написать в Telegram», а ссылка
`t.me/<username>?start=landing_<id>` передаёт боту источник заявки.

## Если Render требует карту

Бот запускается локально той же командой; для клиента — видео-демо. Код и тесты
от этого не меняются.
```

- [ ] **Step 2: Verify every command in the README actually works**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -2`
Expected: `OK`

Run: `python3 run.py check-config; echo exit=$?`
Expected: exit 1 with the missing-environment message.

Run: `grep -c "BOT_TOKEN_AUTO\|WEBHOOK_SECRET\|WEBHOOK_BASE" run.py` → at least 3.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: local run, bot setup and render deploy instructions"
```

---

### Task 7: Deploy to Render and switch the landing sites

**Files:**
- Modify (in `~/Work/landing-pages`): `sites/auto.json`, `sites/cafe.json` — set
  `submit` to `{"type": "bot", "bot_username": "<real username>"}`.

**Interfaces:**
- Consumes: Task 5 (deployable server), Task 6 (deploy instructions).
- Produces: live bot URLs, active webhooks, redeployed landing pages whose form CTA
  opens Telegram with `?start=landing_<id>`.

- [ ] **Step 1: Get BotFather data from the user**

One message, from the user: the two usernames and the two tokens. Tokens go only into
Render's secret environment; they are never written to files, chat logs summaries or
git.

- [ ] **Step 2: Create the Render service and set env vars**

Per README: start command `python3 run.py`, health check `/health`, env vars from
Step 1 plus `WEBHOOK_SECRET` (generate e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`).

- [ ] **Step 3: Verify the deployment**

```bash
curl -s -o /dev/null -w "health: %{http_code}\n" https://<service>.onrender.com/health
curl -s https://<service>.onrender.com/webhook-status
```

Expected: `health: 200`; `/webhook-status` lists both bots with a `url` field and no
`last_error_message`.

- [ ] **Step 4: Wire `owner_chat_id`**

The owner opens each bot and presses `/myid`, then pastes the ids into
`bots/auto.json` and `bots/cafe.json`; commit and push (Render redeploys).

- [ ] **Step 5: Switch the landing configs and redeploy the sites**

In `~/Work/landing-pages`: set `submit` to `{"type": "bot", "bot_username": "<username>"}`
in both configs, then:

```bash
cd ~/Work/landing-pages
python3 -m unittest discover -s tests 2>&1 | tail -2
python3 generate.py
grep -rI 'Написать в Telegram' dist/ | head -2
git commit -am "feat: point landing forms at the telegram bots" && git push
```

Expected: tests OK, grep finds both `dist/*/index.html`, Pages redeploys.

- [ ] **Step 6: End-to-end manual check in Telegram**

Send `/start` to both bots; press «Оставить заявку»; send `Тест, +7 900 123-45-67`.
Confirm the forward arrives in the owner's chat with source `с лендинга` when entered
via the landing link and `напрямую` otherwise. Record the screen for the portfolio.

- [ ] **Step 7: Commit the owner ids and push**

```bash
cd ~/Work/tg-bots && git add bots && git commit -m "chore: set owner chat ids" && git push
```

## Self-Review (executed at plan write time)

- **Spec coverage:** bot scenarios 1-6 → Task 1 (each has a test); Bot API client →
  Task 2; config validation and per-niche copy → Task 3; webhook, health, status,
  secret check → Task 4; env contract, webhook registration, keepalive, deployable
  entry point → Task 5; documentation and card-free fallback → Task 6; live deployment,
  landing integration → Task 7. Acceptance criteria 1-2 → Task 4, 3-6 → Task 1,
  7 → Tasks 3-5, 8-9 → Task 7.
- **Placeholders:** BotFather tokens, bot usernames, the Render service name and
  `owner_chat_id` come from the user in Task 7 (secrets or deployment specifics, not
  code placeholders). The phone is the same temporary number as the landing configs,
  swapped together. No other gaps.
- **Type consistency:** `handle_update(update, cfg, owner_chat_id) -> list[Action]`,
  `Action(chat_id, text, reply_markup)`, `normalize_phone(raw) -> str`,
  `parse_request(text) -> tuple[str, str] | None`, `mark_source`/`get_source`,
  `validate(cfg, path)`, `load_config(path)`, `TelegramClient(token).send_message(action)`,
  `make_handler(sites, clients, secret)`, `serve(sites, clients, secret, port)`,
  `run.main(argv) -> int` — identical names and signatures in every task and test.
- **Review Focus:** 1 → Task 1 `test_update_without_text_or_callback` and
  `test_update_without_message_or_callback`; 2 → Task 1
  `test_eight_prefix_with_parens` and Task 5 `test_request_reaches_owner_chat`;
  3 → Task 3 `test_services_entry_without_price`; 4 → Task 4
  `test_malformed_json_returns_400`; 5 → Task 1 `test_forwarded_html_is_escaped`.
