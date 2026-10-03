# Design: Telegram bots for the landing-page upsell

Date: 2026-10-03
Status: approved by user
Related: `~/Work/landing-pages/docs/superpowers/specs/2026-09-29-landing-pages-design.md` (sub-project 1)

## Goal

Two Telegram bots (auto service + cafe) that serve as the upsell case: a client who
purchased a landing page sees the same niche as a working bot. Together with
sub-project 1 this produces portfolio case 1 and 2 of 6.

## Context and constraints

- Portfolio rule: one artifact per niche; both bots must be live and openable by link.
- Language: Python 3, standard library only, no pip dependencies — consistent with
  sub-project 1 and deployable on any free host.
- Hosting: free Render web service (512 MB) plus a GitHub Actions keep-alive pinger.
  Free web services spin down when idle, so a pinger keeps the bot responsive.
- Secrets (bot tokens, webhook secret) live only in environment variables and Render
  secret env. No token, no `.env` file in git.
- Free-tier details (whether Render asks for a card) are verified at signup; a
  cardless fallback is running the same code from the student's machine with a
  screen recording for the demo.

## Decision: stateless bot

Render restarts the process (idle spin-down, redeploy). Any in-memory dialogue state
("we already asked for the name") would be lost mid-conversation. The bot therefore
has no state machine: a free-text message is always interpreted as a request, the
phone number is extracted with a regex, and the rest of the text is the name. This
costs one extra "please repeat" round in the rare case a user writes something that
is not a request, and buys restart-proof behaviour.

## Architecture

Repository: `~/Work/tg-bots` (own git repo, separate portfolio case; no code coupling
with `landing-pages`, only a link).

| File | Responsibility |
|---|---|
| `tg.py` | Bot API client over `urllib`: `send_message`, `set_webhook`, `get_me`, `get_webhook_info` |
| `bot.py` | Core: `handle_update(update, cfg) -> list[Action]`, request parser, phone validation, texts |
| `server.py` | `ThreadingHTTPServer`: `POST /webhook/<bot_id>`, `GET /health`, secret check |
| `run.py` | Entry point: reads env, validates configs, starts the server |
| `bots/auto.json`, `bots/cafe.json` | Per-niche config |
| `tests/test_config.py` | Config validation |
| `tests/test_parser.py` | Request parsing and phone normalization |
| `tests/test_handlers.py` | Update-to-actions logic |
| `tests/test_server.py` | HTTP endpoints against a local port with a fake Bot API client |
| `README.md` | Run and deploy instructions (part of the case) |

`Action` is a small dataclass-like structure: `chat_id`, `text`, optional `reply_markup`,
optional `forward_to` (owner chat with a `tel:` button). Handlers return actions; the
server executes them through `tg.py`. Nothing in `bot.py` performs I/O, so every
behaviour is testable offline.

## Bot scenarios

1. `/start`, including deep link `?start=landing_<site_id>` — greeting with the niche
   name and three buttons: "Услуги и цены", "Оставить заявку", "Позвонить". The source
   marker (`с лендинга` for `landing_<id>`, `напрямую` otherwise) is stored in an
   in-memory map `chat_id → source`, filled at `/start` and refreshed by the request
   callback; it degrades to `напрямую` after a restart. The marker is best-effort
   metadata, never part of the dialogue logic, so a restart cannot break the flow.
2. "Услуги и цены" — one message listing services and prices.
3. "Оставить заявку" — "напишите имя и телефон одним сообщением, например:
   Иван, +7 900 123-45-67".
4. Free text — parsed as a request: phone via regex, normalized to 11 digits starting
   with 7 (the same rules as `generate.digits` in sub-project 1). No phone found →
   one action asking to repeat. Phone found → two actions: confirmation to the client,
   forward to the owner with name, phone (a "Позвонить" button), comment and source.
5. `/myid` — replies with the sender's `chat_id`; the owner puts it into the config
   (`owner_chat_id`). If `owner_chat_id` is `null`, requests are written to the log with
   an explicit warning instead of being silently dropped.
6. Unknown command — hint plus the keyboard.

Callback data carries the button action (`prices`, `req|<source>`, `phone`); no
dialogue state.

## Config

Per niche: `id`, `name`, `tagline`, `phone`, `address`, `hours`, `services[]`
(`name`, `price`), `owner_chat_id` (number or `null`), `landing_url`, `welcome`.
The `phone` value is the same one as in the landing configs (currently the temporary
test number `+7 900 111-22-33`) and is swapped together with them.
Validation mirrors sub-project 1: message format `<path>: отсутствует поле <name>`,
exit non-zero, no secrets in the file.

## Deployment

- Render free web service: start command `python3 run.py`, port from `PORT`,
  healthcheck `GET /health`. Env: `BOT_TOKEN_AUTO`, `BOT_TOKEN_CAFE`, `WEBHOOK_SECRET`,
  `WEBHOOK_BASE`, `PORT`.
- On start: `get_me` per bot (logs the bot username), `set_webhook` to
  `<WEBHOOK_BASE>/webhook/<bot_id>?secret=<WEBHOOK_SECRET>`.
- `.github/workflows/keepalive.yml` in this repo: `schedule: "*/10 * * * *"` plus
  `workflow_dispatch`, curls `secrets.BOT_HEALTH_URL`. The repo is public so Actions
  minutes are free.
- Verification after deploy: `get_webhook_info` shows an active webhook, public
  `/health` returns 200.

## Landing-page integration (the upsell)

In `landing-pages/sites/*.json`, set `submit` to `{"type": "bot", "bot_username":
"<bot>"}`. The generator already supports this mode: the form button becomes
"Написать в Telegram" and the link `t.me/<bot>?start=landing_<id>` carries the source.
Regenerate and redeploy the sites.

## Testing

All tests run offline, without tokens or network:

- handlers: `/start`, deep-link source marker, prices, request button, valid request,
  text without phone, `/myid`, unknown command — exact action counts and contents.
- parser: "Иван, +7 900 123-45-67", "+79001234567 Иван переборол двигатель", text
  without a phone, phone starting with 8, too-short number.
- config: missing required field, bad phone, missing services, valid configs.
- server: `GET /health` → 200; `POST /webhook/auto` without secret → 403; with secret
  → 200; unknown `bot_id` → 404; a valid update reaches the fake Bot API client.

## Acceptance criteria

1. `python3 run.py` starts the server; `GET /health` → 200.
2. `POST /webhook/auto` without the secret → 403; with the secret → 200; unknown
   `bot_id` → 404.
3. A `/start` update produces exactly one action: a message with the prices, request
   and phone buttons.
4. `/start` with `landing_cafe` marks the source "с лендинга" in the forwarded request.
5. "Иван, +7 900 123-45-67" produces exactly two actions: client confirmation and owner
   forward with phone `79001234567`. Text without a phone produces one action asking to
   repeat. A phone starting with 8 normalizes to 7.
6. `/myid` replies with the sender's `chat_id`.
7. Both configs validate; the whole suite passes (`python3 -m unittest discover -s tests`).
8. After deploy: `get_webhook_info` shows an active webhook, the public `/health`
   returns 200, and the bot answers in Telegram to `/start` and to a request.
9. The landing sites are switched to `submit.type: "bot"` and redeployed.

## Out of scope

Database, appointment booking with dates, photos or media in the bot, payments, an
admin panel, languages other than Russian, long-polling mode.

## Open items requiring the user

- Bot tokens from @BotFather for both bots (secrets, supplied at deploy time).
- Render account; whether the free tier asks for a card (fallback: local run plus
  screen recording).
