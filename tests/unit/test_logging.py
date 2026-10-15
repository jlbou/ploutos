"""Regla 19: los secretos nunca salen en los logs.

No basta con "tener cuidado". Aqui se comprueba que, si un secreto llega a un
log por accidente, sale redactado.
"""

from __future__ import annotations

import json
import logging

import pytest

from core.logging import REDACTED, JsonFormatter, scrub, setup_logging

SECRET = "sk-super-secreto-de-verdad-12345"


@pytest.fixture
def with_secret(monkeypatch):
    monkeypatch.setenv("OKX_API_SECRET", SECRET)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token-larguisimo-999")
    return SECRET


# --- redaccion por valor ---


def test_un_secreto_en_un_mensaje_se_redacta(with_secret):
    assert SECRET not in scrub(f"fallo la auth con {SECRET}")
    assert REDACTED in scrub(f"fallo la auth con {SECRET}")


def test_un_secreto_dentro_de_un_dict_se_redacta(with_secret):
    out = scrub({"detalle": {"cabecera": f"Bearer {SECRET}"}})
    assert SECRET not in json.dumps(out)


def test_un_secreto_dentro_de_una_lista_se_redacta(with_secret):
    out = scrub(["ok", f"clave={SECRET}", "fin"])
    assert SECRET not in json.dumps(out)


def test_el_texto_normal_no_se_toca(with_secret):
    assert scrub("BTC/USDC spread 0.01 %") == "BTC/USDC spread 0.01 %"


# --- redaccion por nombre de clave ---


@pytest.mark.parametrize(
    "key", ["api_secret", "password", "passphrase", "token", "apiKey", "Authorization"]
)
def test_las_claves_sospechosas_se_redactan_siempre(key):
    """Aunque el valor no este en el entorno: si la clave se llama asi, fuera."""
    assert scrub({key: "lo-que-sea"})[key] == REDACTED


def test_una_clave_sospechosa_anidada_se_redacta():
    out = scrub({"config": {"okx": {"secret": "abc123456"}}})
    assert out["config"]["okx"]["secret"] == REDACTED


# --- formateador ---


def test_el_formateador_produce_json_con_timestamp_utc():
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "hola", None, None
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "hola"
    assert payload["level"] == "INFO"
    assert payload["ts"].endswith("+00:00")


def test_el_formateador_redacta_el_mensaje(with_secret):
    record = logging.LogRecord(
        "t", logging.ERROR, __file__, 1, "auth fallo: %s", (SECRET,), None
    )
    assert SECRET not in JsonFormatter().format(record)


def test_el_formateador_redacta_el_contexto(with_secret):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None)
    record.context = {"headers": {"Authorization": f"Bearer {SECRET}"}}
    assert SECRET not in JsonFormatter().format(record)


def test_el_decision_id_aparece_en_el_json():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None)
    record.decision_id = "d-42"
    assert json.loads(JsonFormatter().format(record))["decision_id"] == "d-42"


# --- integracion ---


def test_un_secreto_logueado_de_verdad_no_llega_al_fichero(
    tmp_path, with_secret, capsys
):
    """La prueba que importa: end to end, con un fichero real."""
    log_file = tmp_path / "test.log"
    setup_logging("INFO", str(log_file))
    try:
        logging.getLogger("prueba").error(
            "no se pudo autenticar con la clave %s", SECRET
        )
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = log_file.read_text(encoding="utf-8")
        assert SECRET not in content
        assert REDACTED in content
        assert SECRET not in capsys.readouterr().out
    finally:
        setup_logging("INFO", None)


def test_setup_logging_es_idempotente(tmp_path):
    setup_logging("INFO", str(tmp_path / "a.log"))
    before = len(logging.getLogger().handlers)
    setup_logging("INFO", str(tmp_path / "a.log"))
    assert len(logging.getLogger().handlers) == before
    setup_logging("INFO", None)


def test_los_valores_cortos_no_se_redactan(monkeypatch):
    """Redactar 'abc' llenaria los logs de ***REDACTED*** sin motivo."""
    monkeypatch.setenv("OKX_API_KEY", "abc")
    assert scrub("el simbolo abc no existe") == "el simbolo abc no existe"
