"""Operaciones cerradas y linea de tiempo de la IA (api/historial.py), con una base de papel de verdad."""

from __future__ import annotations

import json

import pytest

from api import historial
from portfolio import store

T0 = 1_790_352_000_000          # 25/09/2026 16:00 UTC
XRP, AVAX = "d-20260925T1600-xrp-pb", "d-20260925T1600-avax-pb"


def candidato(did, simbolo):
    return (f"{did} {simbolo} pullback_trend (4h): entrada 1.5718, stop 1.4879 (-5.34 %), objetivo 1.8638 "
            f"(+18.58 %), R:R 3.48, coste 0.382 % = 48.7x")


@pytest.fixture
def base(tmp_path):
    c = store.connect(tmp_path / "ai.db")
    store.migrate(c)
    with c:
        c.executemany("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail) VALUES (?,?,?,?,?,?)", [
            (T0, XRP, "XRP/USDC", "pullback_trend", "candidate", candidato(XRP, "XRP/USDC")),
            (T0, AVAX, "AVAX/USDC", "pullback_trend", "candidate", candidato(AVAX, "AVAX/USDC")),
            (T0, XRP, "XRP/USDC", "pullback_trend", "submitted", "ADX 32.5"),
            (T0, AVAX, "AVAX/USDC", "pullback_trend", "vetoed", "regla 15: correlacion > 0,8 <con XRP>"),
            (T0, None, "BTC/USDC", None, "filtered", "spread"),
        ])
        estructura = {"market_read": "Mercado alcista moderado.", "decisions": []}
        cur = c.execute("INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates, latency_s,"
                        " structured) VALUES (?,?,?,?,?,?,?,?,?)",
                        (T0, T0 + 4 * 3600_000 + 4000, "decision", "ok", 1, "2 open", 2, 22.2, json.dumps(estructura)))
        call = cur.lastrowid
        c.executemany("INSERT INTO ai_decisions (call_id, ref, type, size_multiplier, confidence, reasons, risks, executed)"
                      " VALUES (?,?,?,?,?,?,?,?)", [
                          (call, XRP, "open", 1.0, 0.68, json.dumps(["ADX 32.5"]), json.dumps(["stop cerca"]), 1),
                          (call, AVAX, "open", 0.7, 0.55, json.dumps(["RR 3.16"]), json.dumps(["correlacion"]), 1)])
        c.executemany("INSERT INTO paper_trades (decision_id, symbol, setup, decider, qty, entry_price, exit_price,"
                      " stop_price, target_price, opened_ts_ms, closed_ts_ms, reason, entry_fee_usd, exit_fee_usd,"
                      " exit_was_maker, mae_pct, mfe_pct, net_pnl_usd, r_multiple) VALUES"
                      " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                          ("d-a", "ETH/USDC", "pullback_trend", "ai", 0.01, 100, 95, 95, 110, T0, T0 + 3600_000, "stop",
                           0.001, 0.002, 0, -5, 1, -0.053, -1.06),
                          ("d-b", "SOL/USDC", "range_breakout", "ai", 0.1, 50, 55, 48, 55, T0, T0 + 7200_000, "target",
                           0.005, 0.005, 1, -1, 10, 0.49, 2.45)])
    yield c
    c.close()


def test_la_linea_de_tiempo_de_la_ia(base):
    [vela] = historial.decisiones(base)
    assert vela["vela_ms"] == T0 and vela["resultado"] == "ok" and vela["lectura"] == "Mercado alcista moderado."
    assert [c["simbolo"] for c in vela["candidatos"]] == ["XRP/USDC", "AVAX/USDC"]      # los filtrados, no
    xrp, avax = vela["candidatos"]
    assert xrp["ia"]["tipo"] == "open" and xrp["ia"]["confianza"] == 0.68 and xrp["ia"]["motivos"] == ["ADX 32.5"]
    assert xrp["motor"] == "enviada" and xrp["veto"] is None
    assert avax["ia"]["multiplicador"] == 0.7 and avax["motor"] == "vetada" and "regla 15" in avax["veto"]
    assert xrp["numeros"] == {"entrada": 1.5718, "stop": 1.4879, "stop_pct": -5.34, "objetivo": 1.8638,
                              "objetivo_pct": 18.58, "rr": 3.48}


