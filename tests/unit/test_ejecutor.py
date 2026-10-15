"""El ejecutor entero (`execution/ejecutor.py`) contra un OKX simulado (`tests/okx_simulado.py`) y bases temporales.

Cada test es un trozo de la vida del demo: copiar una orden de la cartera de la IA, llenarse, saltar la OCO, el
llenado a medias, la salida por noticias, el suelo, la pausa, la red caida, la caducidad. Sin red ni claves.
"""

from __future__ import annotations

from pathlib import Path

import ccxt
import pytest

from core.config import load_settings
from core.modes import Mode
from execution import ids
from execution import store as db
from execution.ejecutor import PASADA_MS, Ejecutor
from portfolio import store as papel_store
from risk.types import Instrument
from tests.okx_simulado import MERCADOS_DEMO, OkxSimulado
from tests.risk_fixtures import independent_pairs

S = load_settings()
TF = 4 * 3600_000
T0 = 1_790_352_000_000                         # 25/09/2026 16:00 UTC: apertura de la vela que decide
DECIDE = T0 + TF + 5_000                       # la cartera de papel decide al cierre
DEMO_SALDOS = {"USDC": 5000.0, "BTC": 1.0, "ETH": 1.0, "XRP": 50000.0, "USD": 5000.0}
PRECIOS = {"BTC/USDC": 84400.0, "ETH/USDC": 2650.0, "SOL/USDC": 117.8, "DOGE/USDC": 0.0914, "NEAR/USDC": 4.65,
           "XRP/USDC": 2.5, "AVAX/USDC": 25.0, "TRX/USDC": 0.15}
OPERABLES = ("BTC/USDC", "ETH/USDC", "SOL/USDC", "DOGE/USDC")
ETH = "d-20260925T1600-eth-pb"
# Una orden de papel de ETH con precios al tick del mercado REAL (0,01) y ~0,50 $ de riesgo.
ETH_PAPEL = dict(qty=0.005736, limit_price=2640.37, stop_price=2553.21, target_price=2860.55)


def instrumentos():
    f = S.exchange.fees
    return {s: Instrument(s, tick, lote, minimo, f.maker_pct / 100, f.taker_pct / 100)
            for s, (tick, lote, minimo) in MERCADOS_DEMO.items()}


class Escena:
    def __init__(self, tmp_path, manual=None):
        self.ahora = [T0 + TF - 60_000]
        self.ok = OkxSimulado(DEMO_SALDOS, PRECIOS, self.ahora)
        self.papel_db = tmp_path / "ploutos-paper-ai.db"
        self.papel = papel_store.connect(self.papel_db)
        papel_store.migrate(self.papel)
        self.exec_db = tmp_path / "ploutos-exec.db"
        self.manual = manual if manual is not None else [None]
        self.nuevo_ejecutor()

    def nuevo_ejecutor(self):
        """Tambien sirve de "reinicio del servicio": lee lo guardado."""
        self.conn = db.conectar(self.exec_db)
        db.migrar(self.conn)
        self.ej = Ejecutor(ex=self.ok, settings=S, conn=self.conn, papel_db=self.papel_db,
                           instrumentos=instrumentos(), operables=OPERABLES, tf_ms=TF,
                           manuales=lambda _ms: self.manual[0], reloj=lambda: self.ahora[0])

    def orden_papel(self, did=ETH, simbolo="ETH/USDC", creada=T0, estado="pending", **precios):
        p = {**ETH_PAPEL, **precios}
        with self.papel:
            self.papel.execute(
                "INSERT OR REPLACE INTO paper_orders (decision_id, symbol, qty, limit_price, stop_price, target_price,"
                " setup, created_ts_ms, state, bars_waited) VALUES (?,?,?,?,?,?,?,?,?,0)",
                (did, simbolo, p["qty"], p["limit_price"], p["stop_price"], p["target_price"], "pullback_trend",
                 creada, estado))
            self.papel.executemany("INSERT OR REPLACE INTO paper_market VALUES (?,?,?,?)",
                                   [(creada, s, 0.01, 50_000.0) for s in S.whitelist])
            self.papel.executemany("INSERT OR REPLACE INTO paper_correlations VALUES (?,?,?,?)",
                                   [(creada, a, b, c) for (a, b), c in independent_pairs().items()])
            self.papel.execute("INSERT OR REPLACE INTO paper_usdc VALUES (?, 1.0, NULL, 0.01, 'A')", (creada,))

    def cierre_papel(self, did, motivo, cerrada):
        with self.papel:
            self.papel.execute(
                "INSERT INTO paper_trades (decision_id, symbol, setup, decider, qty, entry_price, exit_price,"
                " stop_price, target_price, opened_ts_ms, closed_ts_ms, reason, entry_fee_usd, exit_fee_usd,"
                " exit_was_maker, mae_pct, mfe_pct, net_pnl_usd, r_multiple)"
                " VALUES (?, 'ETH/USDC', 'pullback_trend', 'ai', 1, 1, 1, 1, 1, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0)",
                (did, T0, cerrada, motivo))

    def vuelta(self, mas_ms=0):
        self.ahora[0] += mas_ms
        return self.ej.vuelta()

    def pasada(self):
        """Una vuelta con la conciliacion completa (han pasado 5 min)."""
        inf = self.vuelta(PASADA_MS)
        assert inf.pasada
        return inf

    def ultima_pasada(self):
        return db.ultima_pasada(self.conn)


