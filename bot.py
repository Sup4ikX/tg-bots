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
