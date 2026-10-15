"""El CSV fiscal en euros (PRD: "el bot exporta un CSV fiscal desde el primer dia"; el propietario, 28/09).

El cambio USDC/EUR sale de OKX (dato publico) solo al bajar el CSV: `api/cambio.py`. NINGUN test sale a la
red: se pasa un `pedir` falso que imita el formato de `history-candles` (la mas reciente primero).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from api import cambio, historial
from api.app import crear_app
from core.config import load_settings
from portfolio import store

H = cambio.HORA_MS
T0 = 1_790_352_000_000          # 25/09/2026 16:00 UTC
API = Path(__file__).resolve().parents[2] / "api"


def okx_falso(tasa_de, huecos=()):
    """`pedir` con velas de 1 h: apertura = tasa_de(hora); `huecos`, horas sin vela. Apunta cada peticion."""
    llamadas = []

    def pedir(host, after_ms):
        llamadas.append(after_ms)
        horas = [after_ms - (i + 1) * H for i in range(100)]
        return [[str(h), str(tasa_de(h)), "0", "0", "0", "1", "1", "1", "1"] for h in horas if h not in huecos]

    pedir.llamadas = llamadas
    return pedir


def test_baja_solo_lo_justo_y_da_la_apertura_de_su_hora():
    pedir = okx_falso(lambda h: 0.85 + (h - T0) / H / 10_000)
    instantes = [T0 + 17 * 60_000, T0 - 3 * H, T0 - 150 * H]       # dos en el mismo lote y uno en otro
    tabla = cambio.aperturas(instantes, "eea.okx.com", pedir, pausa_s=0)
    assert len(pedir.llamadas) == 2
    assert cambio.cambio(T0 + 17 * 60_000, tabla) == pytest.approx(0.85)       # la hora de las 16:00
    assert cambio.cambio(T0 - 3 * H, tabla) == pytest.approx(0.85 - 0.0003)
    assert cambio.cambio(T0 - 150 * H, tabla) == pytest.approx(0.85 - 0.015)


def test_una_hora_sin_vela_toma_la_anterior_y_no_mas_alla_de_6_h():
    pedir = okx_falso(lambda h: 0.9, huecos={T0})
    tabla = cambio.aperturas([T0 + 60_000], "eea.okx.com", pedir, pausa_s=0)
    assert cambio.cambio(T0 + 60_000, tabla) == 0.9                            # la de las 15:00
    lejos = {T0 - 7 * H: 0.9}
    assert cambio.cambio(T0, lejos) is None


def test_si_okx_no_responde_no_hay_cambio_y_no_lanza():
    def cae(host, after_ms):
        raise TimeoutError("sin red")
    assert cambio.aperturas([T0], "eea.okx.com", cae, pausa_s=0) == {}
    assert cambio.aperturas([], "eea.okx.com", cae, pausa_s=0) == {}


def test_nunca_pasa_del_tope_de_peticiones():
    pedir = okx_falso(lambda h: 0.9)
    instantes = [T0 - i * 200 * H for i in range(cambio.MAX_PETICIONES + 10)]  # cada uno en su lote
    cambio.aperturas(instantes, "eea.okx.com", pedir, pausa_s=0)
    assert len(pedir.llamadas) == cambio.MAX_PETICIONES


OP = {"cartera": "ai", "decision_id": "d-a", "symbol": "ETH/USDC", "setup": "pullback_trend", "qty": 0.01,
      "entry_price": 2000.0, "exit_price": 2100.0, "stop_price": 1900.0, "target_price": 2300.0,
      "opened_ts_ms": T0, "closed_ts_ms": T0 + 8 * H, "reason": "target", "entry_fee_usd": 0.02,
      "exit_fee_usd": 0.021, "net_pnl_usd": 0.959, "r_multiple": 0.96}


def test_las_columnas_en_euros():
    tabla = {T0: 0.90, T0 + 8 * H: 0.80}
    fila = dict(zip(historial.COLUMNAS_CSV, historial.csv_operaciones([OP], tabla).splitlines()[1].split(";")))
    assert float(fila["cambio_usdc_eur_apertura"]) == 0.90 and float(fila["cambio_usdc_eur_cierre"]) == 0.80
    # adquisicion: (0,01 x 2000 + 0,02) x 0,90; transmision: (0,01 x 2100 - 0,021) x 0,80
    assert float(fila["valor_adquisicion_eur"]) == pytest.approx(18.018)
    assert float(fila["valor_transmision_eur"]) == pytest.approx(16.7832)
    # Con el dolar bajando, una operacion que gana en USDC pierde en euros: lo que pide Hacienda.
    assert float(fila["ganancia_eur"]) == pytest.approx(16.7832 - 18.018)


def test_sin_cambio_las_columnas_en_euros_van_vacias():
    for tabla in (None, {}, {T0: 0.9}):                                        # sin ninguno, o falta el cierre
        fila = historial.csv_operaciones([OP], tabla).splitlines()[1].split(";")
        assert fila[-5:] == ["", "", "", "", ""]


def _csv_de(app, cartera):
    ruta = next(r for r in app.routes if getattr(r, "path", "") == "/api/operaciones.csv")
    return ruta.endpoint(cartera)


def _base_con_una_operacion(tmp_path):
    c = store.connect(tmp_path / "ai.db")
    store.migrate(c)
    with c:
        c.execute("INSERT INTO paper_trades (decision_id, symbol, setup, decider, qty, entry_price, exit_price,"
                  " stop_price, target_price, opened_ts_ms, closed_ts_ms, reason, entry_fee_usd, exit_fee_usd,"
                  " exit_was_maker, mae_pct, mfe_pct, net_pnl_usd, r_multiple) VALUES"
                  " ('d-a','ETH/USDC','pullback_trend','ai',0.01,2000,2100,1900,2300,?,?,'target',0.02,0.021,1,"
                  " -1,5,0.959,0.96)", (T0, T0 + 8 * H))
    c.close()
    return {"principal": tmp_path / "no.db", "baseline": tmp_path / "no.db", "ai": tmp_path / "ai.db",
            "noticias": tmp_path / "no.db", "control": tmp_path / "no.db"}


def test_el_panel_da_el_csv_con_euros_y_avisa_si_faltan(tmp_path):
    rutas = _base_con_una_operacion(tmp_path)
    bien = _csv_de(crear_app(load_settings(), rutas, pedir_cambio=okx_falso(lambda h: 0.86)), "ai")
    assert "X-Ploutos-Aviso" not in bien.headers
    assert bien.body.decode().splitlines()[1].split(";")[-5] == "0.86"

    def cae(host, after_ms):
        raise TimeoutError
    mal = _csv_de(crear_app(load_settings(), rutas, pedir_cambio=cae), "ai")
    assert "2 instante" in mal.headers["X-Ploutos-Aviso"]
    assert mal.body.decode().splitlines()[1].split(";")[-5:] == ["", "", "", "", ""]


def test_lo_unico_del_panel_que_sale_a_la_red_es_el_cambio():
    """Decision del 25/09: el panel no habla con el exchange. Excepcion del 28/09: el cambio del CSV."""
    # `urllib.parse` solo trata texto (lo usa mando.py): no sale a la red.
    prohibidos = {"urllib", "urllib.request", "http.client", "socket", "requests", "httpx", "ccxt", "aiohttp",
                  "data.exchange"}
    for fichero in API.glob("*.py"):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        nombres = {a.name for n in ast.walk(arbol) if isinstance(n, ast.Import) for a in n.names}
        nombres |= {n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.module}
        salen = {m for m in nombres if m in prohibidos or m.split(".")[0] in {"requests", "httpx", "ccxt", "aiohttp"}}
        if fichero.name == "cambio.py":
            assert salen == {"urllib.request"}, salen
        else:
            assert not salen, f"{fichero.name} sale a la red: {salen}"
