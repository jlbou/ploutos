"""La "foto" del estado para el panel (fase 5; docs/diseno-api-panel.md). SOLO LEE.

Una funcion, `foto()`, que junta en un diccionario todo lo que ensenya el panel: por cartera (el
baseline y la de la IA) equity, P&L del dia, drawdown, distancia al suelo, posiciones con su P&L en
dolares y en R, entradas pendientes y modos; la pausa y la parada; las flags de noticias; lo fresco
de cada servicio; los limites duros y el estado del token de la IA.

Reglas (decisiones del propietario del 25/09):
- **Solo lectura**: recibe conexiones ya abiertas en `mode=ro` (las abre quien llama).
- **Una base que falta o no se deja leer es "sin datos", nunca ceros**: el panel lo ensenya en gris.
- **El estado de cada servicio se DEDUCE de lo fresco de su base**, no de un diccionario en memoria.
- **Nunca nombra a Claude**: "IA".
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.config import Settings
from core.modes import Mode
from data.news import store as noticias_db
from features.news import bases_de, event_flags, flags
from notify import control
from notify.comandos import reconstruir
from notify.resumen import resumen_desde_base
from portfolio.store import load_modes
from risk.limits import SLIDER_LEVELS

H4 = 4 * 3600_000
MIN = 60_000
# Cuanto puede tardar cada servicio antes de ir "tarde" y antes de darlo por "caido", en ms.
# La ingesta guarda velas de 1 m; el papel procesa cada vela de 4 h al minuto de cerrar; noticias
# lee cada 5 min; Telegram da una vuelta cada ~25 s.
UMBRALES = {
    "ingesta": (3 * MIN, 10 * MIN),
    "noticias": (15 * MIN, 60 * MIN),
    "telegram": (5 * MIN, 15 * MIN),
    # El ejecutor del demo (fase 4) guarda el equity cada minuto mientras OKX contesta.
    "ejecutor": (3 * MIN, 10 * MIN),
    # Los medios en sombra (07/10) leen sus 24 RSS cada 10 min.
    "medios": (25 * MIN, 60 * MIN),
    # El papel de L (10/10) se rehace una vez al dia, a las 00:20 UTC.
    "papel_l": (26 * 60 * MIN, 50 * 60 * MIN),
}
# El papel de L (`docs/diseno-papel-l.md`): las mismas fechas que `scripts/papel_l.py` (un test lo comprueba).
PAPEL_L = {"inicio": "2026-10-12", "fin": "2027-01-11", "corte_pct": 25}
MARGEN_VELA_MS = 10 * MIN          # tras cerrar una vela de 4 h, el papel tiene 10 min para procesarla


def _estado(retraso_ms: int | None, tarde_ms: int, caido_ms: int) -> str:
    if retraso_ms is None:
        return "sin_datos"
    if retraso_ms <= tarde_ms:
        return "ok"
    return "tarde" if retraso_ms <= caido_ms else "caido"


def estado_del_papel(ultima_vela_ms: int | None, ahora_ms: int) -> str:
    """ok si ya proceso la ultima vela de 4 h que tenia que procesar (con 10 min de margen)."""
    if ultima_vela_ms is None:
        return "sin_datos"
    esperada = (ahora_ms - MARGEN_VELA_MS) // H4 * H4 - H4      # apertura de la ultima vela cerrada
    retraso = esperada - ultima_vela_ms
    if retraso <= 0:
        return "ok"
    return "tarde" if retraso <= H4 else "caido"


def _precios(principal: sqlite3.Connection | None, simbolos: set[str]) -> dict[str, tuple[float, int]]:
    """El ultimo cierre de 1 m de cada simbolo (precio, apertura de esa vela): con el se valoran las
    posiciones abiertas."""
    if principal is None or not simbolos:
        return {}
    out = {}
    for s in simbolos:
        fila = principal.execute(
            "SELECT close, ts_open_ms FROM candles WHERE symbol = ? AND timeframe = '1m' AND closed = 1"
            " ORDER BY ts_open_ms DESC LIMIT 1", (s,)).fetchone()
        if fila is not None:
            out[s] = (float(fila[0]), int(fila[1]))
    return out


def equity_ahora(inicial: float, realizado: float, posiciones: list[dict[str, Any]], taker: float) -> float | None:
    """La MISMA formula que `PaperLedger.equity_usd` (regla 6, version de papel), con los precios del
    ultimo minuto en vez de los del cierre de la vela. Es una ESTIMACION para mirar (el propietario, 26/09): no la
    usa ninguna regla ni ningun juez. Sin precio de alguna posicion, no se estima (None)."""
    total = inicial + realizado
    for p in posiciones:
        if p.get("precio") is None:
            return None
        valor = p["qty"] * p["precio"]
        total += valor - p["qty"] * p["entry_price"] - p["entry_fee_usd"] - valor * taker
    return total


def monedas(conn: sqlite3.Connection, whitelist: tuple[str, ...], posiciones: list[dict[str, Any]],
            pendientes: list[dict[str, Any]]) -> dict[str, Any]:
    """Donde se quedo cada moneda en la ULTIMA vela procesada, y por que (vista por moneda, informe 5.3).

    La posicion y la entrada pendiente mandan (son el estado de ahora); si no, lo que paso en esa vela:
    enviada, vetada por el motor, candidato que no se abrio, descartada por un filtro, o sin senyal.
    """
    fila = conn.execute("SELECT MAX(ts_ms) FROM paper_decisions").fetchone()
    vela = fila[0] if fila else None
    por: dict[str, dict[str, set | str]] = {s: {"kinds": set(), "detalle": ""} for s in whitelist}
    if vela is not None:
        for r in conn.execute("SELECT symbol, kind, detail FROM paper_decisions WHERE ts_ms = ?", (vela,)):
            if r["symbol"] in por:
                por[r["symbol"]]["kinds"].add(r["kind"])
                if r["kind"] in ("filtered", "vetoed", "sin_senyal"):   # sin_senyal: desde el 29/09
                    por[r["symbol"]]["detalle"] = r["detail"] or ""
    con_posicion = {p["symbol"] for p in posiciones}
    con_pendiente = {o["symbol"] for o in pendientes}
    out = {}
    for s in whitelist:
        k, detalle = por[s]["kinds"], por[s]["detalle"]
        if s in con_posicion:
            estado, detalle = "posicion", ""
        elif s in con_pendiente:
            estado, detalle = "pendiente", ""
        elif "submitted" in k:
            estado = "enviada"
        elif "vetoed" in k:
            estado = "vetada"
        elif "candidate" in k:
            estado, detalle = "no_abierta", "candidato que no se abrio"
        elif "filtered" in k:
            estado = "descartada"
        else:
            estado = "sin_senyal"
        # `pasos`: lo que paso EN ESTA VELA (una posicion abierta antes no ha recorrido el camino de esta vela).
        out[s] = {"estado": estado, "detalle": detalle, "pasos": sorted(k)}
    return {"vela_ms": vela, "monedas": out}


def flujo(conn: sqlite3.Connection, vela: int | None, whitelist: tuple[str, ...], posiciones: int, pendientes: int,
          max_posiciones: int) -> dict[str, Any]:
    """El camino de la ULTIMA vela procesada, paso a paso (PRD 10: "diagrama de flujo por nodos, vista de sistema").

    Cuantas monedas pasan los filtros, cuantos candidatos salen, que hizo quien decide (la llamada a la IA, si la
    hubo), que dijo el motor de riesgo, y como quedan ordenes y posiciones AHORA. La vista por moneda (donde se
    quedo cada una) sale de `monedas`.
    """
    if vela is None:
        return {"vela_ms": None}
    descartadas: set[str] = set()
    cuenta = {"candidate": 0, "submitted": 0, "vetoed": 0}
    for r in conn.execute("SELECT symbol, kind FROM paper_decisions WHERE ts_ms = ?", (vela,)):
        if r[1] == "filtered" and r[0] in whitelist:
            descartadas.add(r[0])
        elif r[1] in cuenta:
            cuenta[r[1]] += 1
    try:
        ll = conn.execute("SELECT outcome, n_candidates, latency_s FROM ai_calls WHERE ts_ms = ? AND kind = 'decision'"
                          " ORDER BY id DESC LIMIT 1", (vela,)).fetchone()
    except sqlite3.OperationalError:
        ll = None                                   # la base del baseline no tiene tablas de la IA
    return {
        "vela_ms": vela, "monedas": len(whitelist), "pasan": len(whitelist) - len(descartadas),
        "descartadas": len(descartadas), "candidatos": cuenta["candidate"], "enviadas": cuenta["submitted"],
        "vetadas": cuenta["vetoed"],
        "llamada_ia": None if ll is None else {"resultado": ll[0], "candidatos": ll[1], "latencia_s": ll[2]},
        "pendientes": pendientes, "posiciones": posiciones, "max_posiciones": max_posiciones,
    }


def cartera(conn: sqlite3.Connection | None, nombre: str, settings: Settings, ahora_ms: int,
            principal: sqlite3.Connection | None) -> dict[str, Any]:
    if conn is None:
        return {"disponible": False}
    conn.row_factory = sqlite3.Row
    hoy = datetime.fromtimestamp(ahora_ms / 1000, tz=UTC).date()
    r = resumen_desde_base(conn, nombre, hoy, settings)
    tiene_velas = conn.execute("SELECT 1 FROM paper_equity LIMIT 1").fetchone() is not None
    try:
        modos = load_modes(conn)
        activos = sorted(m.name for m in modos.active)
        efectivo = modos.effective.name
    except sqlite3.OperationalError:
        activos, efectivo = [], Mode.NORMAL.name

    posiciones = [dict(p) for p in conn.execute("SELECT * FROM paper_positions ORDER BY opened_ts_ms")]
    precios = _precios(principal, {p["symbol"] for p in posiciones})
    for p in posiciones:
        precio, _ts = precios.get(p["symbol"], (None, None))
        riesgo = p["qty"] * (p["entry_price"] - p["stop_price"])
        p["precio"] = precio
        p["pnl_usd"] = None if precio is None else round((precio - p["entry_price"]) * p["qty"], 4)
        p["pnl_r"] = None if precio is None or riesgo <= 0 else round(p["pnl_usd"] / riesgo, 3)
    pendientes = [dict(o) for o in conn.execute(
        "SELECT decision_id, symbol, setup, qty, limit_price, stop_price, target_price, created_ts_ms"
        " FROM paper_orders WHERE state = 'pending' ORDER BY created_ts_ms")]

    realizado = conn.execute("SELECT COALESCE(SUM(net_pnl_usd), 0) FROM paper_trades").fetchone()[0]
    ahora = equity_ahora(settings.capital.initial_capital_usd, float(realizado), posiciones,
                         settings.exchange.fees.taker_pct / 100)
    por_moneda = monedas(conn, tuple(settings.whitelist), posiciones, pendientes)
    return {
        "disponible": True,
        "tiene_velas": tiene_velas,
        # Estimacion en directo (precios del ultimo minuto); la oficial es `equity_usd`, la de la vela.
        "equity_ahora_usd": ahora if tiene_velas else None,
        "equity_ahora_ms": min((ts for _p, ts in precios.values()), default=None),
        "equity_usd": r.equity_usd if tiene_velas else None,
        "cambio_hoy_usd": r.cambio_dia_usd,
        "drawdown_max_pct": r.drawdown_max_pct,
        "distancia_suelo_usd": (r.equity_usd - settings.capital.floor_usd) if tiene_velas else None,
        "cerradas_hoy": r.cerradas_hoy,
        "resultado_hoy_usd": r.resultado_hoy_usd,
        "posiciones": posiciones,
        "pendientes": pendientes,
        "modo": efectivo,
        "modos_activos": activos,
        "ultima_vela_ms": r.ultima_vela_ms,
        "estado": estado_del_papel(r.ultima_vela_ms, ahora_ms),
        "llamadas_ia": r.llamadas_claude,
        "por_moneda": por_moneda,
        "flujo": flujo(conn, por_moneda["vela_ms"], tuple(settings.whitelist), len(posiciones), len(pendientes),
                       settings.risk.max_positions),
    }


def ejecutor(conn: sqlite3.Connection | None, ahora_ms: int,
             principal: sqlite3.Connection | None = None) -> dict[str, Any]:
    """El ejecutor del demo (fase 4), leido de su base en `mode=ro` con SQL propio: el panel no importa `execution/`.

    La OCO de cada posicion: "viva" salvo que la ultima conciliacion la dejara sin OCO (`sin_oco`) o se este vendiendo.
    Las posiciones llevan los mismos campos que las de papel (para las mismas tarjetas): el precio de ahora es el del
    MERCADO REAL (la ingesta), no el del libro del demo, que se le parece mucho pero no es el mismo
    (`docs/preparacion-fase-4.md` 12): `precio_aprox`.
    """
    vacio: dict[str, Any] = {"disponible": False}
    if conn is None:
        return vacio
    try:
        foto_fila = conn.execute("SELECT ts_ms, capital_usd FROM exec_foto WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return vacio
    if foto_fila is None:
        return vacio
    modos: dict[str, str] = {}
    for m, activo, motivo in conn.execute("SELECT modo, activo, motivo FROM exec_modos ORDER BY id"):
        if activo:
            modos[m] = motivo
        else:
            modos.pop(m, None)
    eq = conn.execute("SELECT ts_ms, equity_usd, fiable FROM exec_equity ORDER BY ts_ms DESC LIMIT 1").fetchone()
    pasada = conn.execute("SELECT ts_ms, cuadra, descuadres, sin_oco FROM exec_pasadas ORDER BY ts_ms DESC LIMIT 1"
                          ).fetchone()
    sin_oco = set(json.loads(pasada[3])) if pasada else set()
    filas = conn.execute("SELECT decision_id, simbolo, cantidad, entrada, stop, objetivo, abierta_ms, vendiendo_ms"
                         " FROM exec_posiciones ORDER BY abierta_ms").fetchall()
    precios = _precios(principal, {r[1] for r in filas})
    posiciones = []
    for r in filas:
        did, simbolo, qty, entrada, stop, objetivo = r[0], r[1], r[2], r[3], r[4], r[5]
        precio = precios.get(simbolo, (None, 0))[0]
        riesgo = (entrada - stop) * qty
        pnl = None if precio is None else round((precio - entrada) * qty, 4)
        posiciones.append({
            "decision_id": did, "symbol": simbolo, "qty": qty, "entry_price": entrada, "stop_price": stop,
            "target_price": objetivo, "opened_ts_ms": r[6], "setup": SETUP_DE_TAG.get(did.rsplit("-", 1)[-1], ""),
            "precio": precio, "precio_aprox": True, "pnl_usd": pnl,
            "pnl_r": None if pnl is None or riesgo <= 0 else round(pnl / riesgo, 3),
            "oco": "vendiendo" if r[7] else ("sin_oco" if did in sin_oco else "viva")})
    entradas = [{"decision_id": r[0], "simbolo": r[1], "cantidad": r[2], "limite": r[3], "stop": r[4],
                 "objetivo": r[5], "creada_ms": r[6]}
                for r in conn.execute("SELECT decision_id, simbolo, cantidad, limite, stop, objetivo, creada_ms"
                                      " FROM exec_entradas ORDER BY creada_ms")]
    dia = datetime.fromtimestamp(ahora_ms / 1000, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    hoy = conn.execute("SELECT COUNT(*), COALESCE(SUM(pnl_usd), 0) FROM exec_cierres WHERE cerrada_ms >= ?",
                       (int(dia.timestamp() * 1000),)).fetchone()
    tratadas = [{"decision_id": r[0], "ts_ms": r[1], "que": r[2], "motivo": r[3]}
                for r in conn.execute("SELECT decision_id, ts_ms, que, motivo FROM exec_tratadas"
                                      " ORDER BY ts_ms DESC LIMIT 8")]
    return {
        "disponible": True,
        "foto_ms": foto_fila[0],
        "capital_usd": foto_fila[1],
        "modo": max((Mode[m] for m in modos), key=lambda m: m.rank).name if modos else "NORMAL",   # el mas restrictivo
        "modos": modos,
        "equity_usd": eq[1] if eq else None,
        "equity_fiable": bool(eq[2]) if eq else None,
        "equity_ms": eq[0] if eq else None,
        "posiciones": posiciones,
        "entradas": entradas,
        "cerradas_hoy": hoy[0],
        "pnl_hoy_usd": hoy[1],
        "conciliacion": None if pasada is None else {
            "ts_ms": pasada[0], "cuadra": bool(pasada[1]),
            "descuadres": [f"{d['tipo']}: {d['detalle']}" for d in json.loads(pasada[2])]},
        "tratadas": tratadas,
    }


def _pct(x: float | None) -> float | None:
    return None if x is None else 100 * x


def papel_l(directorio: Path | None, principal: sqlite3.Connection | None) -> dict[str, Any]:
    """El papel de L (10/10), de los ficheros que deja `scripts/papel_l.py` cada noche. SOLO LEE; sin ficheros (antes
    de la primera pasada), "aun no ha empezado". El precio de ahora de cada posicion, el de la ingesta (estimacion)."""
    base = {**PAPEL_L, "disponible": False}
    if directorio is None:
        return base
    try:
        r = json.loads((Path(directorio) / "ultimo.json").read_text(encoding="utf-8"))
        meta = json.loads((Path(directorio) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return base
    met, btc = r["metricas"], r["btc"]
    precios = _precios(principal, set(r["abiertas"]))
    posiciones = []
    for s, p in sorted(r["abiertas"].items(), key=lambda x: int(x[1]["t"])):
        ahora = precios.get(s, (None, 0))[0]
        posiciones.append({"symbol": s, "entrada": float(p["entrada"]), "stop": float(p["stop"]),
                           "objetivo": float(p["objetivo"]), "coste_usd": float(p["coste"]), "abierta_ms": int(p["t"]),
                           "precio": ahora,
                           "pnl_usd": None if ahora is None else round(float(p["qty"]) * ahora - float(p["coste"]), 4)})
    ultimas = [{"symbol": o["simbolo"], "entrada_ms": int(o["entrada_ms"]), "salida_ms": int(o["salida_ms"]),
                "neto_usd": float(o["neto"]), "motivo": o["motivo"]}
               for o in sorted(r["ops"], key=lambda o: int(o["salida_ms"]), reverse=True)[:6]]
    return {**base, "disponible": True, "pasada_ms": int(meta["pasada_ms"]), "huecos": meta.get("huecos") or {},
            "equity_usd": met["final"], "rendimiento_pct": 100 * met["rendimiento"],
            "caida_max_pct": 100 * met["caida_max"], "btc_rendimiento_pct": 100 * btc["rendimiento"],
            "btc_caida_max_pct": 100 * btc["caida_max"],
            # Solo informacion (revision 6, 15/10): la caida con el cierre de cada vela de 4 h; None en pasadas viejas.
            "caida_velas_pct": _pct(met.get("caida_max_velas")), "btc_caida_velas_pct": _pct(btc.get("caida_max_velas")),
            "operaciones": len(r["ops"]), "posiciones": posiciones,
            "ultimas": ultimas}


# La abreviatura del setup en el decision_id (`strategy.candidates.make_decision_id`).
SETUP_DE_TAG = {"pb": "pullback_trend", "bo": "range_breakout", "mr": "mean_reversion"}


def _ultimo(conn: sqlite3.Connection | None, sql: str) -> int | None:
    if conn is None:
        return None
    try:
        fila = conn.execute(sql).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if fila is None or fila[0] is None else int(fila[0])


# 15/10/2026 (el propietario, inventario, decision 1 b): retirados. Sus bases siguen (y sus copias), sin moverse: "Retirado",
# no "Caido". `docs/cierre-fase-6.md`.
RETIRADOS = frozenset({"papel_baseline", "papel_ai", "ejecutor"})


def foto(*, settings: Settings, ahora_ms: int, principal: sqlite3.Connection | None,
         carteras: Mapping[str, sqlite3.Connection | None], noticias: sqlite3.Connection | None,
         mando: sqlite3.Connection | None, hoy: date | None = None,
         exec_conn: sqlite3.Connection | None = None, papel_l_dir: Path | None = None,
         medios: sqlite3.Connection | None = None) -> dict[str, Any]:
    """El estado entero. Cada conexion puede ser None (esa base no esta): esa parte sale sin datos."""
    ultimo_1m = _ultimo(principal, "SELECT MAX(ts_open_ms) FROM candles WHERE timeframe = '1m'")
    # Una vela de 1 m que abrio a las T se guarda al cerrar (T + 1 min).
    retraso_ingesta = None if ultimo_1m is None else ahora_ms - (ultimo_1m + MIN)
    ultima_lectura = _ultimo(noticias, "SELECT MAX(ms) FROM news_lecturas WHERE ok = 1")
    ultima_vuelta = _ultimo(mando, "SELECT MAX(ms) FROM control_lecturas WHERE ok = 1")

    fotos = {n: cartera(c, n, settings, ahora_ms, principal) for n, c in carteras.items()}
    demo = ejecutor(exec_conn, ahora_ms, principal)
    servicios = {
        "ingesta": {"ultimo_ms": ultimo_1m, "estado": _estado(retraso_ingesta, *UMBRALES["ingesta"])},
        # El "ultimo dato" de una cartera es el CIERRE de su ultima vela (con la apertura salia "hace 4 h" estando al dia).
        **{f"papel_{n}": {"ultimo_ms": None if f.get("ultima_vela_ms") is None else f["ultima_vela_ms"] + H4,
                          "estado": f.get("estado", "sin_datos")}
           for n, f in fotos.items()},
        "noticias": {"ultimo_ms": ultima_lectura, "estado": _estado(
            None if ultima_lectura is None else ahora_ms - ultima_lectura, *UMBRALES["noticias"])},
        "telegram": {"ultimo_ms": ultima_vuelta, "estado": _estado(
            None if ultima_vuelta is None else ahora_ms - ultima_vuelta, *UMBRALES["telegram"])},
    }
    # Los medios en sombra: SOLO si el servicio lee (la ultima lectura buena), nunca los titulares
    # (docs/diseno-medios-sombra.md 1; hay un test). Sin su base, el servicio no se ensenya.
    if medios is not None:
        ultima_medios = _ultimo(medios, "SELECT MAX(ms) FROM medios_lecturas WHERE ok = 1")
        servicios["medios"] = {"ultimo_ms": ultima_medios, "estado": _estado(
            None if ultima_medios is None else ahora_ms - ultima_medios, *UMBRALES["medios"])}
    l = papel_l(papel_l_dir, principal)
    if l["disponible"]:
        servicios["papel_l"] = {"ultimo_ms": l["pasada_ms"], "estado": _estado(ahora_ms - l["pasada_ms"],
                                                                              *UMBRALES["papel_l"])}
    if demo["disponible"]:
        servicios["ejecutor"] = {"ultimo_ms": demo["equity_ms"], "estado": _estado(
            None if demo["equity_ms"] is None else ahora_ms - demo["equity_ms"], *UMBRALES["ejecutor"])}

    for k in RETIRADOS & servicios.keys():
        servicios[k]["estado"] = "retirado"

    manual = {"disponible": mando is not None, "pausa_ms": None, "parada_ms": None}
    if mando is not None:
        e = reconstruir(control.comandos(mando))
        manual.update(pausa_ms=e.pausa_ms, parada_ms=e.kill_ms)

    news: dict[str, Any] = {"disponible": noticias is not None, "flags": {}}
    if noticias is not None:
        todas = flags(noticias_db.anuncios(noticias), bases_de(settings.whitelist),
                      levantadas=noticias_db.levantadas(noticias))
        news["flags"] = {par: list(ts) for par, ts in
                         event_flags(todas, ahora_ms, settings.whitelist).items()}

    caduca = settings.claude.token_expires_on
    hoy = hoy or datetime.fromtimestamp(ahora_ms / 1000, tz=UTC).date()
    return {
        "generado_ms": ahora_ms,
        "carteras": fotos,
        "demo": demo,
        "papel_l": l,
        "manual": manual,
        "noticias": news,
        "servicios": servicios,
        "limites": {
            "whitelist": list(settings.whitelist),
            "capital_inicial_usd": settings.capital.initial_capital_usd,
            "suelo_usd": settings.capital.floor_usd,
            "max_posiciones": settings.risk.max_positions,
            "max_operaciones_dia": settings.risk.max_trades_per_day,
            "perdida_diaria_max_usd": settings.risk.daily_loss_limit_usd,
            "riesgo_por_operacion_pct": settings.risk.risk_per_trade_pct,
            "max_llamadas_ia_dia": settings.claude.max_calls_per_day,
        },
        "token_ia": {"caduca": caduca.isoformat() if caduca else None,
                     "dias": (caduca - hoy).days if caduca else None},
        # Decision del propietario del 25/09: bloqueado en el 3 hasta cerrar la fase 6 y revisar la estrategia.
        "slider": {"nivel": 3, "bloqueado": True,
                   "motivo": "bloqueado hasta cerrar la fase 6 y revisar la estrategia",
                   "niveles": [{"nivel": n, "riesgo_pct": v["risk_pct"], "max_operaciones": v["max_trades"],
                                "setups": sorted(v["setups"])} for n, v in sorted(SLIDER_LEVELS.items())]},
    }