@pytest.fixture
def e(tmp_path):
    esc = Escena(tmp_path)
    esc.vuelta()                    # arranque: la foto, antes de que la cartera de papel decida nada
    esc.ahora[0] = DECIDE
    return esc


# --- La foto y el equity -------------------------------------------------------------------------------------


def test_el_bot_cuenta_50_dolares_y_no_los_5000_del_demo(e):
    f = db.foto(e.conn)
    assert f is not None and f[1] == S.capital.initial_capital_usd
    inf = e.vuelta()
    assert inf.equity.equity_usd == pytest.approx(50.0) and inf.equity.is_reliable
    assert e.ej.modos.effective is Mode.NORMAL


# --- Copiar una orden ----------------------------------------------------------------------------------------


def test_una_orden_de_papel_se_copia_con_los_ticks_del_demo_y_su_stop_adjunto(e):
    e.orden_papel()
    e.vuelta()
    o = e.ok.orden(ids.cl_ord_id(ETH))
    assert o is not None and o["ordType"] == "post_only" and o["tradeQuoteCcy"] == "USDC"
    assert float(o["px"]) == 2640.0, "entrada al tick del demo (1 $), hacia abajo"
    assert float(o["sz"]) == pytest.approx(ETH_PAPEL["qty"]), "la MISMA cantidad que el papel"
    (adj,) = o["attachAlgoOrds"]
    assert adj["attachAlgoClOrdId"] == ids.algo_cl_ord_id(ETH)
    assert float(adj["slTriggerPx"]) == 2554.0 and float(adj["tpTriggerPx"]) == 2861.0, "al tick, hacia arriba"
    assert ETH in db.tratadas(e.conn) and [x.decision_id for x in db.entradas(e.conn)] == [ETH]
    e.vuelta(15_000)
    assert len([x for x in e.ok.ordenes if x["clOrdId"] == ids.cl_ord_id(ETH)]) == 1, "una sola vez"


def test_lo_que_no_se_opera_en_el_demo_se_omite(e):
    near = "d-20260925T1600-near-pb"
    e.orden_papel(near, "NEAR/USDC", limit_price=4.6, stop_price=4.45, target_price=5.0, qty=3.2)
    e.vuelta()
    assert e.ok.orden(ids.cl_ord_id(near)) is None
    fila = e.conn.execute("SELECT que, motivo FROM exec_tratadas WHERE decision_id = ?", (near,)).fetchone()
    assert fila["que"] == "omitida" and "no se opera en el demo" in fila["motivo"]


def test_el_motor_del_demo_veta_sin_paridad(e):
    e.orden_papel()
    with e.papel:
        e.papel.execute("UPDATE paper_usdc SET deviation_pct = NULL WHERE ts_ms = ?", (T0,))
    e.vuelta()
    assert e.ok.orden(ids.cl_ord_id(ETH)) is None
    motivo = e.conn.execute("SELECT motivo FROM exec_tratadas WHERE decision_id = ?", (ETH,)).fetchone()[0]
    assert "regla 17" in motivo


# --- Llenado, OCO y cierre -----------------------------------------------------------------------------------


