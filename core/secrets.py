"""Carga de secretos desde `.env` (regla dura 19).

Reglas de esta casa:
  * los secretos SOLO viven en `.env`, que esta en `.gitignore`;
  * nunca se imprimen, ni en logs, ni en errores, ni en un `repr()`;
  * la IA nunca ve este objeto ni el entorno.

Las fases 1-3 no necesitan ningun secreto: funcionan con datos publicos.
Telegram hace falta desde la fase 0 (verificacion) y se usa desde la fase 5.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Secrets(BaseSettings):
    """Secretos del proyecto. Todo opcional: cada fase usa los suyos."""

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _vacio_es_ausente(cls, value: object) -> object:
        """Un `.env` recien copiado del ejemplo trae `CLAVE=` (vacio).

        Sin esto, un secreto vacio contaria como configurado y el bot
        intentaria autenticarse con la cadena vacia, fallando con un error
        confuso en vez de decir "falta el token".
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # --- OKX (fase 4; en fase 4 son las del entorno DEMO) ---
    okx_api_key: SecretStr | None = None
    okx_api_secret: SecretStr | None = None
    okx_password: SecretStr | None = None
    okx_demo: bool = True

    # --- Claude (fase 3) ---
    claude_code_oauth_token: SecretStr | None = Field(default=None)

    # --- Telegram (fase 0 para verificar, fase 5 para usar) ---
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # --- Vigilante externo, Healthchecks.io (decision del propietario del 24/09/2026) ---
    # Una URL por comprobacion. Son secretas: quien las tenga puede mandar latidos
    # falsos y tapar una caida.
    healthcheck_ingesta: SecretStr | None = None
    healthcheck_papel: SecretStr | None = None
    healthcheck_papel_ia: SecretStr | None = None
    healthcheck_copia: SecretStr | None = None
    healthcheck_noticias: SecretStr | None = None   # el servicio ploutos-news (quinta comprobacion)
    healthcheck_telegram: SecretStr | None = None   # el servicio ploutos-telegram (sexta)
    healthcheck_ejecutor: SecretStr | None = None   # el ejecutor del demo, ploutos-exec (fase 4; octava)
    healthcheck_medios: SecretStr | None = None     # los medios en sombra, ploutos-medios (07/10; novena)

    # --- disponibilidad, sin exponer valores ---

    @property
    def has_telegram(self) -> bool:
        return self.telegram_bot_token is not None

    @property
    def has_telegram_chat(self) -> bool:
        return bool(self.telegram_chat_id)

    @property
    def has_okx(self) -> bool:
        return all(
            (self.okx_api_key, self.okx_api_secret, self.okx_password)
        )

    @property
    def has_claude(self) -> bool:
        return self.claude_code_oauth_token is not None

    def status(self) -> dict[str, bool]:
        """Que hay configurado. NUNCA los valores."""
        return {
            "telegram_bot_token": self.has_telegram,
            "telegram_chat_id": self.has_telegram_chat,
            "okx": self.has_okx,
            "claude": self.has_claude,
            **{n: getattr(self, n) is not None for n in (
                "healthcheck_ingesta", "healthcheck_papel", "healthcheck_papel_ia", "healthcheck_copia",
                "healthcheck_noticias", "healthcheck_telegram", "healthcheck_ejecutor", "healthcheck_medios",
            )},
        }

    def valor(self, nombre: str) -> str | None:
        """El valor de un secreto opcional, o None. Para pasarlo, nunca para imprimirlo."""
        secreto = getattr(self, nombre)
        return secreto.get_secret_value().strip() if secreto is not None else None

    def __repr__(self) -> str:
        return f"Secrets({self.status()})"

    __str__ = __repr__


def load_secrets(env_file: str | Path | None = None) -> Secrets:
    if env_file is not None:
        return Secrets(_env_file=env_file)  # type: ignore[call-arg]
    return Secrets()


def scrub_url(url: str, *tokens: str | None) -> str:
    """Quita tokens de una URL antes de ensenyarla.

    La API de Telegram lleva el token EN LA URL, asi que cualquier traza de
    error lo filtraria. Todo mensaje de error que incluya una URL pasa por aqui.
    """
    out = url
    for token in tokens:
        if token:
            out = out.replace(token, "***REDACTED***")
    return out
