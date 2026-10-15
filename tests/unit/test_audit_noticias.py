"""El juez de papel con noticias (pieza 4d): ventas a mercado y cancelaciones por una flag.

Una base de papel escrita con el simulador de VERDAD y en el MISMO orden que el bucle (vela,
noticias, equity). El juez tiene que darla por buena con las noticias, y suspenderla sin ellas
o si la venta no es la que tocaba.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import load_settings
from features.news import Anuncio, bases_de, flags
from portfolio import store
from portfolio.audit import Audit, PaperRecord
from portfolio.paper import Bar, ExitReason, PaperBroker, PaperLedger
from strategy.candidates import make_decision_id
from tests.risk_fixtures import INSTRUMENTS

BAR = 4 * 60 * 60 * 1000
T0 = 1_790_035_200_000
SETUP = "pullback_trend"
BASES = bases_de(load_settings().whitelist)
MERCADO = [("ETH/USDC", 0.02, 500_000.0), ("SOL/USDC", 0.03, 300_000.0)]
CORR = [("ETH/USDC", "SOL/USDC", 0.84)]


def ts(i):
    return T0 + i * BAR


def b(i, o, h, low, c):
    return Bar(ts(i), o, h, low, c)


# ETH: orden en la vela 0, se llena en la 1 (sin tocar stop ni objetivo), y a mitad de la 1 sale
# un deslistado: se vende al CIERRE de la 1, a 101. SOL: orden en la 1 que no se llena; a mitad
# de la 2 sale un aviso de volatilidad: se cancela en la 2.
BARS = {
    "ETH/USDC": [b(0, 100.5, 101, 100.2, 100.5), b(1, 100.5, 102, 99.5, 101),
                 *[b(i, 101, 101.5, 100.5, 101) for i in range(2, 6)]],
    "SOL/USDC": [b(i, 52, 52.5, 51, 52) for i in range(6)],
}
ORDERS = {0: [("ETH/USDC", 0.15, 100.0, 97.0, 106.0)], 1: [("SOL/USDC", 0.3, 50.0, 48.5, 53.0)]}
NOTICIAS = [Anuncio("del-eth", ts(1) + BAR // 2, "OKX to delist ETH"),
            Anuncio("vol-sol", ts(2) + BAR // 2, "Announcement on the Price Volatility of Solana (SOL)")]
FLAGS = flags(NOTICIAS, BASES)


def escribir(tmp_path: Path, noticias=FLAGS):
    """Como el bucle: vela -> noticias (cancelar / vender) -> equity -> ordenes nuevas."""
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    for i in range(6):
        marks, filas = {}, []
        for sym, velas in BARS.items():
            broker.on_bar(sym, velas[i])
            marks[sym] = velas[i].close
        decision = ts(i) + BAR
        for sym in sorted(BARS):
            base = sym.split("/")[0]
            activas = [f for f in noticias if f.moneda == base and f.activa(decision)]
            if activas:
                for o in broker.pending:
                    if o.symbol == sym:
                        filas.append((o.decision_id, sym, None, "cancelled", "noticia"))
                broker.cancel_pending(sym)
            if any(str(f.gravedad) == "critica" for f in activas):
                broker.close_at_market(sym, BARS[sym][i])
        ledger.record(ts(i), marks)
        for sym, qty, lim, stop, tgt in ORDERS.get(i, []):
            did = make_decision_id(sym, SETUP, ts(i))
            assert broker.submit(did, sym, qty, lim, stop, tgt, SETUP, ts(i))
            filas += [(did, sym, SETUP, "candidate", "..."), (did, sym, SETUP, "submitted", "...")]
        store.save_step(c, broker, ledger, "4h", ts(i), filas, market=MERCADO, correlations=CORR,
                        usdc=(0.99986, 0.99995, -0.014, "medido"))
    return c


def auditar(conn, noticias=FLAGS):
    return Audit(record=PaperRecord.from_db(conn, "4h"), bars=BARS, instruments=INSTRUMENTS,
                 settings=load_settings(), timeframe_ms=BAR, noticias=noticias)


def fallos(audit):
    return {c.nombre: c.fallos for c in audit.run() if not c.ok}


@pytest.fixture
def conn(tmp_path):
    c = escribir(tmp_path)
    yield c
    c.close()


def test_el_escenario_es_el_que_dice(conn):
    [t] = conn.execute("SELECT * FROM paper_trades").fetchall()
    assert (t["symbol"], t["reason"], t["exit_price"], t["closed_ts_ms"]) == ("ETH/USDC", "news", 101, ts(1))
    assert not t["exit_was_maker"]
    sol = conn.execute("SELECT state FROM paper_orders WHERE symbol = 'SOL/USDC'").fetchone()[0]
    assert sol == "cancelled"


def test_con_las_noticias_el_juez_lo_da_por_bueno(conn):
    assert fallos(auditar(conn)) == {}


def test_sin_las_noticias_el_juez_suspende_la_venta_y_la_cancelacion(conn):
    f = fallos(auditar(conn, noticias=None))
    todos = " ".join(x for lista in f.values() for x in lista)
    assert "ETH" in todos.upper() and "cancelada sin modo de solo cierre ni noticia" in todos


def test_una_venta_en_otra_vela_se_detecta(conn):
    with conn:
        conn.execute("UPDATE paper_trades SET closed_ts_ms = ?, exit_price = 101.0", (ts(2),))
    assert "lo guardado coincide con re-simular contra las velas" in fallos(auditar(conn))


def test_una_entrada_que_debia_cancelarse_y_no_se_cancelo_se_detecta(conn):
    with conn:
        conn.execute("UPDATE paper_orders SET state = 'pending' WHERE symbol = 'SOL/USDC'")
    f = fallos(auditar(conn))
    assert any("por una noticia" in x for lista in f.values() for x in lista)


def test_la_venta_por_noticia_paga_taker(conn):
    with conn:
        conn.execute("UPDATE paper_trades SET exit_was_maker = 1")
    assert "comisiones, P&L y R de cada operacion" in fallos(auditar(conn))


def test_un_aviso_levantado_no_obliga_a_nada(tmp_path):
    """Si el propietario levanta la flag antes, no hay venta ni cancelacion que exigir."""
    clave = FLAGS[0].clave
    sin_eth = flags(NOTICIAS, BASES, levantadas=frozenset({clave}))
    c = escribir(tmp_path, noticias=sin_eth)
    assert c.execute("SELECT COUNT(*) FROM paper_trades WHERE reason = ?", (str(ExitReason.NEWS),)).fetchone()[0] == 0
    assert fallos(auditar(c, noticias=sin_eth)) == {}
    c.close()


# --- con los comandos de Telegram: en HALTED no se vende ni por una noticia -----------------

from notify.comandos import Comando, Orden  # noqa: E402


def auditar_con(conn, comandos):
    return Audit(record=PaperRecord.from_db(conn, "4h"), bars=BARS, instruments=INSTRUMENTS,
                 settings=load_settings(), timeframe_ms=BAR, noticias=FLAGS, comandos=comandos)


def test_en_halted_el_juez_no_espera_la_venta_por_noticia(conn):
    """Con un /kill antes de la decision de la vela 1, esa venta no tocaba: el juez la suspende."""
    kill = [Comando(1, ts(1) + BAR // 2, Orden.KILL, "/kill")]
    assert "lo guardado coincide con re-simular contra las velas" in fallos(auditar_con(conn, kill))


def test_un_kill_posterior_no_cambia_nada(conn):
    kill = [Comando(1, ts(6) + BAR, Orden.KILL, "/kill")]
    assert fallos(auditar_con(conn, kill)) == {}