def test_llenada_entera_la_conciliacion_la_pasa_a_posicion_y_cuadra(e):
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    [p] = db.posiciones(e.conn)
    assert p.decision_id == ETH and p.cantidad == pytest.approx(ETH_PAPEL["qty"]) and p.entrada == 2640.0
    assert db.entradas(e.conn) == []
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]
    assert e.ok.oco(ids.algo_cl_ord_id(ETH))["state"] == "live", "la OCO adjunta, de OKX"
    assert not any(n == "post_algo" for n, _ in e.ok.llamadas), "no se crea una OCO propia"
    e.pasada()      # sin movimientos: ahora si se compara el USDC (comision de entrada incluida)
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]


def test_salta_el_objetivo_y_se_cierra_con_el_precio_de_verdad(e):
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.ok.saltar(ids.algo_cl_ord_id(ETH), "tp")
    e.pasada()
    fila = e.conn.execute("SELECT * FROM exec_cierres WHERE decision_id = ?", (ETH,)).fetchone()
    assert fila["motivo"] == "tp" and fila["salida"] == 2861.0 and fila["salida_estimada"] == 0
    q = ETH_PAPEL["qty"]
    assert fila["pnl_usd"] == pytest.approx((2861.0 - 2640.0) * q - 2640.0 * q * 0.001 - 2861.0 * q * 0.002)
    e.pasada()
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]
    assert e.vuelta().equity.equity_usd == pytest.approx(50.0 + fila["pnl_usd"])


# --- El llenado a medias -------------------------------------------------------------------------------------


def test_a_medias_se_cancela_el_resto_al_momento_y_la_oco_cubre_lo_llenado(e):
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH), 0.002)
    e.vuelta(15_000)                 # una vuelta corta, sin conciliacion: lo urgente
    o = e.ok.orden(ids.cl_ord_id(ETH))
    assert o["state"] == "canceled"
    assert float(e.ok.oco(ids.algo_cl_ord_id(ETH))["sz"]) == pytest.approx(0.002)
    e.pasada()
    [p] = db.posiciones(e.conn)
    assert p.cantidad == pytest.approx(0.002) and db.entradas(e.conn) == []
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]
    e.pasada()
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]


# --- La salida por noticias (decision 4 del 02/10) -----------------------------------------------------------


def test_cerrada_en_papel_por_noticias_el_demo_cancela_la_oco_y_vende(e):
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.cierre_papel(ETH, "news", DECIDE + TF)
    e.vuelta(15_000)
    assert e.ok.oco(ids.algo_cl_ord_id(ETH))["state"] == "canceled"
    venta = e.ok.orden(ids.cl_ord_id_salida(ETH))
    assert venta["ordType"] == "market" and venta["side"] == "sell" and venta["state"] == "filled"
    assert e.ok.saldos["ETH"] == pytest.approx(1.0), "vendido justo lo del bot"
    e.pasada()
    fila = e.conn.execute("SELECT motivo, salida_estimada FROM exec_cierres WHERE decision_id = ?", (ETH,)).fetchone()
    assert fila["motivo"] == "salida" and fila["salida_estimada"] == 0
    e.pasada()
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]


def test_en_halted_no_se_vende(tmp_path):
    esc = Escena(tmp_path)
    esc.vuelta()
    esc.ahora[0] = DECIDE
    esc.orden_papel()
    esc.vuelta()
    esc.ok.llenar(ids.cl_ord_id(ETH))
    esc.pasada()
    esc.manual[0] = {Mode.HALTED: "parada desde el VPS"}
    esc.cierre_papel(ETH, "news", DECIDE + TF)
    esc.vuelta(15_000)
    assert esc.ok.orden(ids.cl_ord_id_salida(ETH)) is None, "HALTED no cierra: las OCO siguen (decision 4)"
    assert esc.ok.oco(ids.algo_cl_ord_id(ETH))["state"] == "live"


# --- Modos ---------------------------------------------------------------------------------------------------


def test_la_pausa_cancela_la_entrada_pendiente_al_momento(e):
    e.orden_papel()
    e.vuelta()
    e.manual[0] = {Mode.CLOSE_ONLY_MANUAL: "/pause"}
    e.vuelta(15_000)
    assert e.ok.orden(ids.cl_ord_id(ETH))["state"] == "canceled"
    assert e.ej.modos.effective is Mode.CLOSE_ONLY_MANUAL


