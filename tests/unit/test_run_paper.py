"""El bucle de papel en vivo cuando una pasada falla a medias.

BUG REAL (22/09/2026): si una pasada lanzaba una excepcion despues de que el
simulador hubiera avanzado la vela en memoria, el cursor no se movia (bien)
pero el estado en memoria SI (mal). Al reintentar, la misma vela se aplicaba
dos veces: una entrada envejecia el doble, una posicion se volvia a evaluar.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from argparse import Namespace
from pathlib import Path

import pytest

from data.store.db import open_database
from portfolio import store
from tests.risk_fixtures import INSTRUMENTS, MAKER, TAKER

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_paper.py"
_spec = importlib.util.spec_from_file_location("run_paper", SCRIPT)
run_paper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_paper)

BAR_MS = 4 * 60 * 60 * 1000
T0 = 1_790_092_800_000   # 22/09/2026 16:00 UTC


@pytest.fixture
def runner(tmp_path):
    main = tmp_path / "main.db"
    db = open_database(main)
    db.executemany_sync(
        "INSERT INTO instruments (symbol, base, quote, active, tick_size,"
        " lot_size, min_amount, min_cost, maker_fee, taker_fee, raw, fetched_ms)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (s, s.split("/")[0], "USDC", 1, i.tick_size, i.lot_size,
             i.min_amount, None, MAKER, TAKER, "{}", T0)
            for s, i in INSTRUMENTS.items()
        ],
    )
    db.executemany_sync(
        "INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low,"
        " close, volume, closed, source, ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (s, "4h", T0 + k * BAR_MS, 1.0, 1.1, 0.9, 1.0, 100.0, 1, "rest", T0)
            for s in INSTRUMENTS
            for k in range(2)
        ],
    )
    db.close()

    args = Namespace(
        tf="4h", equity=50.0, slider=3, main_db=str(main),
        paper_db=str(tmp_path / "paper.db"), news_db=str(tmp_path / "news.db"),
        control_db=str(tmp_path / "control.db"),
    )
    r = run_paper.PaperRunner(args)
    # Nada de red en los tests: precios de la regla 17 fijos y en paridad.
    r.usdc_mids = lambda: {
        "USDC/USDT": 1.0, "USDT/USD": 1.0, "BTC/USD": 60000.0, "BTC/USDC": 60000.0,
    }
    yield r
    r.main.close()
    r.paper.close()


def test_una_pasada_que_falla_no_deja_estado_a_medias(runner, monkeypatch):
    # Una entrada pendiente, guardada.
    runner.broker.submit("d-1", "ETH/USDC", 0.15, 100.0, 97.0, 106.0,
                         "pullback_trend", T0 - BAR_MS)
    store.save_state(runner.paper, runner.broker, runner.ledger, "4h", T0 - BAR_MS)
    runner.cursor = store.cursor(runner.paper, "4h")

    def paso_que_revienta(*_a, **_k):
        # Avanza el simulador EN MEMORIA y luego falla, como haria un error
        # en los indicadores despues del paso 1 del bucle.
        runner.broker.orders[0].bars_waited += 1
        raise RuntimeError("fallo a mitad de vela")

    monkeypatch.setattr(runner.loop, "step", paso_que_revienta)
    runner.tick()   # no puede lanzar

    # El estado es el de la ultima vela que SI se completo.
    assert runner.broker.orders[0].bars_waited == 0
    assert runner.cursor == T0 - BAR_MS
    assert runner.loop.step is not paso_que_revienta, "el bucle se reconstruye"


def test_si_falla_al_guardar_no_queda_journal_huerfano(runner, monkeypatch):
    """Journal y estado van juntos: o se guarda la vela entera o nada."""
    def guardar_que_revienta(*_a, **_k):
        raise sqlite3.OperationalError("disco lleno")

    monkeypatch.setattr(store, "_write_state", guardar_que_revienta)
    runner.tick()

    filas = runner.paper.execute("SELECT count(*) FROM paper_decisions").fetchone()[0]
    assert filas == 0
    assert store.cursor(runner.paper, "4h") is None


def test_las_comisiones_salen_de_settings_no_de_la_tabla(runner):
    """Decision del propietario del 23/09/2026. La tabla `instruments` trae las de ccxt
    (genericas); el motor de riesgo y el modelo de costes tienen que ver las de
    settings.yaml, LOS DOS, o la regla 16 y el simulador contarian distinto."""
    fees = runner.settings.exchange.fees
    assert TAKER != fees.taker_pct / 100, "el test no probaria nada"
    for symbol in INSTRUMENTS:
        assert runner.instruments[symbol].maker_fee == pytest.approx(fees.maker_pct / 100)
        assert runner.instruments[symbol].taker_fee == pytest.approx(fees.taker_pct / 100)
        assert runner.cost.fees_for(symbol).taker == pytest.approx(fees.taker_pct / 100)
        assert runner.cost.fees_for(symbol).maker == pytest.approx(fees.maker_pct / 100)


# --------------------------------------------------------------------------
# Los avisos de Telegram, enchufados (24/09/2026)
# --------------------------------------------------------------------------


def test_un_telegram_que_falla_no_tumba_la_vuelta_ni_recarga(runner, monkeypatch):
    """Los avisos van aparte y blindados: ni lanzan ni provocan la recarga del bucle."""
    runner._tg_token, runner._tg_chat = "token-falso", "1"
    recargas = []
    monkeypatch.setattr(runner, "reload", lambda: recargas.append(1))

    def revienta(*a, **kw):
        raise RuntimeError("Telegram raro")

    monkeypatch.setattr(run_paper, "enviar_pendientes", revienta)
    runner.tick()
    assert recargas == []
    assert runner.cursor is not None, "la vela se proceso igual"


def test_la_parada_queda_apuntada(runner, monkeypatch):
    monkeypatch.setattr(run_paper, "enviar_pendientes", lambda *a, **kw: (0, "sin credenciales"))
    runner._aviso_parada("prueba")
    [fila] = runner.paper.execute("SELECT tipo, texto FROM paper_avisos WHERE tipo = 'parada'").fetchall()
    assert "ploutos-paper" in fila["texto"] and "prueba" in fila["texto"]


def test_sin_credenciales_los_avisos_se_quedan_en_la_base(runner):
    """La guarda de conftest deja el runner sin Telegram: nada sale, nada se pierde."""
    assert runner._tg_token is None
    runner._aviso_parada("prueba")
    fila = runner.paper.execute("SELECT enviado_ms, descartado FROM paper_avisos").fetchone()
    assert tuple(fila) == (None, 0)


# --------------------------------------------------------------------------
# El latido del vigilante externo (24/09/2026)
# --------------------------------------------------------------------------


class LatidoFalso:
    def __init__(self):
        self.veces = 0

    def enviar(self):
        self.veces += 1


def test_late_solo_tras_una_vuelta_sin_error(runner, monkeypatch):
    """Un bucle vivo pero atascado no puede latir: si no, el vigilante no lo veria."""
    runner._latido = LatidoFalso()
    runner.tick()
    assert runner._latido.veces == 1

    def revienta():
        raise RuntimeError("vela imposible")

    monkeypatch.setattr(runner, "catch_up", revienta)
    monkeypatch.setattr(runner, "reload", lambda: None)
    runner.tick()
    assert runner._latido.veces == 1, "tras un fallo, sin latido"


# --------------------------------------------------------------------------
# Noticias (pieza 4c): las flags de ploutos-news llegan al filtro de la cartera
# --------------------------------------------------------------------------

from data.news import store as noticias  # noqa: E402
from features.news import Anuncio  # noqa: E402


def _base_de_noticias(runner, *anuncios):
    conn = noticias.conectar(runner.news_db)
    noticias.migrar(conn)
    noticias.guardar(conn, list(anuncios), T0)
    return conn


def _motivos_de(runner, simbolo):
    return [r[0] for r in runner.paper.execute(
        "SELECT detail FROM paper_decisions WHERE kind = 'filtered' AND symbol = ?", (simbolo,))]


def test_un_deslistado_para_la_moneda_en_el_filtro_y_solo_esa(runner):
    _base_de_noticias(runner, Anuncio("u", T0 - BAR_MS, "OKX to delist ETH")).close()
    runner.tick()
    eth = _motivos_de(runner, "ETH/USDC")
    assert eth and all("evento" in m and "delisting (critica)" in m for m in eth)
    assert not any("evento" in m for m in _motivos_de(runner, "BTC/USDC"))


def test_sin_base_de_noticias_nada_se_bloquea_por_noticias(runner):
    assert not runner.news_db.exists()
    runner.tick()
    todos = [r[0] for r in runner.paper.execute("SELECT detail FROM paper_decisions WHERE kind = 'filtered'")]
    assert not any("evento" in m for m in todos)


def test_la_flag_se_mira_al_cierre_de_la_vela_no_a_la_apertura(runner):
    """Anunciado a mitad de la ultima vela: tiene que parar la decision de su cierre."""
    _base_de_noticias(runner, Anuncio("u", T0 + BAR_MS + BAR_MS // 2, "OKX to delist ETH")).close()
    runner.tick()
    ultima = runner.cursor
    filas = runner.paper.execute(
        "SELECT detail FROM paper_decisions WHERE kind = 'filtered' AND symbol = 'ETH/USDC' AND ts_ms = ?",
        (ultima,)).fetchall()
    assert filas and "evento" in filas[0][0]


def test_si_la_base_de_noticias_falla_se_mantienen_las_ultimas_flags(runner, monkeypatch):
    _base_de_noticias(runner, Anuncio("u", T0 - BAR_MS, "OKX to delist ETH")).close()
    assert runner._event_flags(T0 + BAR_MS)
    def rota(_ruta):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(noticias, "solo_lectura", rota)
    assert runner._event_flags(T0 + 2 * BAR_MS) == {"ETH/USDC": ("delisting (critica)",)}


def test_con_una_flag_critica_la_cartera_vende_a_mercado_y_lo_avisa(runner):
    """De punta a punta: posicion en ETH, deslistado de ETH -> venta al cierre, taker, y aviso."""
    runner.broker.submit("d-eth", "ETH/USDC", 5.0, 1.0, 0.85, 1.2, "pullback_trend", T0 - BAR_MS)
    store.save_state(runner.paper, runner.broker, runner.ledger, "4h", T0 - BAR_MS)
    runner.cursor = store.cursor(runner.paper, "4h")
    _base_de_noticias(runner, Anuncio("u", T0 - BAR_MS, "OKX to delist ETH")).close()
    runner.tick()
    [t] = runner.paper.execute("SELECT * FROM paper_trades WHERE decision_id = 'd-eth'").fetchall()
    assert (t["reason"], t["exit_was_maker"], t["closed_ts_ms"]) == ("news", 0, T0)
    avisos = [r[0] for r in runner.paper.execute("SELECT texto FROM paper_avisos")]
    assert any("noticia" in a and "ETH/USDC" in a for a in avisos)


def test_con_una_flag_la_entrada_pendiente_se_cancela_y_queda_apuntado(runner):
    runner.broker.submit("d-sol", "SOL/USDC", 0.1, 0.5, 0.45, 0.7, "pullback_trend", T0 - BAR_MS)
    store.save_state(runner.paper, runner.broker, runner.ledger, "4h", T0 - BAR_MS)
    runner.cursor = store.cursor(runner.paper, "4h")
    _base_de_noticias(runner, Anuncio("v", T0 - BAR_MS, "Announcement on the Price Volatility of Solana (SOL)")).close()
    runner.tick()
    estado = runner.paper.execute("SELECT state FROM paper_orders WHERE decision_id = 'd-sol'").fetchone()[0]
    assert estado == "cancelled"
    [fila] = runner.paper.execute(
        "SELECT detail FROM paper_decisions WHERE decision_id = 'd-sol' AND kind = 'cancelled'").fetchall()
    assert "volatility (alta)" in fila[0]


def test_el_juez_de_verdad_da_por_buena_la_venta_por_noticia(runner, monkeypatch, capsys):
    """check_paper.py sobre las bases que acaba de escribir el servicio: sin ninguna FALLA."""
    runner.broker.submit("d-eth", "ETH/USDC", 5.0, 1.0, 0.85, 1.2, "pullback_trend", T0 - BAR_MS)
    store.save_state(runner.paper, runner.broker, runner.ledger, "4h", T0 - BAR_MS)
    runner.cursor = store.cursor(runner.paper, "4h")
    _base_de_noticias(runner, Anuncio("u", T0 - BAR_MS, "OKX to delist ETH")).close()
    runner.tick()
    spec = importlib.util.spec_from_file_location(
        "check_paper", Path(__file__).resolve().parents[2] / "scripts" / "check_paper.py")
    juez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(juez)
    monkeypatch.setattr("sys.argv", ["check_paper.py", "--main-db", str(runner.main_db),
                                     "--paper-db", str(runner.paper_db), "--news-db", str(runner.news_db),
                                     "--hours", "0"])
    juez.main()
    salida = capsys.readouterr().out
    # La orden de este test se mete a mano en el simulador (sin candidato en el journal ni vela
    # anterior con equity): las comprobaciones de la cadena y de las reglas al ENTRAR fallan por
    # eso, y no miden nada de las noticias. Las que juzgan la VENTA si: tienen que estar en OK.
    for nombre in ("lo guardado coincide con re-simular contra las velas",
                   "comisiones, P&L y R de cada operacion",
                   "equity y contadores de cada vela"):
        [linea] = [l for l in salida.splitlines() if nombre in l and ("OK" in l or "FALLA" in l)][:1]
        assert linea.strip().startswith("OK"), linea


# --------------------------------------------------------------------------
# Comandos de Telegram (pieza 6 de docs/diseno-comandos-telegram.md): la pausa llega al bucle
# --------------------------------------------------------------------------

from notify import control  # noqa: E402
from core.modes import Mode  # noqa: E402
from notify.comandos import Comando, Orden  # noqa: E402


def _base_de_control(ruta, *comandos):
    conn = control.conectar(ruta)
    control.migrar(conn)
    for i, (orden, ts) in enumerate(comandos):
        control.guardar_comando(conn, Comando(i + 1, ts, orden, f"/{orden.value}"),
                                recibido_ms=ts, origen="telegram", respuesta="ok")
    conn.close()


def _pendiente_lejos(runner):
    """Una entrada que no se llena nunca (muy por debajo del precio): solo la cancela un modo."""
    runner.broker.submit("d-sol", "SOL/USDC", 0.1, 0.01, 0.009, 0.02, "pullback_trend", T0 - BAR_MS)
    store.save_state(runner.paper, runner.broker, runner.ledger, "4h", T0 - BAR_MS)
    runner.cursor = store.cursor(runner.paper, "4h")


def _juez(runner, monkeypatch, capsys, control_db):
    spec = importlib.util.spec_from_file_location(
        "check_paper", Path(__file__).resolve().parents[2] / "scripts" / "check_paper.py")
    juez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(juez)
    monkeypatch.setattr("sys.argv", ["check_paper.py", "--main-db", str(runner.main_db),
                                     "--paper-db", str(runner.paper_db), "--news-db", str(runner.news_db),
                                     "--control-db", str(control_db), "--hours", "0"])
    juez.main()
    salida = capsys.readouterr().out
    [linea] = [l for l in salida.splitlines() if "ninguna entrada en modo de solo cierre" in l]
    return linea.strip()


def test_con_pausa_la_cartera_entra_en_solo_cierre_y_cancela(runner):
    _pendiente_lejos(runner)
    _base_de_control(runner.control_db, (Orden.PAUSE, T0 - BAR_MS // 2))
    runner.tick()
    estado = runner.paper.execute("SELECT state FROM paper_orders WHERE decision_id = 'd-sol'").fetchone()[0]
    assert estado == "cancelled"
    modos = [(r["mode"], r["activated"]) for r in runner.paper.execute("SELECT * FROM paper_mode_changes")]
    assert modos == [("CLOSE_ONLY_MANUAL", 1)]
    assert runner.loop.modes.effective is Mode.CLOSE_ONLY_MANUAL
    avisos = [r[0] for r in runner.paper.execute("SELECT texto FROM paper_avisos")]
    assert any("CLOSE_ONLY_MANUAL" in a and "/resume" in a for a in avisos)
    assert not runner.paper.execute(
        "SELECT 1 FROM paper_decisions WHERE kind = 'submitted'").fetchall()


def test_la_pausa_cuenta_al_cierre_de_la_vela(runner):
    """Enviada despues del cierre de la ultima vela: esa decision ya estaba tomada."""
    _pendiente_lejos(runner)
    _base_de_control(runner.control_db, (Orden.PAUSE, T0 + 2 * BAR_MS + 1000))
    runner.tick()
    assert runner.loop.modes.effective is Mode.NORMAL


def test_sin_base_de_control_no_cambia_ningun_modo(runner):
    assert not runner.control_db.exists()
    runner.tick()
    assert runner.loop.modes.effective is Mode.NORMAL


def test_el_juez_de_verdad_da_por_buena_la_pausa(runner, monkeypatch, capsys):
    _pendiente_lejos(runner)
    _base_de_control(runner.control_db, (Orden.PAUSE, T0 - BAR_MS // 2))
    runner.tick()
    assert _juez(runner, monkeypatch, capsys, runner.control_db).startswith("OK")


def test_el_juez_ve_una_cartera_que_no_aplico_la_pausa(runner, monkeypatch, capsys, tmp_path):
    """La cartera no ve la base de control (no existe para ella); el juez si: FALLA."""
    _pendiente_lejos(runner)
    runner.tick()
    otra = tmp_path / "control-juez.db"
    _base_de_control(otra, (Orden.PAUSE, T0 - BAR_MS // 2))
    assert _juez(runner, monkeypatch, capsys, otra).startswith("FALLA")


def test_tras_una_parada_avisa_de_que_vuelve_una_sola_vez(runner):
    """el propietario, 26/09: al "parado" de una actualizacion le sigue su "en marcha de nuevo"."""
    runner._aviso_arranque()                 # primer arranque: nada
    assert not runner.paper.execute("SELECT 1 FROM paper_avisos WHERE tipo = 'arranque'").fetchall()
    ahora = [T0 + 10 * BAR_MS]
    runner._ahora_ms = lambda: ahora[0]
    runner._aviso_parada("parado limpiamente")
    ahora[0] += 4000
    runner._aviso_arranque()
    runner._aviso_arranque()                 # una sola vez por parada
    filas = runner.paper.execute("SELECT texto FROM paper_avisos WHERE tipo = 'arranque'").fetchall()
    assert len(filas) == 1
    assert "en marcha de nuevo" in filas[0][0] and "(4 s)" in filas[0][0] and "ploutos-paper" in filas[0][0]
    assert "claude" not in filas[0][0].lower()


def test_cerrar_todo_desde_el_panel_vende_y_el_juez_lo_da_por_bueno(runner, monkeypatch, capsys):
    """De punta a punta: posicion en ETH, "cerrar todo" durante la ultima vela -> venta manual al cierre,
    taker; la cartera queda en pausa; el juez de papel (con la base de control) no ve nada raro en la venta."""
    from api import mando
    runner.broker.submit("d-eth", "ETH/USDC", 5.0, 1.0, 0.85, 1.2, "pullback_trend", T0 - BAR_MS)
    store.save_state(runner.paper, runner.broker, runner.ledger, "4h", T0 - BAR_MS)
    runner.cursor = store.cursor(runner.paper, "4h")
    ctl = control.conectar(runner.control_db)
    control.migrar(ctl)
    mando.ejecutar(ctl, "cerrar_todo", "", T0 + BAR_MS // 2)      # durante la vela de T0 (cierra en T0 + BAR_MS)
    ctl.close()
    runner.tick()
    [t] = runner.paper.execute("SELECT * FROM paper_trades WHERE decision_id = 'd-eth'").fetchall()
    assert (t["reason"], t["exit_was_maker"], t["closed_ts_ms"]) == ("manual", 0, T0)
    assert runner.loop.modes.effective is Mode.CLOSE_ONLY_MANUAL
    for nombre in ("lo guardado coincide con re-simular contra las velas", "comisiones, P&L y R de cada operacion"):
        spec = importlib.util.spec_from_file_location(
            "check_paper", Path(__file__).resolve().parents[2] / "scripts" / "check_paper.py")
        juez = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(juez)
        monkeypatch.setattr("sys.argv", ["check_paper.py", "--main-db", str(runner.main_db), "--paper-db",
                                         str(runner.paper_db), "--news-db", str(runner.news_db),
                                         "--control-db", str(runner.control_db), "--hours", "0"])
        juez.main()
        [linea] = [l for l in capsys.readouterr().out.splitlines() if nombre in l]
        assert linea.strip().startswith("OK"), linea


def _anyadir_velas(ruta, k, simbolos):
    db = open_database(ruta)
    db.executemany_sync(
        "INSERT INTO candles (symbol, timeframe, ts_open_ms, open, high, low, close, volume, closed, source,"
        " ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(s, "4h", T0 + k * BAR_MS, 1.0, 1.1, 0.9, 1.0, 100.0, 1, "ws", T0) for s in simbolos])
    db.close()


def test_no_se_procesa_una_vela_hasta_que_estan_las_ocho_monedas(runner, monkeypatch, tmp_path):
    """BUG REAL (27/09/2026, 04:00): el bucle proceso la vela con DOGE aun sin cerrar (la ingesta escribe
    las ocho en ~1,5 s). Sin DOGE no se miro su stop ni su objetivo y la posicion se valoro a la entrada."""
    runner.catch_up()
    assert runner.cursor == T0 + BAR_MS
    sin_doge = [s for s in INSTRUMENTS if s != "DOGE/USDC"]
    _anyadir_velas(tmp_path / "main.db", 2, sin_doge)
    cierre = T0 + 3 * BAR_MS

    monkeypatch.setattr(runner, "_ahora_ms", lambda: cierre + 1_000)        # 1 s tras el cierre: falta DOGE
    assert runner._closed_bars_after(runner.cursor) == []
    assert runner.catch_up() == 0 and runner.cursor == T0 + BAR_MS

    _anyadir_velas(tmp_path / "main.db", 2, ["DOGE/USDC"])                  # llega DOGE: ya se procesa
    assert runner._closed_bars_after(runner.cursor) == [T0 + 2 * BAR_MS]


def test_si_una_moneda_no_llega_se_procesa_a_los_dos_minutos(runner, monkeypatch, tmp_path, caplog):
    """El bucle no se puede quedar parado porque falle la ingesta de UNA moneda; lo dice en el log."""
    runner.catch_up()
    _anyadir_velas(tmp_path / "main.db", 2, [s for s in INSTRUMENTS if s != "DOGE/USDC"])
    cierre = T0 + 3 * BAR_MS
    monkeypatch.setattr(runner, "_ahora_ms", lambda: cierre + run_paper.ESPERA_VELA_MS - 1)
    assert runner._closed_bars_after(runner.cursor) == []
    monkeypatch.setattr(runner, "_ahora_ms", lambda: cierre + run_paper.ESPERA_VELA_MS)
    with caplog.at_level("WARNING"):
        assert runner._closed_bars_after(runner.cursor) == [T0 + 2 * BAR_MS]
    assert "7 de 8 monedas" in caplog.text


def test_una_vela_incompleta_no_deja_pasar_las_siguientes(runner, monkeypatch, tmp_path):
    runner.catch_up()
    _anyadir_velas(tmp_path / "main.db", 2, [s for s in INSTRUMENTS if s != "XRP/USDC"])
    _anyadir_velas(tmp_path / "main.db", 3, list(INSTRUMENTS))
    monkeypatch.setattr(runner, "_ahora_ms", lambda: T0 + 3 * BAR_MS + 1_000)
    assert runner._closed_bars_after(runner.cursor) == []                   # nunca se salta la de las 2


def test_una_moneda_sin_la_vela_de_la_hora_no_da_candidatos_y_queda_apuntada(runner, monkeypatch, tmp_path):
    """28/09: si a los 2 min falta una moneda, se procesa sin ella; su ultima vela es una ANTERIOR y un
    candidato suyo saldria de una vela vieja. No se le generan candidatos y queda en el journal."""
    runner.catch_up()
    _anyadir_velas(tmp_path / "main.db", 2, [s for s in INSTRUMENTS if s != "DOGE/USDC"])
    monkeypatch.setattr(runner, "_ahora_ms", lambda: T0 + 3 * BAR_MS + run_paper.ESPERA_VELA_MS)
    assert runner.catch_up() == 1
    filas = runner.paper.execute("SELECT symbol, kind, detail FROM paper_decisions WHERE ts_ms = ?",
                                 (T0 + 2 * BAR_MS,)).fetchall()
    sin_vela = [f for f in filas if "sin la vela de esta hora" in (f[2] or "")]
    assert [f[0] for f in sin_vela] == ["DOGE/USDC"] and sin_vela[0][1] == "filtered"
    assert not any(f[0] == "DOGE/USDC" and f[1] == "candidate" for f in filas)



def test_el_bucle_apunta_el_motivo_de_las_que_no_dan_senyal(runner, monkeypatch):
    """29/09 (el propietario): lo que devuelve `filas_sin_senyal` acaba en el journal como `sin_senyal` (enchufado de verdad;
    la logica se prueba en test_motivo_sin_senyal.py: aqui los datos de prueba no dejan pasar ninguna moneda)."""
    monkeypatch.setattr(run_paper, "filas_sin_senyal", lambda pipeline: [("BTC/USDC", "mercado de lado: prueba")])
    runner.tick()
    filas = runner.paper.execute("SELECT symbol, detail FROM paper_decisions WHERE kind = 'sin_senyal'").fetchall()
    assert filas and all(tuple(f) == ("BTC/USDC", "mercado de lado: prueba") for f in filas)


# --------------------------------------------------------------------------
# Regla 17: OKX retiro BTC/USD y la paridad bloqueo 20 h sin avisar (01/10/2026)
# --------------------------------------------------------------------------


def test_el_bucle_avisa_cuando_la_paridad_bloquea_y_cuando_se_recupera(runner, monkeypatch, tmp_path):
    """Enchufado de verdad: la lectura anterior sale de la BASE (sobrevive a un reinicio)."""
    runner.usdc_mids = lambda: {"USDC/USDT": 1.0, "USDT/USD": None}      # falta un libro: desconocida
    runner.catch_up()                                                     # dos velas, las dos bloqueadas
    avisos = runner.paper.execute("SELECT clave, texto FROM paper_avisos WHERE tipo = 'paridad'").fetchall()
    assert len(avisos) == 1, "solo al empezar, no en cada vela"
    assert "sin entradas" in avisos[0]["texto"] and "USDT/USD" in avisos[0]["texto"]

    runner.usdc_mids = lambda: {"USDC/USDT": 1.0, "USDT/USD": 1.0}       # vuelve
    _anyadir_velas(tmp_path / "main.db", 2, list(INSTRUMENTS))
    monkeypatch.setattr(runner, "_ahora_ms", lambda: T0 + 3 * BAR_MS + 1_000)
    assert runner.catch_up() == 1
    textos = [f["texto"] for f in runner.paper.execute(
        "SELECT texto FROM paper_avisos WHERE tipo = 'paridad' ORDER BY id")]
    assert len(textos) == 2 and "recuperada" in textos[1]
