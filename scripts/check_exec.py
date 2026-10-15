"""El juez de la fase 4: "1 semana sin descuadres" en el demo (PRD 12; decision 5 del propietario del 24/09).

Pide a OKX (solo LECTURA) el historial de ordenes, OCO y llenados desde la foto del saldo, lee la base del ejecutor
(sus operaciones y cada pasada de la conciliacion) y la cartera de la IA en papel (lo que el demo tenia que copiar), y
se lo pasa al nucleo puro `execution/juez.py`. **No usa la logica del ejecutor** (conciliacion, plan, espejo,
peticiones): si el juez razonara igual, un error compartido pasaria sin que nadie lo viera. Lee OKX y las bases por su
cuenta; de `execution/` solo usa el juez y `ids` (el contrato de los identificadores).

    exit 0 -> CUMPLIDO (7 dias sin descuadres)
    exit 1 -> FALLA (se dice cual)
    exit 2 -> todo en orden, pero aun no hay una semana (o el ejecutor no ha arrancado nunca)

    ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_exec.py'
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from execution import juez as j  # noqa: E402

# Los pares que el demo opera (02/10: los 4 con par contra USDC y la comision configurada; NEAR, solo en papel).
PARES_DEMO = ("BTC/USDC", "ETH/USDC", "SOL/USDC", "DOGE/USDC")
SALIDAS_A_MERCADO = ("news", "manual")
CODIGOS_OKX = ("50101", "50105", "50110", "50111", "50113", "50114", "50119", "50123")


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sim(inst_id: str) -> str:
    return str(inst_id).replace("-", "/")


# --- De lo que da OKX a lo que mira el juez (puro) -------------------------------------------------------------


def lanzadas_por_oco(ocos: Iterable[dict[str, Any]]) -> dict[str, str]:
    """ordId de la orden que lanzo una OCO al saltar -> algoClOrdId de esa OCO."""
    out = {}
    for a in ocos:
        for oid in [a.get("ordId"), *(a.get("ordIdList") or [])]:
            if oid:
                out[str(oid)] = str(a.get("algoClOrdId") or "")
    return out


def okx_para_el_juez(ordenes: list[dict], ocos: list[dict], fills: list[dict], saldos_inicio: dict[str, float],
                     saldos_fin: dict[str, float]) -> j.Okx:
    de_oco = lanzadas_por_oco(ocos)
    js_ordenes = tuple(
        j.Orden(str(o.get("clOrdId") or ""), _sim(o["instId"]), str(o.get("side")), str(o.get("ordType")),
                str(o.get("tdMode") or ""), _f(o.get("sz")), _f(o.get("accFillSz")), str(o.get("state")),
                int(o.get("cTime") or 0))
        for o in ordenes if str(o.get("ordId")) not in de_oco)      # las que lanza una OCO van con su OCO
    js_ocos = tuple(
        j.Oco(str(a.get("algoClOrdId") or ""), _sim(a["instId"]), str(a.get("side")), str(a.get("tdMode") or ""),
              _f(a.get("sz")), str(a.get("state")), int(a.get("cTime") or 0),
              None if a.get("state") == "live" else int(a.get("uTime") or 0))
        for a in ocos)
    js_fills = []
    for f in fills:
        propio = de_oco.get(str(f.get("ordId"))) or str(f.get("clOrdId") or "")
        comision = -_f(f.get("fee")) if f.get("feeCcy") in ("USDC", None, "") else 0.0
        js_fills.append(j.Fill(propio, _sim(f["instId"]), str(f.get("side")), _f(f.get("fillSz")),
                               _f(f.get("fillPx")), comision, int(f.get("ts") or f.get("fillTime") or 0)))
    return j.Okx(js_ordenes, js_ocos, tuple(js_fills), saldos_inicio, saldos_fin)


def recortar(okx: j.Okx, hasta_ms: int) -> j.Okx:
    """OKX tal como estaba en `hasta_ms` (para juzgar una COPIA de la base del ejecutor, `--ahora-ms`).

    Se quita lo que paso despues: las ordenes y OCO creadas mas tarde, los fills posteriores y su efecto en los
    saldos (los de OKX son los de AHORA). Una OCO que acabo despues no hace falta tocarla: el juez corta sus tramos en
    `hasta_ms` y la cuenta como viva hasta ahi. Lo que no se reconstruye: el estado de una orden que se lleno despues
    (sigue el de ahora); el juez no lo usa para juzgar.
    """
    fills = tuple(f for f in okx.fills if f.ts_ms <= hasta_ms)
    saldos_fin = dict(okx.saldos_fin)
    for f in okx.fills:
        if f.ts_ms > hasta_ms:
            signo = 1 if f.lado == "buy" else -1
            base = f.simbolo.split("/")[0]
            saldos_fin[base] = saldos_fin.get(base, 0.0) - signo * f.cantidad
            saldos_fin["USDC"] = saldos_fin.get("USDC", 0.0) + signo * f.cantidad * f.precio + f.comision_usdc
    ocos = tuple(a for a in okx.ocos if a.creada_ms <= hasta_ms)
    ordenes = tuple(o for o in okx.ordenes if o.creada_ms <= hasta_ms)
    return j.Okx(ordenes, ocos, fills, okx.saldos_inicio, saldos_fin)


# --- Las bases -------------------------------------------------------------------------------------------------


def _ro(ruta: Path) -> sqlite3.Connection | None:
    if not ruta.exists():
        return None
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def bot_de(conn: sqlite3.Connection) -> j.Bot:
    ops = [j.Operacion(r["decision_id"], r["simbolo"], r["cantidad"], r["entrada"])
           for r in conn.execute("SELECT * FROM exec_posiciones")]
    ops += [j.Operacion(r["decision_id"], r["simbolo"], r["cantidad"], r["entrada"], r["cantidad"], r["salida"])
            for r in conn.execute("SELECT * FROM exec_cierres")]
    pasadas = [j.Pasada(r["ts_ms"], tuple(f"{d['tipo']}: {d['detalle']}" for d in json.loads(r["descuadres"])))
               for r in conn.execute("SELECT ts_ms, descuadres FROM exec_pasadas ORDER BY ts_ms")]
    return j.Bot(tuple(ops), tuple(pasadas))


def adoptadas_de(conn: sqlite3.Connection, foto_ms: int) -> set[str]:
    """Las posiciones de la cartera de la IA que estaban ABIERTAS en la foto (decision del propietario del 03/10: se adoptaron
    una vez para arrancar la fase 4). Se mira en papel, no en lo que apunto el ejecutor."""
    abiertas = {r[0] for r in conn.execute("SELECT decision_id FROM paper_positions WHERE opened_ts_ms < ?", (foto_ms,))}
    abiertas |= {r[0] for r in conn.execute(
        "SELECT decision_id FROM paper_trades WHERE opened_ts_ms < ? AND closed_ts_ms >= ?", (foto_ms, foto_ms))}
    return abiertas


def niveles_de(conn: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """decision_id -> (stop, objetivo) de las ordenes de la cartera de la IA en papel."""
    return {r[0]: (r[1], r[2]) for r in conn.execute("SELECT decision_id, stop_price, target_price FROM paper_orders")}


def espejo_de(conn: sqlite3.Connection, desde_ms: int, tf_ms: int, pares: Iterable[str]) -> tuple[set[str], set[str]]:
    """(decisiones que la cartera de la IA envio en papel en los pares del demo, las que cerro a mercado)."""
    pares = tuple(pares)
    marcas = ",".join("?" * len(pares))
    enviadas = {r[0] for r in conn.execute(
        f"SELECT decision_id FROM paper_orders WHERE created_ts_ms + ? >= ? AND symbol IN ({marcas})",
        (tf_ms, desde_ms, *pares))}
    salidas = {r[0] for r in conn.execute(
        f"SELECT decision_id FROM paper_trades WHERE closed_ts_ms >= ? AND reason IN ({','.join('?' * 2)})",
        (desde_ms, *SALIDAS_A_MERCADO))}
    return enviadas, salidas


# --- OKX (solo lectura) ----------------------------------------------------------------------------------------


def _todo(llamada, params: dict[str, Any], desde_ms: int) -> list[dict[str, Any]]:
    """Pagina hacia atras (`after` = el ultimo id) hasta pasar de `desde_ms`."""
    out: list[dict[str, Any]] = []
    clave = None
    while True:
        p = dict(params, limit="100", **({"after": clave} if clave else {}))
        datos = list((llamada(p) or {}).get("data") or [])
        out += [d for d in datos if int(d.get("cTime") or d.get("ts") or 0) >= desde_ms]
        if len(datos) < 100 or int(datos[-1].get("cTime") or datos[-1].get("ts") or 0) < desde_ms:
            return out
        clave = datos[-1].get("ordId") or datos[-1].get("algoId") or datos[-1].get("billId")


def leer_okx(ex: Any, desde_ms: int, monedas: Iterable[str]) -> tuple[list, list, list, dict[str, float]]:
    ordenes = _todo(ex.private_get_trade_orders_pending, {"instType": "SPOT"}, desde_ms)
    ordenes += _todo(ex.private_get_trade_orders_history_archive, {"instType": "SPOT"}, desde_ms)
    ocos = _todo(ex.private_get_trade_orders_algo_pending, {"ordType": "oco", "instType": "SPOT"}, desde_ms)
    for estado in ("effective", "canceled"):
        ocos += _todo(ex.private_get_trade_orders_algo_history,
                      {"ordType": "oco", "state": estado, "instType": "SPOT"}, desde_ms)
    fills = _todo(ex.private_get_trade_fills_history, {"instType": "SPOT"}, desde_ms)
    total = ex.fetch_balance().get("total") or {}
    saldos = {m: float(total.get(m) or 0.0) for m in monedas}
    return ordenes, ocos, fills, saldos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exec-db", default=str(REPO / "var" / "ploutos-exec.db"))
    ap.add_argument("--paper-db", default=str(REPO / "var" / "ploutos-paper-ai.db"))
    ap.add_argument("--pares", default=",".join(PARES_DEMO))
    ap.add_argument("--tf-ms", type=int, default=4 * 3600_000)
    ap.add_argument("--ahora-ms", type=int, default=None,
                    help="juzgar como si fuera este instante (ms UTC): para una COPIA de la base (simulacro de "
                         "restauracion); lo que OKX hizo despues se quita")
    args = ap.parse_args()
    pares = tuple(p.strip() for p in args.pares.split(",") if p.strip())

    conn = _ro(Path(args.exec_db))
    if conn is None or conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'exec_foto'").fetchone() is None:
        print("El ejecutor no ha arrancado nunca (sin base o sin foto): nada que juzgar todavia.")
        return 2
    foto = conn.execute("SELECT ts_ms, datos FROM exec_foto WHERE id = 1").fetchone()
    if foto is None:
        print("El ejecutor no ha guardado la foto del saldo: nada que juzgar todavia.")
        return 2
    datos_foto = json.loads(foto["datos"])
    saldos_inicio = {"USDC": datos_foto["usdc_total"], **datos_foto["monedas"]}
    papel = _ro(Path(args.paper_db))
    if papel is None:
        print("FALLA: sin la base de la cartera de la IA no se puede juzgar el espejo.")
        return 1
    espejo, salidas = espejo_de(papel, foto["ts_ms"], args.tf_ms, pares)

    import ccxt

    from core.config import load_settings
    from core.secrets import load_secrets
    from execution import guardia
    settings, secretos = load_settings(), load_secrets()
    if not secretos.has_okx or not secretos.okx_demo:
        print("FALLA: sin la clave del demo no se puede pedir el historial a OKX.")
        return 1
    ex = ccxt.okx({"hostname": settings.exchange.hostname, "apiKey": secretos.okx_api_key.get_secret_value(),
                   "secret": secretos.okx_api_secret.get_secret_value(),
                   "password": secretos.okx_password.get_secret_value(), "enableRateLimit": True,
                   "timeout": 15_000, "options": {"defaultType": "spot", **guardia.OPCIONES_EXCHANGE},
                   "headers": {"User-Agent": "ploutos/0.1"}})
    ex.set_sandbox_mode(True)
    try:
        ex.load_markets()
        ordenes, ocos, fills, saldos_fin = leer_okx(ex, foto["ts_ms"], saldos_inicio)
    except Exception as exc:  # noqa: BLE001 - solo el tipo y el codigo de OKX
        codigo = next((c for c in CODIGOS_OKX if c in str(exc)), "")
        print(f"FALLA: no se pudo leer OKX ({type(exc).__name__} {codigo})".strip())
        return 1
    lotes = {s: float(ex.markets[s]["precision"]["amount"]) for s in pares if s in ex.markets}
    okx = okx_para_el_juez(ordenes, ocos, fills, saldos_inicio, saldos_fin)
    hasta_ms = int(time.time() * 1000)
    if args.ahora_ms is not None:
        hasta_ms = args.ahora_ms
        okx = recortar(okx, hasta_ms)
        print(f"(juzgado como si fueran las {j._hora(hasta_ms)} UTC: lo que OKX hizo despues no cuenta)")
    v = j.juzgar(okx, bot_de(conn), whitelist=pares, lotes=lotes, espejo=espejo, hasta_ms=hasta_ms,
                 salidas_espejo=salidas, niveles=niveles_de(papel), adoptadas=adoptadas_de(papel, foto["ts_ms"]))
    dias = v.cubierto_ms / 86_400_000
    print(f"Ejecutor del demo: {dias:.1f} dias de conciliacion desde la foto")
    for k, n in v.medidas.items():
        print(f"  {k}: {n}")
    for f in v.fallas:
        print(f"  FALLA {f}")
    if v.codigo == 0:
        print("\nRESULTADO: CUMPLIDO (una semana sin descuadres).")
    elif v.codigo == 2 and v.cubierto_ms >= j.SEMANA_MS:
        print(f"\nRESULTADO: {dias:.1f} dias sin descuadres, pero ninguna operacion completa en el demo (compra, OCO y"
              " cierre): la semana no vale sin actividad (decision del propietario del 03/10). Aun no.")
    elif v.codigo == 2:
        print(f"\nRESULTADO: sin descuadres, pero solo {dias:.1f} dias de 7 ({v.completas} operacion(es) completa(s);"
              f" hace falta al menos {j.MIN_COMPLETAS}). Aun no.")
    else:
        print(f"\nRESULTADO: FALLA ({len(v.fallas)}).")
    return v.codigo


if __name__ == "__main__":
    raise SystemExit(main())