def test_dos_lecturas_bajo_el_suelo_enclavan_capital_y_sobrevive_al_reinicio(e):
    e.orden_papel()
    e.vuelta()
    e.ok.saldos["USDC"] -= 30.0          # el bot "pierde" 30 $: 20 $ de equity
    e.vuelta(15_000)
    assert e.ej.modos.effective is Mode.NORMAL, "una lectura sola no basta (regla 7)"
    e.vuelta(15_000)
    assert e.ej.modos.effective is Mode.CLOSE_ONLY_CAPITAL
    assert e.ok.orden(ids.cl_ord_id(ETH))["state"] == "canceled", "fuera de NORMAL, sin entradas pendientes"
    e.ok.saldos["USDC"] += 30.0
    e.nuevo_ejecutor()
    e.vuelta(15_000)
    assert e.ej.modos.effective is Mode.CLOSE_ONLY_CAPITAL, "enclavado: ni el rebote ni el reinicio lo levantan"


def test_tres_errores_de_red_seguidos_pasan_a_degraded(e):
    e.ok.fallar = 3
    for _ in range(3):
        assert not e.vuelta(15_000).leido
    assert e.ej.modos.effective is Mode.CLOSE_ONLY_DEGRADED


def test_en_degraded_la_orden_espera_y_se_copia_al_salir(e):
    e.ok.fallar = 3
    for _ in range(3):
        e.vuelta(15_000)
    e.orden_papel()
    e.vuelta(15_000)
    assert e.ok.orden(ids.cl_ord_id(ETH)) is None and ETH not in db.tratadas(e.conn), "espera, no se omite"
    for _ in range(45):                  # 11 min sano
        e.vuelta(15_000)
    assert e.ej.modos.effective is Mode.NORMAL
    assert e.ok.orden(ids.cl_ord_id(ETH)) is not None


# --- Caducidad -----------------------------------------------------------------------------------------------


def test_la_entrada_caduca_con_el_reloj_del_ejecutor(e):
    e.orden_papel()
    e.vuelta()
    e.ahora[0] = T0 + 4 * TF - 1_000
    e.vuelta()
    assert e.ok.orden(ids.cl_ord_id(ETH))["state"] == "live"
    e.ahora[0] = T0 + 4 * TF
    e.vuelta()
    assert e.ok.orden(ids.cl_ord_id(ETH))["state"] == "canceled"
    e.pasada()
    assert db.entradas(e.conn) == [] and e.ultima_pasada()["cuadra"] == 1


# --- El juez de la fase 4, independiente, sobre lo que hizo el ejecutor -------------------------------------------


def _juzgar(e, salidas=()):
    import importlib.util
    from pathlib import Path

    from execution import juez as j
    raiz = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("check_exec", raiz / "scripts" / "check_exec.py")
    ce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ce)
    ts_foto, _capital, foto = db.foto(e.conn)
    inicio = {"USDC": foto.usdc_total, **foto.monedas}
    fin = {m: e.ok.saldos.get(m, 0.0) for m in inicio}
    okx = ce.okx_para_el_juez([dict(o) for o in e.ok.ordenes], [dict(a) for a in e.ok.ocos], e.ok.fills(), inicio, fin)
    espejo, salidas_papel = ce.espejo_de(e.papel, ts_foto, TF, OPERABLES)
    lotes = {s: MERCADOS_DEMO[s][1] for s in OPERABLES}
    return j.juzgar(okx, ce.bot_de(e.conn), whitelist=OPERABLES, lotes=lotes, espejo=espejo,
                    hasta_ms=e.ahora[0], salidas_espejo=salidas_papel, niveles=ce.niveles_de(e.papel),
                    adoptadas=ce.adoptadas_de(e.papel, ts_foto))


def test_el_juez_independiente_no_ve_nada_raro_en_una_operacion_por_la_oco(e):
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.ok.saltar(ids.algo_cl_ord_id(ETH), "tp")
    for _ in range(3):
        e.pasada()
    v = _juzgar(e)
    assert v.fallas == [], v.fallas
    assert v.medidas["mandadas al demo"] == 1 and v.codigo == 2, "sin fallas, pero aun no hay una semana"


def test_el_juez_independiente_no_ve_nada_raro_en_un_parcial_ni_en_una_salida(e):
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH), 0.002)
    e.vuelta(15_000)
    e.pasada()
    e.cierre_papel(ETH, "news", e.ahora[0])
    e.vuelta(15_000)
    e.pasada()
    e.pasada()
    v = _juzgar(e)
    assert v.fallas == [], v.fallas
    assert v.medidas["salidas a mercado"] == 1


