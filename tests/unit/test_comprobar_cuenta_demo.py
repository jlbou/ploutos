"""La comprobacion de la cuenta demo (`scripts/comprobar_cuenta_demo.py`): solo sus partes puras, sin red ni claves."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "comprobar_cuenta_demo.py"
_spec = importlib.util.spec_from_file_location("comprobar_cuenta_demo", SCRIPT)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

CONF = (0.10, 0.20)
BIEN = {"BTC-USDC": (0.10, 0.20)}


def test_los_permisos_se_leen_de_perm():
    assert m.permisos({"data": [{"perm": "read_only,trade"}]}) == {"read_only", "trade"}
    assert m.permisos({}) == set()


def test_la_comision_de_okx_va_con_el_signo_al_reves_y_se_lee_la_de_usdc():
    """Negativo = la pagas. `maker`/`taker` son los de USDT: no se leen."""
    r = {"data": [{"maker": "-0.0008", "taker": "-0.001", "makerUSDC": "-0.001", "takerUSDC": "-0.002"}]}
    maker, taker = m.comision_usdc(r)
    assert round(maker, 6) == 0.10 and round(taker, 6) == 0.20
    assert m.comision_usdc({"data": [{}]}) == (None, None)


def test_en_orden():
    assert m.veredicto({"read_only", "trade"}, "1", BIEN, CONF) == []


def test_con_permiso_de_retirada_no_se_opera():
    assert any("retirada" in x for x in m.veredicto({"read_only", "trade", "withdraw"}, "1", BIEN, CONF))


def test_comision_mas_cara_o_desconocida_no_se_opera():
    assert any("taker real 0.250" in x for x in m.veredicto({"trade"}, "1", {"BTC-USDC": (0.10, 0.25)}, CONF))
    assert any("no devolvio" in x for x in m.veredicto({"trade"}, "1", {"BTC-USDC": (None, 0.20)}, CONF))
    assert m.veredicto({"trade"}, "1", {"BTC-USDC": (0.08, 0.15)}, CONF) == [], "mas barata: se opera"
    assert any("ninguna" in x for x in m.veredicto({"trade"}, "1", {}, CONF))


def test_la_comision_se_mira_par_por_par():
    """El 02/10, en el demo, NEAR pagaba 0,20 % / 0,35 % y BTC 0,10 % / 0,20 %: mirando solo BTC no se veia."""
    reales = {"BTC-USDC": (0.10, 0.20), "NEAR-USDC": (0.20, 0.35)}
    motivos = m.veredicto({"read_only", "trade"}, "1", reales, CONF)
    assert len(motivos) == 2 and all(x.startswith("NEAR-USDC:") for x in motivos)
    assert set(m.DEMO) == {"BTC-USDC", "ETH-USDC", "SOL-USDC", "DOGE-USDC", "NEAR-USDC"}


def test_sin_comision_en_usdc_o_sin_trading_no_se_opera():
    assert any("feeType = 0" in x for x in m.veredicto({"trade"}, "0", BIEN, CONF))
    assert any("trading" in x for x in m.veredicto({"read_only"}, "1", BIEN, CONF))
