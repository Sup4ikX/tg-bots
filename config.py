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