def test_el_juez_juzga_una_copia_vieja_como_si_fuera_su_hora(e, tmp_path):
    """Simulacro de restauracion (06/10): la copia de la base es de antes y OKX ya ha seguido (salto la OCO)."""
    import importlib.util
    import sqlite3

    from execution import juez as j
    raiz = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("check_exec", raiz / "scripts" / "check_exec.py")
    ce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ce)

    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.pasada()
    copia = tmp_path / "copia-exec.db"
    e.conn.execute(f"VACUUM INTO '{copia}'")
    hora_copia = e.ahora[0]
    e.ahora[0] += 60_000
    e.ok.saltar(ids.algo_cl_ord_id(ETH), "tp")             # despues de la copia: OKX vende
    for _ in range(3):
        e.pasada()

    conn = sqlite3.connect(copia)
    conn.row_factory = sqlite3.Row
    ts_foto, _capital, foto = db.foto(e.conn)
    inicio = {"USDC": foto.usdc_total, **foto.monedas}
    okx = ce.okx_para_el_juez([dict(o) for o in e.ok.ordenes], [dict(a) for a in e.ok.ocos], e.ok.fills(), inicio,
                              {m: e.ok.saldos.get(m, 0.0) for m in inicio})
    espejo, salidas = ce.espejo_de(e.papel, ts_foto, TF, OPERABLES)

    def juzgar(o, hasta):
        return j.juzgar(o, ce.bot_de(conn), whitelist=OPERABLES, lotes={s: MERCADOS_DEMO[s][1] for s in OPERABLES},
                        espejo=espejo, hasta_ms=hasta, salidas_espejo=salidas, niveles=ce.niveles_de(e.papel),
                        adoptadas=ce.adoptadas_de(e.papel, ts_foto))

    v = juzgar(ce.recortar(okx, hora_copia), hora_copia)
    assert v.fallas == [], v.fallas
    assert v.completas == 0, "a la hora de la copia la posicion seguia abierta con su OCO"
    assert any("sin conciliar desde" in f for f in juzgar(okx, e.ahora[0]).fallas), "con la hora de ahora, vieja"
    sin_recortar = juzgar(okx, hora_copia)
    assert sin_recortar.completas == 1, "sin quitar lo que OKX hizo despues, contaria un cierre que aun no habia pasado"


def test_el_juez_independiente_ve_una_compra_a_mano_en_la_web_del_demo(e):
    e.pasada()
    e.ok.saldos["SOL"] = e.ok.saldos.get("SOL", 0.0) + 0.5      # alguien compra SOL a mano
    e.pasada()
    v = _juzgar(e)
    assert any("saldo de SOL" in f for f in v.fallas), v.fallas
    assert any("descuadre" in f for f in v.fallas), "y la conciliacion del ejecutor tambien lo vio"


def test_la_orden_que_lanza_la_oco_no_es_ajena_aunque_la_pille_viva(e):
    """Prueba 10 del demo (03/10): la orden lanzada lleva clOrdId de OKX ("O...") y nuestro algoClOrdId."""
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.ok.saltar(ids.algo_cl_ord_id(ETH), "sl", lanzada_viva=True)
    e.pasada()
    assert "orden_ajena" not in e.ultima_pasada()["descuadres"], e.ultima_pasada()["descuadres"]



# --- La OCO que OKX rechaza con el precio ya pasado (decision del propietario del 03/10, opcion A) --------------------------


def _sin_oco_y_precio(e, precio):
    """Posicion llenada; alguien cancela su OCO desde la web y el precio se va a `precio`."""
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.ok.oco(ids.algo_cl_ord_id(ETH))["state"] = "canceled"
    e.ok.precios["ETH/USDC"] = precio


def test_con_el_precio_ya_pasado_el_objetivo_se_vende_a_mercado(e):
    _sin_oco_y_precio(e, 2870.0)          # objetivo del demo: 2861
    e.pasada()
    venta = e.ok.orden(ids.cl_ord_id_salida(ETH))
    assert venta is not None and venta["state"] == "filled" and float(venta["avgPx"]) == 2870.0
    assert e.conn.execute("SELECT COUNT(*) FROM exec_journal WHERE que = 'crear_oco' AND resultado = 'rechazada'"
                          ).fetchone()[0] == 1
    e.pasada()
    fila = e.conn.execute("SELECT motivo FROM exec_cierres WHERE decision_id = ?", (ETH,)).fetchone()
    assert fila["motivo"] == "salida"
    e.pasada()
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]
    v = _juzgar(e)
    assert not any("no hizo en papel" in f for f in v.fallas), v.fallas
    assert v.medidas["salidas por precio pasado"] == 1