def test_un_candidato_que_la_ia_no_menciono(base):
    with base:
        base.execute("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail) VALUES"
                     " (?, 'd-x', 'SOL/USDC', 'pullback_trend', 'candidate', 'formato raro')", (T0,))
    [vela] = historial.decisiones(base)
    sol = next(c for c in vela["candidatos"] if c["decision_id"] == "d-x")
    assert sol["ia"] is None and sol["numeros"] is None and sol["motor"] is None


def test_las_operaciones_y_su_csv(base):
    ops = historial.operaciones(base, "ai")
    assert [o["decision_id"] for o in ops] == ["d-b", "d-a"]             # la mas reciente primero
    texto = historial.csv_operaciones(ops)
    lineas = texto.strip().splitlines()
    assert lineas[0].split(";") == list(historial.COLUMNAS_CSV)
    assert lineas[1].startswith("ai;d-a;ETH/USDC") and lineas[2].startswith("ai;d-b;SOL/USDC")   # por cierre


def test_una_base_sin_decisiones_de_la_ia(tmp_path):
    c = store.connect(tmp_path / "base.db")
    store.migrate(c)
    assert historial.decisiones(c) == [] and historial.operaciones(c, "baseline") == []


def test_la_curva_comparada(tmp_path, base):
    from data.store.db import open_database
    import sqlite3
    with base:
        base.executemany("INSERT INTO paper_equity (ts_ms, equity_usd, positions, pending) VALUES (?,?,?,?)",
                         [(T0, 50.0, 0, 0), (T0 + 4 * 3600_000, 50.5, 1, 0)])
    db = open_database(tmp_path / "main.db")
    db.executemany_sync("INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close, volume, closed,"
                        " source, ingested_ms) VALUES (?,?,?,?,?,?,?,1,1,'rest',0)",
                        [("BTC/USDC", "4h", T0 - 4 * 3600_000, 1, 1, 1, 100.0), ("BTC/USDC", "4h", T0, 1, 1, 1, 100.0),
                         ("BTC/USDC", "4h", T0 + 4 * 3600_000, 1, 1, 1, 110.0)])
    db.close()
    principal = sqlite3.connect(tmp_path / "main.db")
    c = historial.curva({"ai": base, "baseline": None}, principal, 50.0)
    assert c["ai"] == [[T0, 50.0], [T0 + 4 * 3600_000, 50.5]]
    assert c["btc"] == [[T0, 50.0], [T0 + 4 * 3600_000, 55.0]]            # desde la primera vela de las carteras
    assert "baseline" not in c


# --------------------------------------------------------------------------
# El grafico de cada posicion abierta (el propietario, 01/10)
# --------------------------------------------------------------------------

H4 = 4 * 3600_000


def _principal(tmp_path, filas):
    import sqlite3

    from data.store.db import open_database
    db = open_database(tmp_path / "main.db")
    db.executemany_sync("INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close, volume, closed,"
                        " source, ingested_ms) VALUES (?,?,?,?,?,?,?,1,?,'rest',0)", filas)
    db.close()
    return sqlite3.connect(tmp_path / "main.db")


