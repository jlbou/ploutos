"""Logging JSON con filtro anti-secretos (PRD seccion 4, regla 19).

Regla 19: las claves de API nunca salen en los logs. No basta con "tener
cuidado": aqui se redactan por construccion, comparando contra los valores
reales del entorno. Si un secreto llega a un log por accidente, sale como
`***REDACTED***`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from core.clock import utcnow

# Variables de entorno cuyo VALOR nunca puede aparecer en un log.
SECRET_ENV_VARS: tuple[str, ...] = (
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_PASSWORD",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)

# Claves cuyo CONTENIDO se redacta siempre, venga de donde venga.
SECRET_KEY_HINTS: tuple[str, ...] = (
    "secret",
    "password",
    "passphrase",
    "token",
    "apikey",
    "api_key",
    "authorization",
    "credential",
)

REDACTED = "***REDACTED***"
_MIN_SECRET_LEN = 6  # por debajo de esto, redactar generaria falsos positivos


def _secret_values() -> list[str]:
    """Valores reales de los secretos presentes en el entorno, si los hay."""
    values = []
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= _MIN_SECRET_LEN:
            values.append(value)
    return values


def scrub(value: Any, secrets: list[str] | None = None) -> Any:
    """Redacta secretos de cualquier estructura antes de escribirla."""
    secrets = _secret_values() if secrets is None else secrets
    if isinstance(value, str):
        for secret in secrets:
            if secret in value:
                value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if any(hint in str(key).lower() for hint in SECRET_KEY_HINTS):
                out[key] = REDACTED
            else:
                out[key] = scrub(val, secrets)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """Una linea JSON por evento, con timestamp UTC (PRD seccion 13)."""

    def format(self, record: logging.LogRecord) -> str:
        secrets = _secret_values()
        payload: dict[str, Any] = {
            "ts": utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub(record.getMessage(), secrets),
        }
        extra = getattr(record, "context", None)
        if isinstance(extra, dict):
            payload["context"] = scrub(extra, secrets)
        decision_id = getattr(record, "decision_id", None)
        if decision_id:
            payload["decision_id"] = decision_id
        if record.exc_info:
            payload["exc"] = scrub(self.formatException(record.exc_info), secrets)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", file: str | None = None) -> None:
    """Configura el logging raiz. Idempotente: se puede llamar varias veces."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level.upper())

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)

    if file:
        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    # ccxt es muy verboso en DEBUG y puede llegar a imprimir cabeceras.
    logging.getLogger("ccxt").setLevel(max(logging.INFO, root.level))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_context(logger: logging.Logger, level: int, msg: str, **context: Any) -> None:
    """Loguea con contexto estructurado, ya redactado."""
    logger.log(level, msg, extra={"context": context})
