"""Como acabo una llamada a claude -p (`ai/quota.py`)."""

from __future__ import annotations

import json

import pytest

from ai.quota import CallOutcome, classify


def sobre(**kw):
    base = {"type": "result", "subtype": "success", "is_error": False, "result": "ok",
            "structured_output": {"decisions": [], "market_read": "."}}
    base.update(kw)
    return json.dumps(base)


def test_una_llamada_buena():
    c = classify(0, sobre())
    assert c.outcome is CallOutcome.OK
    assert c.envelope["structured_output"]["market_read"] == "."


def test_el_error_real_del_control_sin_token_del_22_09():
    """Exactamente lo que devolvio el CLI sin sesion y sin token."""
    c = classify(1, sobre(is_error=True, result="Not logged in · Please run /login"))
    assert c.outcome is CallOutcome.AUTH
    assert c.outcome.enters_quota_mode


@pytest.mark.parametrize("texto", [
    "You've hit your session limit · resets 3pm",
    "You've hit your weekly limit",
    "You've hit your Sonnet limit",
    "API Error: rate_limit",
])
def test_cuota_agotada(texto):
    c = classify(1, sobre(is_error=True, result=texto))
    assert c.outcome is CallOutcome.QUOTA and c.outcome.enters_quota_mode


@pytest.mark.parametrize("texto", ["Login expired · Please run /login", "OAuth token has expired"])
def test_login_caducado(texto):
    assert classify(1, sobre(is_error=True, result=texto)).outcome is CallOutcome.AUTH


def test_el_error_puede_venir_solo_por_stderr_sin_json():
    c = classify(1, "", "Error: Not logged in. Please run /login")
    assert c.outcome is CallOutcome.AUTH


def test_el_timeout_es_sin_ia_pero_no_cambia_de_modo():
    c = classify(None, "", timed_out=True)
    assert c.outcome is CallOutcome.TIMEOUT and not c.outcome.enters_quota_mode


def test_un_fallo_desconocido_es_sin_ia_pero_no_cambia_de_modo():
    """Informe 3.1: tratar cualquier fallo desconocido como 'sin IA'."""
    c = classify(1, sobre(is_error=True, result="algo raro que nunca hemos visto"))
    assert c.outcome is CallOutcome.ERROR and not c.outcome.enters_quota_mode


def test_codigo_cero_pero_salida_que_no_es_json():
    assert classify(0, "esto no es json").outcome is CallOutcome.ERROR


def test_una_respuesta_buena_que_habla_de_rate_limit_no_es_un_error():
    """Los patrones solo se miran si la llamada fallo."""
    ok = sobre(result="market_read: hay rate limit en otro exchange")
    assert classify(0, ok).outcome is CallOutcome.OK


def test_el_secreto_nunca_sale_en_el_detalle():
    secreto = "sk-ant-oat01-SECRETO-FALSO"
    c = classify(1, "", f"token {secreto} invalido: authentication_error", secret=secreto)
    assert secreto not in c.detail and "***" in c.detail


def test_el_detalle_se_recorta():
    c = classify(1, "", "x" * 5000)
    assert len(c.detail) <= 200


def test_nunca_lanza():
    for cosa in ("", "[]", "null", "{", "\x00"):
        classify(1, cosa)
        classify(0, cosa)
