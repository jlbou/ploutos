"""El juez de las 72 h de papel (`portfolio/audit.py`).

Un juez que siempre dice "coherente" no juzga nada. Por eso cada comprobacion
tiene aqui su prueba de mutacion: se parte de una base de papel sana, generada
con el simulador de verdad, se ROMPE a proposito una cosa, y la comprobacion
que la vigila tiene que ponerse en rojo.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core.config import load_settings
from portfolio import store
from portfolio.audit import Audit, PaperRecord, expected_outcome
from portfolio.paper import Bar, PaperBroker, PaperLedger
from strategy.candidates import make_decision_id
from tests.risk_fixtures import INSTRUMENTS

BAR = 4 * 60 * 60 * 1000
T0 = 1_790_035_200_000          # 22/09/2026 00:00 UTC: todo cae en el mismo dia
SETUP = "pullback_trend"


def ts(i: int) -> int:
    return T0 + i * BAR


def b(i, o, h, low, c) -> Bar:
    return Bar(ts_open_ms=ts(i), open=o, high=h, low=low, close=c)


# ETH: se crea en la vela 0, se llena en la 1, cierra en objetivo en la 2.
# SOL: se crea en la vela 1 y el precio no vuelve nunca: caduca en la 4.
BARS = {
    "ETH/USDC": [
        b(0, 100.5, 101, 100.2, 100.5),
        b(1, 100.5, 102, 99.5, 101),
        b(2, 101, 107, 100.5, 106.5),
        *[b(i, 106.5, 107, 106, 106.5) for i in range(3, 6)],
    ],
    "SOL/USDC": [b(i, 52, 52.5, 51, 52) for i in range(6)],
}
ORDERS = {
    0: [("ETH/USDC", 0.15, 100.0, 97.0, 106.0)],
    1: [("SOL/USDC", 0.3, 50.0, 48.5, 53.0)],
}
# Con que se decidio cada vela: spread y profundidad, y la correlacion medida
# el 22/09/2026 entre ETH y SOL (0,84: alta, pero una sola pareja cabe).
MERCADO = [("ETH/USDC", 0.02, 500_000.0), ("SOL/USDC", 0.03, 300_000.0)]
CORRELACIONES = [("ETH/USDC", "SOL/USDC", 0.84)]


@pytest.fixture
def conn(tmp_path: Path):
    """Una base de papel SANA, escrita vela a vela por el simulador real."""
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    for i in range(6):
        marks = {}
        for sym, velas in BARS.items():
            broker.on_bar(sym, velas[i])
            marks[sym] = velas[i].close
        ledger.record(ts(i), marks)
        filas = []
        for sym, qty, lim, stop, tgt in ORDERS.get(i, []):
            did = make_decision_id(sym, SETUP, ts(i))
            assert broker.submit(did, sym, qty, lim, stop, tgt, SETUP, ts(i))
            filas += [(did, sym, SETUP, "candidate", "..."), (did, sym, SETUP, "submitted", "...")]
        store.save_step(c, broker, ledger, "4h", ts(i), filas,
                        market=MERCADO, correlations=CORRELACIONES,
                        usdc=(0.99986, 0.99995, -0.014, "medido"))
    yield c
    c.close()


def auditar(conn: sqlite3.Connection) -> Audit:
    return Audit(
        record=PaperRecord.from_db(conn, "4h"), bars=BARS, instruments=INSTRUMENTS,
        settings=load_settings(), timeframe_ms=BAR,
    )


def meter_orden(conn, sym, i, qty, lim, stop, tgt, state="pending"):
    did = make_decision_id(sym, SETUP, ts(i))
    with conn:
        conn.execute(
            "INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?,?,?,?)",
            (did, sym, qty, lim, stop, tgt, SETUP, ts(i), state, 0),
        )
        for kind in ("candidate", "submitted"):
            conn.execute(
                "INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind,"
                " detail) VALUES (?,?,?,?,?,?)", (ts(i), did, sym, SETUP, kind, "..."),
            )


def meter_operacion(conn, sym, i, pnl, reason="stop"):
    with conn:
        conn.execute(
            "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"d-falsa-{sym}-{i}-{pnl}", sym, SETUP, "baseline", 1.0, 10.0, 10.0 + pnl,
             9.0, 13.0, ts(i), ts(i), reason, 0.0, 0.0, 0, 0.0, 0.0, pnl, pnl),
        )


# --------------------------------------------------------------------------
# La base sana pasa, y no porque no mire nada
# --------------------------------------------------------------------------


def test_una_base_sana_pasa_todo(conn):
    checks = auditar(conn).run()
    fallidas = {c.nombre: c.fallos for c in checks if not c.ok}
    assert fallidas == {}
    assert all(c.comprobados > 0 for c in checks), "una comprobacion que no mira nada"


def test_el_escenario_es_el_que_dice_ser(conn):
    a = auditar(conn)
    estados = {o["symbol"]: o["state"] for o in a.record.orders}
    assert estados == {"ETH/USDC": "filled", "SOL/USDC": "expired"}
    assert [t["reason"] for t in a.record.trades] == ["target"]


# --------------------------------------------------------------------------
# Mutaciones: cada una rompe UNA cosa y su comprobacion se pone en rojo
# --------------------------------------------------------------------------


def _sql(*sentencias):
    def mutar(conn):
        with conn:
            for s in sentencias:
                conn.execute(s)
    return mutar


MUTACIONES = {
    "vela sin procesar": (
        _sql(f"DELETE FROM paper_equity WHERE ts_ms = {ts(3)}"), "continuidad"),
    "vela reprocesada": (
        _sql("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail)"
             " SELECT ts_ms, decision_id, symbol, setup, kind, detail FROM paper_decisions"
             " WHERE kind = 'submitted' LIMIT 1"), "sin_reprocesar"),
    "orden sin journal": (
        _sql("DELETE FROM paper_decisions WHERE kind = 'submitted' AND symbol = 'SOL/USDC'"),
        "trazabilidad"),
    "operacion sin orden": (
        _sql("DELETE FROM paper_orders WHERE symbol = 'ETH/USDC'"), "trazabilidad"),
    "stop donde fue objetivo": (
        _sql("UPDATE paper_trades SET reason = 'stop', exit_price = 97.0"), "resimulacion"),
    "caducada guardada como viva": (
        _sql("UPDATE paper_orders SET state = 'pending' WHERE symbol = 'SOL/USDC'"),
        "resimulacion"),
    "P&L amanyado": (
        _sql("UPDATE paper_trades SET net_pnl_usd = net_pnl_usd + 0.01"), "contabilidad"),
    "comision olvidada": (
        _sql("UPDATE paper_trades SET entry_fee_usd = 0"), "contabilidad"),
    "equity inflado con posicion abierta": (
        _sql(f"UPDATE paper_equity SET equity_usd = equity_usd + 0.015 WHERE ts_ms = {ts(1)}"),
        "equity"),
    "historia de contadores machacada": (
        _sql(f"UPDATE paper_equity SET pending = 1 WHERE ts_ms = {ts(5)}"), "equity"),
    "par fuera de la whitelist": (
        _sql("UPDATE paper_orders SET symbol = 'LINK/USDC' WHERE symbol = 'SOL/USDC'"),
        "whitelist_y_setups"),
    "demasiado riesgo": (
        _sql("UPDATE paper_orders SET qty = 0.3 WHERE symbol = 'ETH/USDC'"), "tamanyo"),
    "cantidad fuera de lote": (
        _sql("UPDATE paper_orders SET qty = 0.1500005 WHERE symbol = 'ETH/USDC'"), "tamanyo"),
    "cuatro huecos": (
        lambda c: (meter_orden(c, "BTC/USDC", 1, 0.0001, 60000, 59000, 62000),
                   meter_orden(c, "XRP/USDC", 1, 10, 1.0, 0.97, 1.1)), "huecos"),
    "dos cosas en el mismo simbolo": (
        lambda c: meter_orden(c, "ETH/USDC", 1, 0.1, 99.0, 97.0, 105.0), "huecos"),
    "exposicion por encima del 90 %": (
        lambda c: meter_orden(c, "BTC/USDC", 1, 0.0005, 60000, 59990, 60100), "exposicion"),
    "todo al stop por debajo del suelo": (
        lambda c: meter_orden(c, "BTC/USDC", 1, 0.0004, 60000, 1000, 70000), "preventiva"),
    "entrar con el dia perdido": (
        # -4: el dia ya llevaba +0,87 $ del objetivo de ETH, y la regla 10 mira el NETO.
        lambda c: (meter_operacion(c, "DOGE/USDC", 2, -4.0),
                   meter_orden(c, "XRP/USDC", 3, 10, 1.0, 0.97, 1.1)), "limites_diarios"),
    "septima operacion del dia": (
        lambda c: ([meter_operacion(c, s, 2, 0.1, "target") for s in
                    ("BTC/USDC", "XRP/USDC", "DOGE/USDC", "AVAX/USDC", "TRX/USDC", "NEAR/USDC")],
                   meter_orden(c, "XRP/USDC", 3, 10, 1.0, 0.97, 1.1)), "limites_diarios"),
    "entrar en cooldown": (
        lambda c: (meter_operacion(c, "XRP/USDC", 3, -0.4),
                   meter_orden(c, "XRP/USDC", 3, 10, 1.0, 0.97, 1.1)), "cooldowns"),
    "spread por encima del 0,10 %": (
        _sql("UPDATE paper_market SET spread_pct = 0.2 WHERE symbol = 'ETH/USDC'"),
        "spread_y_coste"),
    "objetivo que no paga 3x el coste": (
        _sql("UPDATE paper_orders SET target_price = 100.5 WHERE symbol = 'ETH/USDC'"),
        "spread_y_coste"),
    "tercera correlacionada": (
        lambda c: (
            _sql(f"INSERT INTO paper_correlations VALUES ({ts(1)}, 'BTC/USDC', 'ETH/USDC', 0.9)",
                 f"INSERT INTO paper_correlations VALUES ({ts(1)}, 'BTC/USDC', 'SOL/USDC', 0.9)")(c),
            meter_orden(c, "BTC/USDC", 1, 0.0001, 60000, 59000, 62000),
        ), "correlacion"),
    "entrar con la paridad desconocida": (
        _sql(f"UPDATE paper_usdc SET deviation_pct = NULL WHERE ts_ms = {ts(1)}"),
        "paridad_usdc"),
    "entrar con USDC despegado": (
        _sql(f"UPDATE paper_usdc SET deviation_pct = -2.0 WHERE ts_ms = {ts(0)}"),
        "paridad_usdc"),
    "entrar en CLOSE_ONLY_QUOTA": (
        _sql("INSERT INTO paper_mode_changes (ts_ms, mode, activated, reason, effective_after)"
             f" VALUES ({ts(1)}, 'CLOSE_ONLY_QUOTA', 1, 'cuota agotada', 'CLOSE_ONLY_QUOTA')"),
        "modos"),
    "orden que el motor veto": (
        _sql("INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup, kind, detail)"
             " SELECT ts_ms, decision_id, symbol, setup, 'vetoed', 'regla 4' FROM paper_decisions"
             " WHERE kind = 'submitted' AND symbol = 'ETH/USDC'"), "propone_y_dispone"),
    "operacion de otra cartera": (
        _sql("UPDATE paper_trades SET decider = 'ai'"), "propone_y_dispone"),
    "el baseline llamando a Claude": (
        _sql("INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates)"
             f" VALUES ({ts(0)}, {ts(1)}, 'decision', 'ok', 1, 'ok', 1)"), "propone_y_dispone"),
    "entrar en pausa": (
        lambda c: ([meter_operacion(c, s, 3, -0.4) for s in
                    ("BTC/USDC", "DOGE/USDC", "AVAX/USDC")],
                   meter_orden(c, "XRP/USDC", 3, 10, 1.0, 0.97, 1.1)), "cooldowns"),
}


@pytest.mark.parametrize("nombre", sorted(MUTACIONES))
def test_cada_mutacion_se_detecta(conn, nombre):
    mutar, comprobacion = MUTACIONES[nombre]
    assert getattr(auditar(conn), comprobacion)().ok, "antes de romper, pasa"
    mutar(conn)
    check = getattr(auditar(conn), comprobacion)()
    assert not check.ok, f"'{nombre}' no lo detecta {comprobacion}"


# --------------------------------------------------------------------------
# La re-simulacion independiente respeta las seis suposiciones
# --------------------------------------------------------------------------


def _orden(created=0, lim=100.0, stop=97.0, tgt=106.0):
    return {"decision_id": "d", "limit_price": lim, "stop_price": stop,
            "target_price": tgt, "created_ts_ms": ts(created)}


def test_la_vela_que_crea_la_orden_no_la_llena():
    oc = expected_outcome(_orden(), [b(0, 99, 99, 98, 99)], ts(0))
    assert oc.state == "pending"


def test_stop_y_objetivo_en_la_misma_vela_gana_el_stop():
    velas = [b(1, 100, 110, 96, 100)]
    oc = expected_outcome(_orden(), velas, ts(1))
    assert (oc.state, oc.reason) == ("filled", "stop")


def test_el_hueco_a_la_baja_se_paga():
    velas = [b(1, 100, 101, 99.5, 100), b(2, 95, 96, 94, 95)]
    oc = expected_outcome(_orden(), velas, ts(2))
    assert (oc.reason, oc.exit_price) == ("stop", 95)


def test_el_hueco_al_alza_no_se_cobra():
    velas = [b(1, 100, 101, 99.5, 100), b(2, 110, 111, 109, 110)]
    oc = expected_outcome(_orden(), velas, ts(2))
    assert (oc.reason, oc.exit_price) == ("target", 106.0)


def test_caduca_a_la_tercera_vela_sin_llenarse():
    velas = [b(i, 101, 102, 100.5, 101) for i in range(1, 4)]
    assert expected_outcome(_orden(), velas[:2], ts(2)).state == "pending"
    assert expected_outcome(_orden(), velas, ts(3)).state == "expired"


# --------------------------------------------------------------------------
# Sin contexto guardado: ni fallo ni aprobado
# --------------------------------------------------------------------------


def test_contexto_sin_correlaciones_se_audita_como_decidio_el_motor(conn):
    """Con el libro guardado pero sin ninguna correlacion medida, todo cuenta
    como correlacionado (decision del propietario del 22/09/2026), y se AVISA."""
    with conn:
        conn.execute("DELETE FROM paper_correlations")
    check = auditar(conn).correlacion()
    assert check.ok, "SOL entro con UNA sola viva (ETH): cabe"
    assert check.comprobados == 2 and check.sin_datos == 0
    assert check.notas and "correlacionadas" in check.notas[0]


def test_sin_medir_cuenta_como_correlacionada(conn):
    """Una tercera orden con DOS vivas sin correlacion medida: el motor la
    habria vetado, y si esta en la base el juez tiene que cantarlo."""
    with conn:
        conn.execute("DELETE FROM paper_correlations")
    meter_orden(conn, "BTC/USDC", 1, 0.0001, 60000, 59000, 62000)
    assert not auditar(conn).correlacion().ok


def test_sin_contexto_no_se_da_por_bueno(conn):
    """Las ordenes de antes de guardar el contexto (22/09/2026) no se pueden
    comprobar contra las reglas 15 y 16. Se cuentan como SIN DATOS: si
    contaran como cumplidas, el juez aprobaria lo que no ha mirado."""
    with conn:
        conn.execute("DROP TABLE paper_market")
        conn.execute("DROP TABLE paper_correlations")
        conn.execute("DROP TABLE paper_usdc")
    a = auditar(conn)
    for check in (a.spread_y_coste(), a.correlacion(), a.paridad_usdc()):
        assert check.ok
        assert check.comprobados == 0
        assert check.sin_datos == 2


# --------------------------------------------------------------------------
# El analista (fase 3, pieza 10): la cartera de la IA
# --------------------------------------------------------------------------

# En cada vela con orden, el analista vio su candidato y uno mas (BTC), eligio
# el suyo con multiplicador 1,0 y descarto BTC.
OTRO = "BTC/USDC"


def _llamada(i: int, did: str, otro: str) -> tuple[dict, list[dict]]:
    entrada = {
        "ts": ts(i), "mode": "NORMAL", "limits": {}, "memory": [],
        "portfolio": {"open_positions": []},
        "candidates": [{"cid": did}, {"cid": otro}],
    }
    llamada = {
        "ts_ms": ts(i), "called_ms": ts(i) + BAR, "kind": "decision", "outcome": "ok",
        "valid": 1, "reason": "ok", "n_candidates": 2,
        "prompt": json.dumps(entrada) + "\nDecide sobre cada candidato.",
    }
    decisiones = [
        {"ref": did, "type": "open", "size_multiplier": 1.0, "confidence": 0.7,
         "reasons": "[]", "risks": "[]", "executed": 1},
        {"ref": otro, "type": "skip", "size_multiplier": None, "confidence": 0.4,
         "reasons": "[]", "risks": "[]", "executed": 1},
    ]
    return llamada, decisiones


@pytest.fixture
def conn_ia(tmp_path: Path):
    """La misma base sana, pero de la cartera de la IA y con su journal."""
    c = store.connect(tmp_path / "paper-ia.db")
    store.migrate(c)
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    for i in range(6):
        marks = {}
        for sym, velas in BARS.items():
            broker.on_bar(sym, velas[i])
            marks[sym] = velas[i].close
        ledger.record(ts(i), marks)
        filas, llamadas = [], []
        for sym, qty, lim, stop, tgt in ORDERS.get(i, []):
            did = make_decision_id(sym, SETUP, ts(i))
            assert broker.submit(did, sym, qty, lim, stop, tgt, SETUP, ts(i))
            filas += [(did, sym, SETUP, "candidate", "..."), (did, sym, SETUP, "submitted", "...")]
            llamadas.append(_llamada(i, did, make_decision_id(OTRO, SETUP, ts(i))))
        store.save_step(c, broker, ledger, "4h", ts(i), filas, decider="ai",
                        market=MERCADO, correlations=CORRELACIONES,
                        usdc=(0.99986, 0.99995, -0.014, "medido"), ai_calls=llamadas)
    yield c
    c.close()


def auditar_ia(conn: sqlite3.Connection, settings=None) -> Audit:
    return Audit(
        record=PaperRecord.from_db(conn, "4h"), bars=BARS, instruments=INSTRUMENTS,
        settings=settings or load_settings(), timeframe_ms=BAR, decider="ai",
    )


ETH = make_decision_id("ETH/USDC", SETUP, ts(0))


def test_la_cartera_de_la_ia_sana_pasa_todo(conn_ia):
    checks = auditar_ia(conn_ia).run()
    assert {c.nombre: c.fallos for c in checks if not c.ok} == {}
    assert all(c.comprobados > 0 for c in checks), "una comprobacion que no mira nada"
    assert len(checks) == len(auditar(conn_ia).run()) + 3, "las tres del analista, ademas"


def test_el_baseline_no_audita_al_analista(conn):
    """Las del analista solo van en la cartera de la IA; en la del baseline
    basta con que no haya ni una llamada (lo mira `propone_y_dispone`)."""
    nombres = {c.nombre for c in auditar(conn).run()}
    assert not any("analista" in n for n in nombres)


def _llamadas_extra(n: int, desde_ms: int, paso_ms: int, kind: str = "probe"):
    def mutar(conn):
        with conn:
            conn.executemany(
                "INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason,"
                " n_candidates) VALUES (?,?,?,?,?,?,?)",
                [(desde_ms + k * paso_ms, desde_ms + k * paso_ms, kind, "error", 0, "x", 0)
                 for k in range(n)],
            )
    return mutar


MUTACIONES_IA = {
    "orden que el analista no eligio": (
        _sql(f"UPDATE ai_decisions SET type = 'skip', size_multiplier = NULL WHERE ref = '{ETH}'"),
        "propone_y_dispone"),
    "multiplicador no aplicado": (
        _sql(f"UPDATE ai_decisions SET size_multiplier = 0.5 WHERE ref = '{ETH}'"),
        "propone_y_dispone"),
    "multiplicador que agranda": (
        _sql("UPDATE ai_decisions SET size_multiplier = 1.5 WHERE type = 'open'"),
        "analista_multiplicador"),
    "open sin multiplicador": (
        _sql("UPDATE ai_decisions SET size_multiplier = NULL WHERE type = 'open'"),
        "analista_multiplicador"),
    "ref inventada aceptada": (
        _sql("INSERT INTO ai_decisions VALUES (1, 'd-inventada', 'skip', NULL, 0.5, '[]', '[]', 1)"),
        "analista_referencias"),
    "cierre de una posicion que no existe": (
        _sql("INSERT INTO ai_decisions VALUES (1, 'p-fantasma', 'close', NULL, 0.5, '[]', '[]', 0)"),
        "analista_referencias"),
    "candidato sin decision apuntada": (
        _sql("DELETE FROM ai_decisions WHERE type = 'skip'"), "analista_referencias"),
    "decisiones de una salida invalida": (
        _sql("UPDATE ai_calls SET valid = 0 WHERE id = 1"), "analista_referencias"),
    "numero de candidatos que no cuadra": (
        _sql("UPDATE ai_calls SET n_candidates = 5 WHERE id = 1"), "analista_referencias"),
    "entrada sin guardar": (
        _sql("UPDATE ai_calls SET prompt = NULL WHERE id = 1"), "analista_referencias"),
    "nueve llamadas en 5 h": (
        _llamadas_extra(7, ts(2) + 60_000, 60_000), "analista_presupuesto"),
    "decidir en CLOSE_ONLY_QUOTA": (
        _sql("INSERT INTO paper_mode_changes (ts_ms, mode, activated, reason, effective_after)"
             f" VALUES ({ts(0)}, 'CLOSE_ONLY_QUOTA', 1, 'cuota', 'CLOSE_ONLY_QUOTA')"),
        "analista_presupuesto"),
    "presupuesto agotado sin QUOTA": (
        _sql("INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates)"
             f" VALUES ({ts(3)}, {ts(4)}, 'decision', 'skipped_budget', 0, 'regla 18', 1)"),
        "analista_presupuesto"),
    "no llamar por cuota sin estar en QUOTA": (
        _sql("INSERT INTO ai_calls (ts_ms, called_ms, kind, outcome, valid, reason, n_candidates)"
             f" VALUES ({ts(3)}, {ts(4)}, 'decision', 'skipped_quota', 0, 'cuota', 1)"),
        "analista_presupuesto"),
}


@pytest.mark.parametrize("nombre", sorted(MUTACIONES_IA))
def test_cada_mutacion_del_analista_se_detecta(conn_ia, nombre):
    mutar, comprobacion = MUTACIONES_IA[nombre]
    assert getattr(auditar_ia(conn_ia), comprobacion)().ok, "antes de romper, pasa"
    mutar(conn_ia)
    check = getattr(auditar_ia(conn_ia), comprobacion)()
    assert not check.ok, f"'{nombre}' no lo detecta {comprobacion}"


def test_el_tope_diario_se_cuenta_por_dia_utc(conn_ia):
    """Con 8 por ventana de 5 h, pasar de 40 en un dia es casi imposible: el tope
    diario se prueba bajandolo. Tres llamadas el mismo dia con tope 2."""
    base = load_settings()
    settings = base.model_copy(update={"claude": base.claude.model_copy(update={"max_calls_per_day": 2})})
    assert auditar_ia(conn_ia, settings).analista_presupuesto().ok, "dos llamadas: caben"
    _llamadas_extra(1, ts(5), 60_000)(conn_ia)
    check = auditar_ia(conn_ia, settings).analista_presupuesto()
    assert any("del dia" in f for f in check.fallos)


def test_cuota_se_lee_del_journal_con_su_momento(conn_ia):
    """Entrar mientras se procesa la vela 2 (marca de la vela) y salir por una
    sonda justo despues de procesarla (entre velas): la vela 2 empieza en NORMAL
    y termina en QUOTA; la 3 ya empieza en NORMAL."""
    with conn_ia:
        conn_ia.executemany(
            "INSERT INTO paper_mode_changes (ts_ms, mode, activated, reason, effective_after)"
            " VALUES (?, 'CLOSE_ONLY_QUOTA', ?, 'x', 'x')",
            [(ts(2), 1), (ts(3) + 1000, 0)],
        )
    a = auditar_ia(conn_ia)
    assert (a.cuota_al_empezar[ts(2)], a.cuota_al_terminar[ts(2)]) == (False, True)
    assert (a.cuota_al_empezar[ts(3)], a.cuota_al_terminar[ts(3)]) == (False, False)
    assert a.solo_cierre[ts(2)] and not a.solo_cierre[ts(3)]


def test_en_la_vela_que_llena_el_objetivo_no_cuenta():
    """Suposicion 7 (revision del 15/10/2026), igual que el simulador (test_paper)."""
    velas = [b(1, 101, 107, 99.5, 103), b(2, 103, 106.5, 102, 104)]
    assert expected_outcome(_orden(), velas[:1], ts(1)).state == "filled"          # abierta, sin objetivo
    assert expected_outcome(_orden(), velas[:1], ts(1)).reason is None
    oc = expected_outcome(_orden(), velas, ts(2))
    assert (oc.reason, oc.closed_ts_ms) == ("target", ts(2))


def test_el_simulador_y_el_juez_dicen_lo_mismo_en_la_vela_que_llena():
    """La prueba de oro de este caso: el PaperBroker y la re-simulacion independiente, con las mismas velas."""
    from portfolio.paper import PaperBroker
    from tests.risk_fixtures import INSTRUMENTS
    velas = [b(1, 101, 107, 99.5, 103), b(2, 103, 106.5, 102, 104)]
    br = PaperBroker(INSTRUMENTS)
    br.submit("d", "ETH/USDC", 0.15, 100.0, 97.0, 106.0, "pullback_trend", ts(0))
    cerradas = [t for v in velas for t in br.on_bar("ETH/USDC", v)]
    oc = expected_outcome(_orden(), velas, ts(2))
    assert len(cerradas) == 1 and cerradas[0].reason.value == oc.reason
    assert cerradas[0].closed_ts_ms == oc.closed_ts_ms and cerradas[0].exit_price == oc.exit_price
