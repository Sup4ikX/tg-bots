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

python3 run.py check-config    # только проверка конфигов и переменных, без сети

BOT_TOKEN_AUTO=... BOT_TOKEN_CAFE=... \
WEBHOOK_SECRET=... WEBHOOK_BASE=https://example.com \
  python3 run.py                # сервер на $PORT (по умолчанию 8000)
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
