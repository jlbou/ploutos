"""Segunda ronda: largos con BTC alcista y CORTOS con BTC bajista (docs/archivo/plan-segunda-ronda-estrategia.md, 5b).

Fijado por el propietario el 28/09 ANTES de medir: los cortos son el ESPEJO de los tres setups actuales, solo con BTC bajo
su media de 200 dias (los largos, solo por encima); el criterio es el de la seccion 5 del plan.

COMO, SIN TOCAR EL BOT. Los precios se INVIERTEN (cada vela pasa a C/precio, con C = mediana^2 de cada moneda
para que las magnitudes, los ticks y los minimos sigan siendo razonables; el maximo pasa a ser el minimo) y se
pasa el recorrido del bot (`scripts/replay_baseline.py`) sin cambios, con sus 19 reglas. Un largo sobre los
precios invertidos es un corto sobre los reales: el stop y el objetivo saltan en las MISMAS velas. Despues,
cada operacion se pasa a corto con la cuenta exacta: mismo riesgo planificado, cantidad del corto
q = riesgo / (p_stop - p_entrada), mismas tasas de comision (la de entrada y la de salida de esa operacion), y la
financiacion pesimista (el corto PAGA 0,01 % del nocional en cada cobro de las 00, 08 y 16 UTC).

    python cortos.py preparar <exploracion.db> <invertida.db>
    python cortos.py medir <base> largo|corto <exploracion.db> [--sin-filtro] > lado.json
    python cortos.py resumen <largos.json> <cortos.json> [--referencia 0.13] > resultado.json

`medir <exploracion.db> largo ... --sin-filtro` es la VALIDACION: tiene que dar la referencia de la primera
ronda (+0,13 R con 497 operaciones), salvo lo que cambie el spread de la copia del bot.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import random
import shutil
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

DESDE = "2020-12-02"
ITER = 10_000
SEMILLA = 20250925
FINANCIACION = 0.0001                 # 0,01 % cada 8 h, pagado SIEMPRE por el corto (pesimista)
COBRO_MS = 8 * 3600_000


# --- preparar: la base con los precios invertidos ------------------------------------------------------------

def preparar(origen: Path, destino: Path) -> None:
    if destino.exists():
        raise SystemExit(f"{destino} ya existe")
    shutil.copyfile(origen, destino)
    con = sqlite3.connect(destino)
    con.execute("CREATE TABLE espejo (symbol TEXT PRIMARY KEY, k REAL NOT NULL)")
    for (simbolo,) in con.execute("SELECT DISTINCT symbol FROM candles").fetchall():
        cierres = [c for (c,) in con.execute(
            "SELECT close FROM candles WHERE symbol = ? AND timeframe = '4h'", (simbolo,))]
        k = statistics.median(cierres) ** 2
        # Todas las velas de la moneda (4 h y 1 h), con el MISMO C: las correlaciones siguen siendo coherentes.
        con.execute("UPDATE candles SET open = ? / open, high = ? / low, low = ? / high, close = ? / close"
                    " WHERE symbol = ?", (k, k, k, k, simbolo))
        con.execute("INSERT INTO espejo VALUES (?, ?)", (simbolo, k))
        print(f"{simbolo}: C = {k:.6g}")
    con.commit()
    con.close()


# --- medir: el recorrido del bot para un lado, con el filtro de BTC --------------------------------------------

def bajista_de_btc(exploracion: Path) -> dict[int, bool]:
    """Vela de 4 h -> BTC cierra bajo su media de 200 dias (igual que la idea 2 de la primera ronda).
    Sin 200 dias de historia, no hay dato (None en el dict: ni largo filtrado ni corto permitido)."""
    con = sqlite3.connect(f"file:{exploracion}?mode=ro", uri=True)
    btc = {int(ts): c for ts, c in con.execute(
        "SELECT ts_open_ms, close FROM candles WHERE symbol='BTC/USDC' AND timeframe='4h' ORDER BY ts_open_ms")}
    con.close()
    diarios = {}
    for ts, c in btc.items():
        d = ts // 86_400_000
        if d not in diarios or ts > diarios[d][0]:
            diarios[d] = (ts, c)
    completos = sorted(v for v in diarios.values() if v[0] % 86_400_000 == 20 * 3600_000)
    out: dict[int, bool] = {}
    for ts in btc:
        previos = [c for t, c in completos if t <= ts][-200:]
        if len(previos) == 200:
            out[ts] = btc[ts] < sum(previos) / 200
    return out


def medir(base: Path, lado: str, exploracion: Path, sin_filtro: bool) -> list[dict]:
    import portfolio.loop as loop_mod
    import strategy.pipeline as pipe_mod
    from strategy.candidates import Generation, Rejection

    cerradas: list = []
    step_original = loop_mod.TradingLoop.step

    def step(self, *a, **k):
        r = step_original(self, *a, **k)
        cerradas.extend(r.closed)
        return r

    loop_mod.TradingLoop.step = step
    if not sin_filtro:
        bajista = bajista_de_btc(exploracion)
        generar_original = pipe_mod.generate_for_symbol

        def generar(symbol, *a, now, **k):
            t = int(now.timestamp() * 1000)
            estado = bajista.get(t)
            # Largos: fuera si BTC esta bajista (sin dato: se deja, como la idea 2). Cortos: SOLO con BTC bajista.
            fuera = (estado is True) if lado == "largo" else (estado is not True)
            if fuera:
                return Generation(rejections=(Rejection(symbol, "*", "btc", f"regimen de BTC: {lado} no toca"),))
            return generar_original(symbol, *a, now=now, **k)

        pipe_mod.generate_for_symbol = generar

    spec = importlib.util.spec_from_file_location("replay", REPO / "scripts" / "replay_baseline.py")
    replay = importlib.util.module_from_spec(spec)
    sys.argv = ["replay_baseline.py", "--db", str(base), "--since", DESDE, "--tf", "4h"]
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(replay)
        replay.main()

    k = {}
    if lado == "corto":
        con = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
        k = dict(con.execute("SELECT symbol, k FROM espejo"))
        con.close()
    return [a_dict(t, lado, k.get(t.symbol)) for t in cerradas]


def a_dict(t, lado: str, k: float | None) -> dict:
    """Una operacion cerrada, como largo tal cual o pasada a CORTO sobre los precios reales."""
    base = {"simbolo": t.symbol, "setup": t.setup, "abierta_ms": t.opened_ts_ms, "cerrada_ms": t.closed_ts_ms,
            "motivo": str(t.reason)}
    if lado == "largo":
        return {**base, "r": t.r_multiple, "r_con_financiacion": t.r_multiple, "neto_usd": t.net_pnl_usd}
    return {**base, **a_corto(k, t.entry_price, t.exit_price, t.stop_price, t.qty, t.entry_fee_usd,
                              t.exit_fee_usd, t.opened_ts_ms, t.closed_ts_ms)}


def cobros_entre(abierta_ms: int, cerrada_ms: int) -> int:
    """Cuantos cobros de financiacion (00, 08 y 16 UTC) caen en (abierta, cerrada]."""
    return max(0, cerrada_ms // COBRO_MS - abierta_ms // COBRO_MS)


def a_corto(k: float, e_inv: float, x_inv: float, s_inv: float, q_inv: float, fee_ent: float, fee_sal: float,
            abierta_ms: int, cerrada_ms: int) -> dict:
    """El largo sobre precios invertidos (C/p) pasado a corto sobre los reales, con el mismo riesgo planificado."""
    riesgo = (e_inv - s_inv) * q_inv
    p_e, p_x, p_s = k / e_inv, k / x_inv, k / s_inv
    q = riesgo / (p_s - p_e)
    tasa_ent, tasa_sal = fee_ent / (q_inv * e_inv), fee_sal / (q_inv * x_inv)
    neto = q * (p_e - p_x) - q * p_e * tasa_ent - q * p_x * tasa_sal
    financiacion = q * p_e * FINANCIACION * cobros_entre(abierta_ms, cerrada_ms)
    return {"r": neto / riesgo, "r_con_financiacion": (neto - financiacion) / riesgo, "neto_usd": neto,
            "entrada": p_e, "salida": p_x, "stop": p_s}


# --- resumen: el criterio fijado antes de medir ---------------------------------------------------------------

def dia(ms: int):
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def bootstrap(ops: list[dict], clave: str) -> tuple[float, float] | tuple[None, None]:
    """IC del 90 % del R medio remuestreando DIAS de cierre (como medir.py de la primera ronda)."""
    random.seed(SEMILLA)
    por_dia = defaultdict(list)
    for o in ops:
        por_dia[dia(o["cerrada_ms"])].append(o[clave])
    dias = list(por_dia.values())
    if len(dias) < 2:
        return None, None
    medias = []
    for _ in range(ITER):
        muestra = [r for d in random.choices(dias, k=len(dias)) for r in d]
        medias.append(sum(muestra) / len(muestra))
    medias.sort()
    return medias[int(0.05 * ITER)], medias[int(0.95 * ITER)]


def resumen_de(ops: list[dict], clave: str = "r") -> dict:
    if not ops:
        return {"n": 0}
    rs = [o[clave] for o in ops]
    lo, hi = bootstrap(ops, clave)
    return {"n": len(rs), "aciertos_pct": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "r_medio": round(sum(rs) / len(rs), 3), "ic90": None if lo is None else [round(lo, 3), round(hi, 3)],
            "neto_usd": round(sum(o["neto_usd"] for o in ops), 2)}


def resumen(largos: list[dict], cortos: list[dict], referencia: float) -> dict:
    todas = sorted(largos + cortos, key=lambda o: o["cerrada_ms"])
    por_anyo = defaultdict(list)
    for o in todas:
        por_anyo[str(dia(o["cerrada_ms"]).year)].append(o)
    sin, con = resumen_de(todas, "r"), resumen_de(todas, "r_con_financiacion")
    anyo_2022 = resumen_de(por_anyo.get("2022", []), "r_con_financiacion")
    criterio = {
        "ic90_entero_sobre_la_referencia": bool(sin.get("ic90") and sin["ic90"][0] > referencia),
        "al_menos_100_operaciones": sin.get("n", 0) >= 100,
        "no_pierde_en_2022": anyo_2022.get("n", 0) > 0 and anyo_2022["r_medio"] > 0,
        # Con el corto pagando siempre la financiacion, el IC sigue entero sobre la referencia.
        "aguanta_la_financiacion_pesimista": bool(con.get("ic90") and con["ic90"][0] > referencia),
    }
    return {
        "referencia_r": referencia,
        "combinacion": sin, "combinacion_con_financiacion": con,
        "largos": resumen_de(largos), "cortos": resumen_de(cortos),
        "cortos_con_financiacion": resumen_de(cortos, "r_con_financiacion"),
        "por_anyo_con_financiacion": {a: resumen_de(o, "r_con_financiacion") for a, o in sorted(por_anyo.items())},
        "cortos_por_setup": {s: resumen_de([o for o in cortos if o["setup"] == s], "r_con_financiacion")
                             for s in sorted({o["setup"] for o in cortos})},
        "criterio": criterio, "pasa_la_exploracion": all(criterio.values()),
    }


def main() -> int:
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    if orden == "preparar":
        preparar(Path(sys.argv[2]), Path(sys.argv[3]))
    elif orden == "medir":
        base, lado, exploracion = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
        assert lado in ("largo", "corto")
        print(json.dumps(medir(base, lado, exploracion, "--sin-filtro" in sys.argv)))
    elif orden == "resumen":
        ref = float(sys.argv[sys.argv.index("--referencia") + 1]) if "--referencia" in sys.argv else 0.13
        largos = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        cortos = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        print(json.dumps(resumen(largos, cortos, ref), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
