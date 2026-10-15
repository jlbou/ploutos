"""Adoptar en el demo las posiciones de la cartera de la IA que estaban ABIERTAS en la foto (decision del propietario del 03/10).

UNA SOLA VEZ, para arrancar la fase 4: la cartera de la IA tenia las 3 plazas llenas con posiciones de antes de la foto
y el ejecutor solo copia decisiones NUEVAS, asi que el demo podia pasar la semana sin hacer nada. No es un mecanismo:
el ejecutor no lo hace solo.

Por cada posicion de papel abierta en la foto, en un par que el demo opera (las condiciones del propietario del 03/10):
1. solo pares operables en el demo (comision real <= la configurada; AVAX no tiene par en el demo);
2. si el ULTIMO precio esta a menos de un 1 % del stop o del objetivo, esa no se copia;
3. el motor de riesgo entero con el estado del demo (como cualquier copia) aprueba la MISMA cantidad que el papel;
4. compra limit que CRUZA (el libro del demo casi no se mueve: una post-only podria no llenarse nunca), con el
   `decision_id` de papel y el stop y objetivo de papel ADJUNTOS: OKX crea la OCO al llenarse y el ejecutor, en su
   pasada siguiente, adopta la posicion por esa OCO (camino ya probado).
Antes de comprar se consulta el `clOrdId`: si OKX ya lo tiene, no se compra otra vez.

    python scripts/adoptar_posiciones_demo.py              # EN SECO: dice que haria
    python scripts/adoptar_posiciones_demo.py --aplicar    # compra (solo con la clave del demo)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DISTANCIA_MIN = 0.01        # condicion 4 del propietario del 03/10
MAX_NOCIONAL = 25.0
CRUCE = 1.002               # limite de la compra: un 0,2 % sobre el mejor ask, para que cruce


def _ro(ruta: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    import ccxt

    from core.config import load_settings
    from core.modes import Mode
    from core.secrets import load_secrets
    from execution import comisiones, guardia, ids, ordenes, riesgo
    from execution.espejo import OrdenPapel
    from execution.equity import Foto, lectura, saldo_de_ccxt, virtual
    from execution.precios import al_tick
    from execution.store import cierres, entradas, posiciones
    from risk.types import Instrument

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--exec-db", default=str(REPO / "var" / "ploutos-exec.db"))
    ap.add_argument("--paper-db", default=str(REPO / "var" / "ploutos-paper-ai.db"))
    args = ap.parse_args()

    s, k = load_settings(), load_secrets()
    if not k.has_okx or not k.okx_demo:
        print("Solo con la clave del DEMO. No se hace nada.")
        return 2
    ex = ccxt.okx({"hostname": s.exchange.hostname, "apiKey": k.okx_api_key.get_secret_value(),
                   "secret": k.okx_api_secret.get_secret_value(), "password": k.okx_password.get_secret_value(),
                   "enableRateLimit": True, "timeout": 15_000,
                   "options": {"defaultType": "spot", **guardia.OPCIONES_EXCHANGE}, "headers": {"User-Agent": "ploutos/0.1"}})
    ex.set_sandbox_mode(True)
    ex.load_markets()

    exe = _ro(Path(args.exec_db))
    fila = exe.execute("SELECT ts_ms, capital_usd, datos FROM exec_foto WHERE id = 1").fetchone()
    if fila is None:
        print("El ejecutor no tiene foto: arrancalo antes.")
        return 1
    foto_ms, capital, foto = fila["ts_ms"], fila["capital_usd"], Foto.de_dict(json.loads(fila["datos"]))
    modos = {}
    for r in exe.execute("SELECT modo, activo, motivo FROM exec_modos ORDER BY id"):
        if r["activo"]:
            modos[r["modo"]] = r["motivo"]
        else:
            modos.pop(r["modo"], None)
    modo = max((Mode[m] for m in modos), key=lambda m: m.rank) if modos else Mode.NORMAL
    pos_demo, ent_demo, cie_demo = posiciones(exe), entradas(exe), cierres(exe)

    papel = _ro(Path(args.paper_db))
    abiertas = papel.execute(
        "SELECT p.*, o.setup AS o_setup FROM paper_positions p LEFT JOIN paper_orders o USING (decision_id)"
        " WHERE p.opened_ts_ms < ? ORDER BY p.opened_ts_ms", (foto_ms,)).fetchall()
    ultima = papel.execute("SELECT MAX(ts_ms) FROM paper_market").fetchone()[0]
    corr = {(a, b): c for a, b, c in papel.execute("SELECT a, b, corr FROM paper_correlations WHERE ts_ms = ?",
                                                   (ultima,))}
    usdc = papel.execute("SELECT deviation_pct FROM paper_usdc ORDER BY ts_ms DESC LIMIT 1").fetchone()
    spreads = dict(papel.execute("SELECT symbol, spread_pct FROM paper_market WHERE ts_ms = ?", (ultima,)))

    f = s.exchange.fees
    conf = (f.maker_pct, f.taker_pct)
    hechos = []
    for p in abiertas:
        sim, did = p["symbol"], p["decision_id"]
        linea = {"decision_id": did, "simbolo": sim}
        hechos.append(linea)
        m = ex.markets.get(sim)
        if m is None:
            linea["no"] = "el demo no tiene ese par"
            continue
        reales = comisiones.comision_usdc(ex.private_get_account_trade_fee({"instType": "SPOT",
                                                                            "instId": sim.replace("/", "-")}))
        if comisiones.motivos_par(sim, reales, conf):
            linea["no"] = "comision del demo mas cara que la configurada"
            continue
        if ordenes.consultar_orden(ex, simbolo=sim, decision_id=did) is not None:
            linea["no"] = "OKX ya tiene esa orden: no se compra otra vez"
            continue
        ultimo = float(ex.fetch_ticker(sim)["last"])
        stop, objetivo = float(p["stop_price"]), float(p["target_price"])
        linea.update(ultimo=ultimo, stop=stop, objetivo=objetivo,
                     al_stop_pct=round((ultimo / stop - 1) * 100, 2), al_objetivo_pct=round((objetivo / ultimo - 1) * 100, 2))
        if ultimo <= stop * (1 + DISTANCIA_MIN) or ultimo >= objetivo * (1 - DISTANCIA_MIN):
            linea["no"] = "a menos de un 1 % del stop o del objetivo (condicion 4)"
            continue
        ins = Instrument(sim, float(m["precision"]["price"]), float(m["precision"]["amount"]),
                         float(m["limits"]["amount"]["min"] or 0.0), f.maker_pct / 100, f.taker_pct / 100)
        ask = float(ex.fetch_order_book(sim, 1)["asks"][0][0])
        pre = al_tick(ins, entrada=ask * CRUCE, stop=stop, objetivo=objetivo, cantidad=float(p["qty"]),
                      riesgo_aprobado_usd=float("inf"))
        # El motor de riesgo, con el estado del demo (incluida la que se acaba de comprar en esta misma pasada).
        saldo = virtual(saldo_de_ccxt(ex.fetch_balance(), tuple(s.whitelist)), foto, capital_inicial=capital)
        bids = {x: float(ex.fetch_order_book(x, 1)["bids"][0][0]) for x in s.whitelist
                if abs(saldo.monedas.get(x.split("/")[0], 0.0)) > 0}
        eq = lectura(saldo, bids, whitelist=tuple(s.whitelist), taker=f.taker_pct / 100)
        mercado = riesgo.Mercado(bids=bids, correlaciones=corr, usdc_desviacion_pct=usdc[0] if usdc else None, flags={})
        foto_riesgo = riesgo.estado(ahora_ms=int(time.time() * 1000), equity=eq, modo=modo, posiciones=pos_demo,
                                    entradas=ent_demo, cierres=cie_demo, mercado=mercado)
        orden = OrdenPapel(did, sim, float(p["qty"]), pre.entrada, pre.stop, pre.objetivo, 0, "filled",
                           p["o_setup"] or p["setup"])
        apr = riesgo.aprobar(orden, foto_riesgo, eq, instrumento=ins, spread_pct=spreads.get(sim, 0.0), settings=s)
        linea.update(limite=pre.entrada, stop_tick=pre.stop, objetivo_tick=pre.objetivo, cantidad_papel=float(p["qty"]),
                     motor=apr.motivo, cantidad=apr.cantidad)
        if not apr.enviar:
            linea["no"] = "el motor del demo no lo aprueba"
            continue
        final = al_tick(ins, entrada=pre.entrada, stop=pre.stop, objetivo=pre.objetivo, cantidad=apr.cantidad,
                        riesgo_aprobado_usd=apr.veredicto.risk_usd)
        peticion = ex.create_order_request(sim, "limit", "buy", final.cantidad, final.entrada, {
            "clOrdId": ids.cl_ord_id(did), "tdMode": "cash", "tradeQuoteCcy": "USDC",
            "attachAlgoOrds": [{"attachAlgoClOrdId": ids.algo_cl_ord_id(did),
                                "tpTriggerPx": ex.price_to_precision(sim, final.objetivo), "tpOrdPx": "-1",
                                "slTriggerPx": ex.price_to_precision(sim, final.stop), "slOrdPx": "-1"}]})
        # La guardia de este script (una entrada limit no pasa la del ejecutor, que exige post-only).
        assert peticion["tdMode"] == "cash" and peticion["side"] == "buy" and sim in s.whitelist
        assert peticion["clOrdId"] == ids.cl_ord_id(did) and "tag" not in peticion
        assert float(peticion["px"]) * float(peticion["sz"]) <= MAX_NOCIONAL
        assert final.stop < final.entrada < final.objetivo
        linea["peticion"] = peticion
        if not args.aplicar:
            linea["en_seco"] = "se compraria"
            continue
        r = ex.private_post_trade_order(peticion)
        time.sleep(3)
        o = ordenes.consultar_orden(ex, simbolo=sim, decision_id=did) or {}
        linea.update(respuesta=r, estado=o.get("state"), llenado=o.get("accFillSz"), precio=o.get("avgPx"))
        if o.get("state") == "filled":
            from execution.riesgo import PosicionDemo
            pos_demo = [*pos_demo, PosicionDemo(did, sim, float(o["accFillSz"]), float(o["avgPx"]), final.stop,
                                                final.objetivo, int(o.get("fillTime") or 0))]
    print(json.dumps(hechos, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
