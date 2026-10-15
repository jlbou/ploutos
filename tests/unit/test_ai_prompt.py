"""La entrada del analista (`ai/prompt.py`).

Lo que se protege: regla 19 (la IA nunca ve claves ni entorno), que la entrada
sea un mundo cerrado, y que lo que el prompt ofrece y lo que el parser acepta
sean los mismos `cid`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from ai.parser import parse
from ai.prompt import (
    INPUT_KEYS,
    SYSTEM_PROMPT,
    LimitsView,
    PositionView,
    build_input,
    candidate_ids,
    position_ids,
    render,
)
from features.regime import Regime
from strategy.candidates import Candidate, make_decision_id

NOW = datetime(2026, 9, 22, 16, tzinfo=UTC)


def candidato(symbol="TRX/USDC", entry=0.3416, stop=0.33765, target=0.36148):
    ts = int(NOW.timestamp() * 1000)
    did = make_decision_id(symbol, "pullback_trend", ts)
    return Candidate(
        cid=did, decision_id=did, symbol=symbol, setup="pullback_trend", timeframe="4h",
        entry=entry, stop=stop, target=target, reward_risk=5.03, cost_rt_pct=0.269,
        spread_pct=0.0205, regime=Regime.TREND_UP, bar_ts_ms=ts, created_at=NOW,
        reasons=("retroceso a la EMA",), features={"rsi14": 48.123456, "adx14": 46.8},
    )


def entrada(**kw):
    base = dict(
        now=NOW, mode="NORMAL", equity_usd=50.0, free_quote_usd=35.0,
        positions=[PositionView("d-20260921T0800-sol-pb", "SOL/USDC", 118.0, 119.2,
                                114.0, 126.0, NOW - timedelta(hours=8))],
        limits=LimitsView(3, 2, 0.5, 3.0, 5),
        candidates=[candidato(), candidato("ETH/USDC", 2751.0, 2670.0, 2950.0)],
    )
    base.update(kw)
    return build_input(**base)


def test_la_entrada_es_un_mundo_cerrado():
    e = entrada()
    assert set(e) == INPUT_KEYS
    with pytest.raises(ValueError, match="no permitidas"):
        render({**e, "api_key": "x"})


def test_el_texto_es_json_valido_mas_la_instruccion():
    texto = render(entrada())
    json_part, instruccion = texto.split("\n")
    assert json.loads(json_part)["mode"] == "NORMAL"
    assert "JSON del esquema" in instruccion


def test_regla_19_ningun_secreto_del_entorno_llega_al_prompt(monkeypatch):
    secretos = {
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-SECRETO-FALSO-123456",
        "OKX_API_KEY": "clave-okx-falsa-abcdef",
        "OKX_API_SECRET": "secreto-okx-falso-987654",
        "OKX_API_PASSPHRASE": "frase-falsa-okx",
        "TELEGRAM_BOT_TOKEN": "123456:telegram-falso",
    }
    for k, v in secretos.items():
        monkeypatch.setenv(k, v)
    texto = render(entrada()) + SYSTEM_PROMPT
    for nombre, valor in secretos.items():
        assert valor not in texto, f"el valor de {nombre} ha llegado al prompt"
        assert nombre not in texto


def test_los_cid_que_ofrece_el_prompt_son_los_que_acepta_el_parser():
    e = entrada()
    cids = candidate_ids(e)
    assert cids == {c["cid"] for c in e["candidates"]}
    salida = {"decisions": [{"type": "open", "ref": sorted(cids)[0], "confidence": 0.5,
                             "reasons": ["ok"]}], "market_read": "."}
    assert parse(salida, cids, position_ids(e)).ok


def test_las_posiciones_van_como_contexto():
    p = entrada()["portfolio"]["open_positions"][0]
    assert p["age_min"] == 8 * 60
    assert p["unrealized_pct"] == pytest.approx(1.02, abs=0.01)


def test_el_candidato_sale_de_to_prompt_dict_mas_el_spread():
    c = candidato()
    d = entrada(candidates=[c])["candidates"][0]
    assert d == {**c.to_prompt_dict(), "spread_pct": 0.0205}


def test_sin_noticias_ni_memoria_por_ahora():
    """Decisiones del propietario: sin noticias en la fase 3; la memoria es de la fase 8."""
    e = entrada()
    assert "news" not in json.dumps(e) and e["memory"] == []


def test_el_prompt_cabe_en_lo_que_dice_el_informe():
    """Informe seccion 1.5: en produccion, ~2-4 KB. Cada byte de mas es cuota."""
    tres = [candidato(), candidato("ETH/USDC", 2751.0, 2670.0, 2950.0),
            candidato("BTC/USDC", 86229.0, 83400.0, 92000.0)]
    assert len(render(entrada(candidates=tres)).encode()) < 4096


def test_el_system_prompt_dice_lo_que_importa():
    for idea in ("cid", "ref", "0.5", "1.0", "skip", "Nunca puedes aumentarlo"):
        assert idea in SYSTEM_PROMPT
