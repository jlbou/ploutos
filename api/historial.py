"""Lo que YA paso, para el panel (fase 5): operaciones cerradas y la linea de tiempo de la IA. SOLO LEE.

- `operaciones`: las cerradas de una cartera, las mas recientes primero; y su CSV (en papel no es
  fiscal: lo sera en la fase 7, con las operaciones reales). Desde el 28/09 lleva tambien las columnas en
  EUROS (PRD: "CSV fiscal"), con el cambio USDC/EUR de OKX de cada instante (`api/cambio.py`):
  valor de adquisicion = (cantidad x entrada + comision de entrada) x cambio de la apertura;
  valor de transmision = (cantidad x salida - comision de salida) x cambio del cierre;
  ganancia = transmision - adquisicion. Es lo que pide un gestor; no es asesoramiento fiscal.
- `decisiones`: por cada vela en que decidio la IA, lo que vio (los candidatos), lo que decidio
  (abrir o saltar, tamanyo, confianza, motivos y riesgos), lo que dijo el motor de riesgo (enviada o
  vetada) y su lectura del mercado. Lo que se ensenya es la JUSTIFICACION QUE ESCRIBE la IA, no su
  razonamiento interno (informe 5.2): el panel lo dice asi.

Todo sale de la base de la cartera (las conexiones, en `mode=ro`, las abre quien llama).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from typing import Any

# "d-... XRP/USDC pullback_trend (4h): entrada 1.5718, stop 1.4879 (-5.34 %), objetivo 1.8638 (+18.58 %), R:R 3.48, ..."
_CANDIDATO = re.compile(r"entrada ([\d.]+), stop ([\d.]+) \(([-\d.]+) %\), objetivo ([\d.]+) \(([+\-\d.]+) %\), R:R ([\d.]+)")
COLUMNAS_CSV = ("cartera", "decision_id", "par", "setup", "abierta_utc", "cerrada_utc", "cantidad", "entrada",
                "salida", "stop", "objetivo", "motivo", "comision_entrada_usd", "comision_salida_usd",
                "neto_usd", "r", "cambio_usdc_eur_apertura", "cambio_usdc_eur_cierre", "valor_adquisicion_eur",
                "valor_transmision_eur", "ganancia_eur")


def _json(texto: str | None, defecto: Any) -> Any:
    try:
        return json.loads(texto) if texto else defecto
    except (TypeError, ValueError):
        return defecto


def operaciones(conn: sqlite3.Connection, cartera: str, limite: int = 200) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    filas = conn.execute(
        "SELECT decision_id, symbol, setup, qty, entry_price, exit_price, stop_price, target_price, opened_ts_ms,"
        " closed_ts_ms, reason, entry_fee_usd, exit_fee_usd, net_pnl_usd, r_multiple FROM paper_trades"
        " ORDER BY closed_ts_ms DESC LIMIT ?", (limite,))
    return [{**dict(f), "cartera": cartera} for f in filas]


def en_euros(f: dict[str, Any], tabla: dict[int, float] | None) -> list[float | str]:
    """Las cinco columnas en euros de una operacion; vacias si falta alguno de los dos cambios."""
    from api.cambio import cambio

    c_ab = cambio(f["opened_ts_ms"], tabla) if tabla else None
    c_ci = cambio(f["closed_ts_ms"], tabla) if tabla else None
    if c_ab is None or c_ci is None:
        return ["", "", "", "", ""]
    adquisicion = (f["qty"] * f["entry_price"] + f["entry_fee_usd"]) * c_ab
    transmision = (f["qty"] * f["exit_price"] - f["exit_fee_usd"]) * c_ci
    return [c_ab, c_ci, round(adquisicion, 6), round(transmision, 6), round(transmision - adquisicion, 6)]


def csv_operaciones(filas: list[dict[str, Any]], tabla: dict[int, float] | None = None) -> str:
    """`tabla`: {hora: apertura de USDC/EUR} (`api.cambio.aperturas`); sin ella, las columnas en euros vacias."""
    from datetime import UTC, datetime

    def utc(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(COLUMNAS_CSV)
    for f in sorted(filas, key=lambda x: x["closed_ts_ms"]):
        w.writerow([f["cartera"], f["decision_id"], f["symbol"], f["setup"], utc(f["opened_ts_ms"]),
                    utc(f["closed_ts_ms"]), f["qty"], f["entry_price"], f["exit_price"], f["stop_price"],
                    f["target_price"], f["reason"], round(f["entry_fee_usd"], 6), round(f["exit_fee_usd"], 6),
                    round(f["net_pnl_usd"], 6), round(f["r_multiple"], 4), *en_euros(f, tabla)])
    return salida.getvalue()


def _candidato(detalle: str | None) -> dict[str, float] | None:
    m = _CANDIDATO.search(detalle or "")
    if not m:
        return None
    entrada, stop, stop_pct, objetivo, obj_pct, rr = (float(x) for x in m.groups())
    return {"entrada": entrada, "stop": stop, "stop_pct": stop_pct, "objetivo": objetivo, "objetivo_pct": obj_pct,
            "rr": rr}


def decisiones(conn: sqlite3.Connection, limite: int = 30) -> list[dict[str, Any]]:
    """La linea de tiempo de la IA, la vela mas reciente primero."""
    conn.row_factory = sqlite3.Row
    try:
        llamadas = conn.execute(
            "SELECT id, ts_ms, called_ms, outcome, valid, reason, n_candidates, latency_s, structured"
            " FROM ai_calls WHERE kind = 'decision' ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    except sqlite3.OperationalError:
        return []                                  # una base sin tablas de la IA (la del baseline)
    out = []
    for ll in llamadas:
        ts = ll["ts_ms"]
        propias = {d["ref"]: d for d in conn.execute("SELECT * FROM ai_decisions WHERE call_id = ?", (ll["id"],))}
        motor = {}
        for d in conn.execute("SELECT decision_id, kind, detail FROM paper_decisions WHERE ts_ms = ?"
                              " AND kind IN ('submitted', 'vetoed')", (ts,)):
            motor[d["decision_id"]] = ("enviada", None) if d["kind"] == "submitted" else ("vetada", d["detail"])
        candidatos = []
        for c in conn.execute("SELECT decision_id, symbol, setup, detail FROM paper_decisions WHERE ts_ms = ?"
                              " AND kind = 'candidate' ORDER BY id", (ts,)):
            ia = propias.get(c["decision_id"])
            candidatos.append({
                "decision_id": c["decision_id"], "simbolo": c["symbol"], "setup": c["setup"],
                "numeros": _candidato(c["detail"]),
                "ia": None if ia is None else {
                    "tipo": ia["type"], "multiplicador": ia["size_multiplier"], "confianza": ia["confidence"],
                    "motivos": _json(ia["reasons"], []), "riesgos": _json(ia["risks"], []),
                    "ejecutada": bool(ia["executed"])},
                "motor": motor.get(c["decision_id"], (None, None))[0],
                "veto": motor.get(c["decision_id"], (None, None))[1],
            })
        out.append({
            "vela_ms": ts, "llamada_ms": ll["called_ms"], "resultado": ll["outcome"], "valida": bool(ll["valid"]),
            "motivo": ll["reason"], "latencia_s": ll["latency_s"],
            "lectura": _json(ll["structured"], {}).get("market_read"),
            "candidatos": candidatos,
        })
    return out


def curva(carteras: dict[str, sqlite3.Connection | None], principal: sqlite3.Connection | None,
          capital: float, simbolo_btc: str = "BTC/USDC") -> dict[str, list[list[float]]]:
    """La curva comparada (PRD 10): el equity de cada cartera por vela y "comprar y esperar BTC" con el
    mismo capital desde la primera vela de las carteras. [[ts_ms, valor], ...], en orden."""
    out: dict[str, list[list[float]]] = {}
    for nombre, conn in carteras.items():
        if conn is not None:
            out[nombre] = [[r[0], r[1]] for r in conn.execute("SELECT ts_ms, equity_usd FROM paper_equity ORDER BY ts_ms")]
    inicio = min((s[0][0] for s in out.values() if s), default=None)
    if principal is not None and inicio is not None:
        velas = principal.execute(
            "SELECT ts_open_ms, close FROM candles WHERE symbol = ? AND timeframe = '4h' AND closed = 1"
            " AND ts_open_ms >= ? ORDER BY ts_open_ms", (simbolo_btc, inicio)).fetchall()
        if velas:
            base = velas[0][1]
            out["btc"] = [[ts, round(capital * c / base, 4)] for ts, c in velas]
    return out


VELA_4H_MS = 4 * 3600_000
VELAS_ANTES = 12        # dos dias antes de la entrada: el contexto en que se entro
MAX_VELAS = 200         # ~33 dias; una posicion mas vieja ensenya solo las ultimas


def velas_posicion(principal: sqlite3.Connection, simbolo: str, desde_ms: int) -> list[list[float]]:
    """Las velas de 4 h de una moneda para el grafico de una posicion abierta (el propietario, 01/10): desde
    `VELAS_ANTES` velas antes de `desde_ms` (la apertura) hasta AHORA. [[ts_ms, open, high, low, close], ...].

    La base solo guarda las velas de 4 h CERRADAS; la que esta en curso se arma con las de 1 minuto desde su
    apertura (abre con la primera, cierra con la ultima, maximo y minimo de todas). Es para MIRAR: ninguna
    decision usa esa vela (los indicadores, solo con velas cerradas).
    """
    inicio = desde_ms - VELAS_ANTES * VELA_4H_MS
    velas = [list(r) for r in principal.execute(
        "SELECT ts_open_ms, open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '4h'"
        " AND closed = 1 AND ts_open_ms >= ? ORDER BY ts_open_ms", (simbolo, inicio))]
    if not velas:
        # Sin ninguna cerrada no se sabe cual es la vela de ahora: armarla con minutos de hace dias enganyaria.
        return []
    en_curso = velas[-1][0] + VELA_4H_MS
    minutos = principal.execute(
        "SELECT open, high, low, close FROM candles WHERE symbol = ? AND timeframe = '1m' AND ts_open_ms >= ?"
        " AND ts_open_ms < ? ORDER BY ts_open_ms", (simbolo, en_curso, en_curso + VELA_4H_MS)).fetchall()
    if minutos:
        velas.append([en_curso, minutos[0][0], max(m[1] for m in minutos), min(m[2] for m in minutos),
                      minutos[-1][3]])
    return velas[-MAX_VELAS:]
