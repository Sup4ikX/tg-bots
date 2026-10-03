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
    names = list(ENV_BY_BOT.values()) + REQUIRED_ENV
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise config.ConfigError("переменные окружения не заданы: " + ", ".join(missing))
    return {name: os.environ[name] for name in names}


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
        server_mod.serve({cfg["id"]: cfg for cfg in configs}, clients,
                         env["WEBHOOK_SECRET"], int(os.environ.get("PORT") or "8000"))
    except (config.ConfigError, tg.TelegramError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