def test_con_el_precio_ya_pasado_el_stop_tambien(e):
    _sin_oco_y_precio(e, 2550.0)          # stop del demo: 2554
    e.pasada()
    assert e.ok.orden(ids.cl_ord_id_salida(ETH))["state"] == "filled"


def test_con_el_precio_entre_stop_y_objetivo_se_rehace_la_oco_y_no_se_vende(e):
    _sin_oco_y_precio(e, 2700.0)
    e.pasada()
    assert e.ok.orden(ids.cl_ord_id_salida(ETH)) is None
    assert e.ok.oco(ids.algo_cl_ord_id(ETH))["state"] == "live", "la conciliacion la vuelve a crear"



# --- Adoptar las posiciones de papel abiertas en la foto (decision del propietario del 03/10) --------------------------


VIEJA = "d-20260928T0000-eth-pb"      # una decision de papel de ANTES de la foto


def _adoptar(e):
    """Lo que hace `scripts/adoptar_posiciones_demo.py`: en papel hay una posicion abierta de antes de la foto; se
    compra en el demo con su decision_id (limit que cruza) y su stop y objetivo adjuntos."""
    e.orden_papel(VIEJA, creada=T0 - 6 * 24 * 3600_000, estado="filled")
    with e.papel:
        e.papel.execute("INSERT INTO paper_positions (symbol, decision_id, qty, entry_price, stop_price, target_price,"
                        " setup, opened_ts_ms, entry_fee_usd, worst_price, best_price) VALUES"
                        " ('ETH/USDC', ?, ?, 2640.37, 2553.21, 2860.55, 'pullback_trend', ?, 0.01, 2600, 2700)",
                        (VIEJA, ETH_PAPEL["qty"], T0 - 6 * 24 * 3600_000 + TF))
    p = e.ok.create_order_request("ETH/USDC", "limit", "buy", ETH_PAPEL["qty"], 2651.0, {
        "clOrdId": ids.cl_ord_id(VIEJA), "tdMode": "cash", "tradeQuoteCcy": "USDC",
        "attachAlgoOrds": [{"attachAlgoClOrdId": ids.algo_cl_ord_id(VIEJA), "tpTriggerPx": "2861", "tpOrdPx": "-1",
                            "slTriggerPx": "2554", "slOrdPx": "-1"}]})
    e.ok.private_post_trade_order(p)
    e.ok.llenar(ids.cl_ord_id(VIEJA))


def test_la_posicion_adoptada_toma_stop_y_objetivo_de_su_orden_de_papel_aunque_sea_de_antes(e):
    _adoptar(e)
    e.pasada()
    [p] = db.posiciones(e.conn)
    assert (p.decision_id, p.stop, p.objetivo, p.entrada) == (VIEJA, 2553.21, 2860.55, 2651.0)
    fila = e.conn.execute("SELECT que, motivo FROM exec_tratadas WHERE decision_id = ?", (VIEJA,)).fetchone()
    assert fila["que"] == "adoptada" and "SIN" not in fila["motivo"]
    e.pasada()
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]
    assert e.ok.orden(ids.cl_ord_id(VIEJA))["state"] == "filled" and len(e.ok.ordenes) == 1, "no se copia otra vez"


def test_el_juez_acepta_la_adoptada_y_su_cierre_cuenta_como_operacion_completa(e):
    _adoptar(e)
    e.pasada()
    e.ok.saltar(ids.algo_cl_ord_id(VIEJA), "tp")
    for _ in range(2):
        e.pasada()
    v = _juzgar(e)
    assert v.fallas == [], v.fallas
    assert v.medidas["adoptadas"] == 1 and v.completas == 1



def test_la_oco_rehecha_va_al_tick_hacia_el_lado_seguro(e):
    """Test de caos 5 del 03/10: el objetivo de papel 134,01 de SOL volvio como 134 (ccxt redondea al mas cercano).
    Rehecha, va como al copiar: stop y objetivo hacia arriba."""
    _adoptar(e)                       # ETH: stop 2553,21 y objetivo 2860,55 de papel; tick del demo 1 $
    e.pasada()
    e.ok.oco(ids.algo_cl_ord_id(VIEJA))["state"] = "canceled"     # cancelada a mano desde la web
    e.pasada()
    nueva = e.ok.oco(ids.algo_cl_ord_id(VIEJA))
    assert nueva["state"] == "live"
    assert (float(nueva["slTriggerPx"]), float(nueva["tpTriggerPx"])) == (2554.0, 2861.0), "no 2553 ni 2861 por azar"



