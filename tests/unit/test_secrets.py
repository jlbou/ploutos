"""Regla 19: los secretos no se imprimen nunca, ni por accidente."""

from __future__ import annotations

import pytest

from core.secrets import load_secrets, scrub_url

TOKEN = "8123456789:AAH-token-de-telegram-que-no-debe-salir"


@pytest.fixture(autouse=True)
def _telegram_desde_el_fichero_de_prueba(monkeypatch):
    """Aqui se prueba LEER un `.env` (uno de prueba, en tmp_path, nunca el real):
    se quita la variable vacia que pone `tests/conftest.py` para que ningun test
    mande Telegrams, porque la variable de entorno manda sobre el fichero."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    for nombre in ("HEALTHCHECK_INGESTA", "HEALTHCHECK_PAPEL", "HEALTHCHECK_PAPEL_IA", "HEALTHCHECK_COPIA",
                   "HEALTHCHECK_NOTICIAS"):
        monkeypatch.delenv(nombre, raising=False)


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        f"TELEGRAM_BOT_TOKEN={TOKEN}\n"
        "TELEGRAM_CHAT_ID=123456\n"
        "OKX_API_KEY=clave-okx\n"
        "OKX_API_SECRET=secreto-okx\n"
        "OKX_PASSWORD=passphrase-okx\n",
        encoding="utf-8",
    )
    return path


# --- carga ---


def test_sin_env_no_hay_nada(tmp_path):
    secrets = load_secrets(tmp_path / "no_existe.env")
    assert not secrets.has_telegram
    assert not secrets.has_okx
    assert not secrets.has_claude


def test_carga_desde_env(env_file):
    secrets = load_secrets(env_file)
    assert secrets.has_telegram
    assert secrets.has_telegram_chat
    assert secrets.has_okx


def test_el_valor_se_puede_recuperar_cuando_hace_falta(env_file):
    secrets = load_secrets(env_file)
    assert secrets.telegram_bot_token.get_secret_value() == TOKEN


def test_las_fases_1_a_3_no_necesitan_secretos(tmp_path):
    """Comprobacion explicita: sin .env el bot de datos publicos funciona."""
    secrets = load_secrets(tmp_path / "vacio.env")
    estado = secrets.status()
    assert {"telegram_bot_token", "okx", "claude", "healthcheck_ingesta"} <= set(estado)
    assert not any(estado.values()), estado


# --- no se filtran ---


def test_el_repr_no_ensenya_el_token(env_file):
    secrets = load_secrets(env_file)
    assert TOKEN not in repr(secrets)
    assert TOKEN not in str(secrets)


def test_status_no_lleva_valores(env_file):
    """status() dice QUE hay, nunca CUANTO vale."""
    values = load_secrets(env_file).status().values()
    assert all(isinstance(v, bool) for v in values)


def test_el_modelo_serializado_no_ensenya_el_token(env_file):
    """Si alguien vuelca el objeto a JSON, no puede salir el secreto."""
    secrets = load_secrets(env_file)
    assert TOKEN not in str(secrets.model_dump())
    assert TOKEN not in secrets.model_dump_json()


def test_okx_incompleto_no_cuenta_como_configurado(tmp_path):
    """Media credencial es una credencial rota, no una credencial."""
    path = tmp_path / ".env"
    path.write_text("OKX_API_KEY=solo-la-clave\n", encoding="utf-8")
    assert not load_secrets(path).has_okx


def test_campos_desconocidos_en_env_no_rompen(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ALGO_QUE_NO_CONOCEMOS=x\nTELEGRAM_CHAT_ID=9\n", encoding="utf-8")
    assert load_secrets(path).telegram_chat_id == "9"


# --- URLs ---


def test_scrub_url_quita_el_token():
    """La API de Telegram lleva el token EN LA URL: cualquier traza lo filtraria."""
    url = f"https://api.telegram.org/bot{TOKEN}/getMe"
    assert TOKEN not in scrub_url(url, TOKEN)
    assert "***REDACTED***" in scrub_url(url, TOKEN)


def test_scrub_url_aguanta_none():
    assert scrub_url("https://x/y", None) == "https://x/y"


def test_scrub_url_con_varios_tokens():
    text = "a=AAA b=BBB"
    assert scrub_url(text, "AAA", "BBB") == "a=***REDACTED*** b=***REDACTED***"


def test_un_secreto_cargado_se_redacta_en_los_logs(env_file, monkeypatch):
    """Integracion con core.logging: lo que cargamos, se redacta."""
    from core.logging import scrub

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert TOKEN not in scrub(f"fallo al mandar con {TOKEN}")


# --- un .env recien copiado del ejemplo no cuenta como configurado ---


def test_valor_vacio_cuenta_como_ausente(tmp_path):
    """Bug real: al copiar .env.example, `TELEGRAM_BOT_TOKEN=` se leia como
    "hay token" y el bot intentaba autenticarse con la cadena vacia."""
    path = tmp_path / ".env"
    path.write_text(
        "TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\nOKX_API_KEY=\n"
        "OKX_API_SECRET=\nOKX_PASSWORD=\nCLAUDE_CODE_OAUTH_TOKEN=\n",
        encoding="utf-8",
    )
    secrets = load_secrets(path)
    estado = secrets.status()
    assert {"telegram_bot_token", "okx", "claude", "healthcheck_ingesta"} <= set(estado)
    assert not any(estado.values()), estado


def test_solo_espacios_tambien_cuenta_como_ausente(tmp_path):
    path = tmp_path / ".env"
    path.write_text('TELEGRAM_BOT_TOKEN="   "\n', encoding="utf-8")
    assert not load_secrets(path).has_telegram


def test_el_env_example_del_repo_no_configura_nada():
    """Copiar .env.example tal cual tiene que dejar el bot en 'falta todo'."""
    from core.secrets import ENV_PATH

    example = ENV_PATH.parent / ".env.example"
    assert not any(load_secrets(example).status().values())


def test_las_url_del_vigilante_son_secretos(tmp_path):
    """Quien tenga una puede mandar latidos falsos y tapar una caida."""
    url = "https://hc-ping.com/0f9a8b7c-0000-4000-8000-123456789abc"
    path = tmp_path / ".env"
    path.write_text(f"HEALTHCHECK_PAPEL={url}\n", encoding="utf-8")
    secrets = load_secrets(path)
    assert secrets.valor("healthcheck_papel") == url
    assert secrets.valor("healthcheck_ingesta") is None
    assert url not in repr(secrets) and url not in str(secrets)