def test_las_velas_de_una_posicion_con_la_vela_en_curso(tmp_path):
    """Las de 4 h cerradas desde 12 antes de la entrada, y la que esta en curso armada con las de 1 minuto."""
    entrada = T0 + 20 * H4
    filas = [("AVAX/USDC", "4h", T0 + k * H4, 10, 11, 9, 10 + k / 10, 1) for k in range(30)]   # hasta T0+29*H4
    filas += [("ETH/USDC", "4h", T0 + 29 * H4, 1, 1, 1, 1, 1)]                                 # otra moneda: fuera
    en_curso = T0 + 30 * H4
    filas += [("AVAX/USDC", "1m", en_curso + m * 60_000, o, h, lo, c, 1)
              for m, (o, h, lo, c) in enumerate([(12.9, 13.0, 12.8, 12.95), (12.95, 13.4, 12.9, 13.1), (13.1, 13.2, 12.5, 12.7)])]
    filas += [("AVAX/USDC", "1m", en_curso - 60_000, 99, 99, 99, 99, 1)]                       # de la vela anterior
    velas = historial.velas_posicion(_principal(tmp_path, filas), "AVAX/USDC", entrada)
    assert velas[0][0] == entrada - historial.VELAS_ANTES * H4
    assert [v[0] for v in velas[:-1]] == [T0 + k * H4 for k in range(8, 30)]
    assert velas[-1] == [en_curso, 12.9, 13.4, 12.5, 12.7], "abre con la primera, cierra con la ultima, max y min"


def test_sin_minutos_no_se_inventa_la_vela_en_curso(tmp_path):
    filas = [("AVAX/USDC", "4h", T0 + k * H4, 10, 11, 9, 10, 1) for k in range(3)]
    filas += [("AVAX/USDC", "4h", T0 + 3 * H4, 10, 11, 9, 10, 0)]                              # sin cerrar: no se usa
    velas = historial.velas_posicion(_principal(tmp_path, filas), "AVAX/USDC", T0 + 2 * H4)
    assert [v[0] for v in velas] == [T0, T0 + H4, T0 + 2 * H4]


def test_una_posicion_muy_vieja_ensenya_solo_las_ultimas(tmp_path):
    filas = [("AVAX/USDC", "4h", T0 + k * H4, 10, 11, 9, 10, 1) for k in range(historial.MAX_VELAS + 50)]
    velas = historial.velas_posicion(_principal(tmp_path, filas), "AVAX/USDC", T0)
    assert len(velas) == historial.MAX_VELAS and velas[-1][0] == T0 + (historial.MAX_VELAS + 49) * H4


def test_el_endpoint_solo_acepta_monedas_de_la_whitelist(tmp_path):
    from pathlib import Path

    from fastapi import HTTPException

    from api.app import crear_app
    from core.config import load_settings
    _principal(tmp_path, [("AVAX/USDC", "4h", T0, 10, 11, 9, 10, 1)]).close()
    rutas = {k: Path("no-esta.db") for k in ("baseline", "ai", "noticias", "control")}
    rutas["principal"] = tmp_path / "main.db"
    app = crear_app(load_settings(), rutas)
    velas = next(r for r in app.routes if getattr(r, "path", "") == "/api/velas").endpoint
    assert velas(simbolo="AVAX/USDC", desde=T0) == [[T0, 10, 11, 9, 10]]
    with pytest.raises(HTTPException) as e:
        velas(simbolo="PEPE/USDC", desde=T0)
    assert e.value.status_code == 404


def test_la_pagina_pide_las_velas_al_abrir_una_posicion():
    """Enchufado de verdad: la tarjeta de la posicion llama al endpoint y dibuja entrada, stop y objetivo."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "ui" / "panel.js").read_text(encoding="utf-8")
    assert "/api/velas?simbolo=" in js and "graficoPosicion(p)" in js
    for linea in ('"objetivo"', '"entrada"', '"stop"'):
        assert linea in js


def test_sin_velas_cerradas_no_se_arma_ninguna(tmp_path):
    """Revision del 01/10: sin cerradas, la "en curso" saldria de minutos de dos dias antes de la entrada."""
    filas = [("AVAX/USDC", "1m", T0 - 12 * H4 + m * 60_000, 10, 11, 9, 10, 1) for m in range(5)]
    assert historial.velas_posicion(_principal(tmp_path, filas), "AVAX/USDC", T0) == []