# --- Revision del 03/10 ----------------------------------------------------------------------------------------


def test_si_la_oco_ya_salto_no_se_vende_otra_vez_con_el_eth_de_la_foto(e):
    """La OCO salta y, antes de que la conciliacion lo vea, el papel cierra por noticias: cancelar la OCO contesta
    'ya no estaba'. Vender entonces gastaria el ETH de la foto (el demo tiene 1 ETH que no es del bot)."""
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.ok.saltar(ids.algo_cl_ord_id(ETH), "tp")
    e.cierre_papel(ETH, "news", e.ahora[0])
    e.vuelta(15_000)                             # vuelta corta: la conciliacion aun no ha visto que salto
    assert e.ok.orden(ids.cl_ord_id_salida(ETH)) is None, "no se vende dos veces"
    assert e.ok.saldos["ETH"] == pytest.approx(1.0), "el ETH de la foto, intacto"
    e.pasada()
    assert e.conn.execute("SELECT motivo FROM exec_cierres WHERE decision_id = ?", (ETH,)).fetchone()[0] == "tp"
    e.pasada()
    assert e.ultima_pasada()["cuadra"] == 1, e.ultima_pasada()["descuadres"]


def test_sin_base_y_con_ordenes_nuestras_vivas_no_se_hace_una_foto_nueva(e):
    e.orden_papel()
    e.vuelta()                                   # entrada nuestra viva en OKX
    e.conn.close()
    for sufijo in ("", "-wal", "-shm"):
        Path(str(e.exec_db) + sufijo).unlink(missing_ok=True)
    e.nuevo_ejecutor()
    with pytest.raises(RuntimeError, match="restaurarla de la copia"):
        e.vuelta(15_000)
    assert db.foto(e.conn) is None


def test_una_posicion_llenada_bajo_su_stop_no_bloquea_las_copias(e):
    db.guardar_posicion(e.conn, "d-20260925T1200-sol-pb", "SOL/USDC", 0.1, 110.0, 114.0, 125.0, T0, 0.01)
    e.ok.saldos["SOL"] = 0.1                     # la tiene en OKX (comprada a 110, por debajo de su stop de 114)
    e.orden_papel()
    e.vuelta()
    assert e.ok.orden(ids.cl_ord_id(ETH)) is not None, "la copia sale igual"


# --- Los dos huecos de Telegram del cierre de la fase 5 (03/10) ---------------------------------------------------


def test_el_aviso_de_cierre_del_demo_lleva_r_y_duracion(e):
    """PRD 9: par, resultado en $ y en R, motivo y duracion (como los de papel)."""
    e.orden_papel()
    e.vuelta()
    e.ok.llenar(ids.cl_ord_id(ETH))
    e.pasada()
    e.ahora[0] += 3 * 3600_000
    e.ok.saltar(ids.algo_cl_ord_id(ETH), "tp")
    e.pasada()
    texto = e.conn.execute("SELECT texto FROM paper_avisos WHERE tipo = 'operacion'").fetchone()[0]
    assert "ETH/USDC" in texto and " R)" in texto and "objetivo" in texto and "Duración" in texto and "3 h" in texto
    assert "claude" not in texto.lower()


def test_una_clave_rechazada_por_okx_se_avisa_como_tal_y_una_vez_por_hora(e):
    """PRD 9: el error de autenticacion de OKX, dicho como tal; sin la credencial en el texto."""
    original = e.ok.fetch_balance

    def rechazo(params=None):
        raise ccxt.AuthenticationError('okx {"code":"50119","data":[],"msg":"API key doesn\'t exist"}')
    e.ok.fetch_balance = rechazo
    for _ in range(4):
        e.vuelta(15_000)
    filas = e.conn.execute("SELECT texto FROM paper_avisos WHERE tipo = 'auth'").fetchall()
    assert len(filas) == 1 and "autenticación con OKX (demo)" in filas[0][0] and "50119" in filas[0][0]
    assert e.ej.modos.effective is Mode.CLOSE_ONLY_DEGRADED, "y cuenta como error del exchange"
    e.ok.fetch_balance = original
