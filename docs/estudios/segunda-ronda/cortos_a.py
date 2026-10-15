"""Idea A': cortos pensados para el mercado bajista (`docs/archivo/diseno-cortos-bajistas.md`, APROBADO por el propietario el 28/09 antes
de medir). El bot no se toca: todo se parchea EN MEMORIA y corre el recorrido del bot (`scripts/replay_baseline.py`).

    python cortos_a.py preparar <exploracion.db> <combinada.db>
    python cortos_a.py medir <combinada.db> <exploracion.db> idea2|espejo|idea2+A > operaciones.json
    python cortos_a.py juzgar <idea2.json> <idea2+A.json>

COMO (seccion 7 del disenyo, escrita antes de medir). Una base COMBINADA con las 8 monedas reales y, al lado, sus
gemelas con los precios invertidos (`BTCINV/USDC` = C/precio de BTC, con el C de `revision-estrategia/cortos.py`).
Un largo sobre la gemela invertida es EXACTAMENTE un corto sobre la real: el stop y el objetivo saltan en las mismas
velas, el stop sufre los huecos y el objetivo no (las suposiciones de `portfolio/paper.py` al reves, como pide el
disenyo). Las dos van en el MISMO recorrido, asi que largos y cortos comparten los 3 huecos de la regla 4 y el resto
de las 19 reglas; una moneda y su gemela cuentan como el mismo simbolo (1 por simbolo). Cada operacion de una gemela
se pasa a corto con la cuenta exacta de `cortos.py` (mismo riesgo, comisiones, financiacion pesimista).

La senyal del corto se calcula sobre los precios REALES (no sobre los invertidos: con medias diarias, la inversion
ya no es exacta, que era la objecion del disenyo al metodo del espejo) y se entrega a la gemela en su escala.

Modos: `idea2` = solo largos con BTC sobre su media de 200 dias (validacion: reproduce la idea 2 de la primera ronda);
`espejo` = solo los tres setups actuales sobre las gemelas con BTC bajista (validacion: reproduce los 220 cortos del
espejo, `cortos-operaciones.json`); `idea2+A` = lo que se mide: los largos de la idea 2 y el rebote fallido de A'.
"""

from __future__ import annotations

import contextlib
import dataclasses
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

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("cortos", REPO / "docs/estudios/revision-estrategia/cortos.py")
cortos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cortos)

SUFIJO = "INV"
SETUP_A = "rebote_fallido"
DESDE = cortos.DESDE
DIA_MS, VELA_MS = 86_400_000, 4 * 3600_000
# El disenyo, seccion 2 (aprobado el 28/09): nada de esto se toca despues de medir.
TOLERANCIA_ATR = 0.5        # el rebote llega a la EMA20 o a menos de 0,5 ATR
MARGEN_STOP_ATR = 0.5       # stop: maximo del rebote (3 velas) + 0,5 ATR
STOP_MINIMO_ATR = 1.5       # y como minimo 1,5 ATR desde la entrada
OBJETIVO_R = 2.0


def gemela(simbolo: str) -> str:
    base, quote = simbolo.split("/")
    return f"{base}{SUFIJO}/{quote}"


def real(simbolo: str) -> str:
    base, quote = simbolo.split("/")
    return f"{base[:-len(SUFIJO)]}/{quote}" if base.endswith(SUFIJO) else simbolo


def es_gemela(simbolo: str) -> bool:
    return simbolo.split("/")[0].endswith(SUFIJO)


# --- preparar: la base combinada ------------------------------------------------------------------------------

def preparar(origen: Path, destino: Path) -> None:
    if destino.exists():
        raise SystemExit(f"{destino} ya existe")
    shutil.copyfile(origen, destino)
    con = sqlite3.connect(destino)
    con.execute("CREATE TABLE espejo (symbol TEXT PRIMARY KEY, k REAL NOT NULL)")
    simbolos = [s for (s,) in con.execute("SELECT DISTINCT symbol FROM candles ORDER BY symbol")]
    columnas_velas = [r[1] for r in con.execute("PRAGMA table_info(candles)")]
    columnas_inst = [r[1] for r in con.execute("PRAGMA table_info(instruments)")]
    columnas_libro = [r[1] for r in con.execute("PRAGMA table_info(book_metrics)") if r[1] != "id"]
    for s in simbolos:
        g = gemela(s)
        cierres = [c for (c,) in con.execute("SELECT close FROM candles WHERE symbol=? AND timeframe='4h'", (s,))]
        k = statistics.median(cierres) ** 2                     # el MISMO C que `cortos.preparar`
        con.execute("INSERT INTO espejo VALUES (?, ?)", (g, k))
        otras = [c for c in columnas_velas if c not in ("symbol", "open", "high", "low", "close")]
        con.execute(
            f"INSERT INTO candles (symbol, open, high, low, close, {', '.join(otras)}) "
            f"SELECT ?, ? / open, ? / low, ? / high, ? / close, {', '.join(otras)} FROM candles WHERE symbol = ?",
            (g, k, k, k, k, s))
        resto = [c for c in columnas_inst if c != "symbol"]
        con.execute(f"INSERT INTO instruments (symbol, {', '.join(resto)}) "
                    f"SELECT ?, {', '.join(resto)} FROM instruments WHERE symbol = ?", (g, s))
        resto = [c for c in columnas_libro if c != "symbol"]
        con.execute(f"INSERT INTO book_metrics (symbol, {', '.join(resto)}) "
                    f"SELECT ?, {', '.join(resto)} FROM book_metrics WHERE symbol = ?", (g, s))
        print(f"{s} -> {g}: C = {k:.6g}")
    con.commit()
    con.close()


# --- la senyal de A', sobre los precios reales ---------------------------------------------------------------

def cierres_diarios(df: pd.DataFrame) -> list[tuple[int, float]]:
    """(ts de la ultima vela de 4 h del dia, cierre del dia), solo dias COMPLETOS (como `cortos.bajista_de_btc`)."""
    return [(int(t), float(c)) for t, c in zip(df["ts_open_ms"], df["close"], strict=True)
            if int(t) % DIA_MS == 20 * 3600_000]


def tendencia_bajista(df: pd.DataFrame) -> dict[int, bool]:
    """Vela de 4 h -> la moneda en tendencia bajista diaria: cierre diario bajo su media de 50 y la de 50 bajo la de
    200, con los dias ya cerrados en esa vela. Sin 200 dias, no hay dato."""
    dias = cierres_diarios(df)
    out, j = {}, 0
    for t in df["ts_open_ms"]:
        t = int(t)
        while j < len(dias) and dias[j][0] <= t:
            j += 1
        previos = [c for _ts, c in dias[:j]]
        if len(previos) >= 200:
            m50, m200 = sum(previos[-50:]) / 50, sum(previos[-200:]) / 200
            out[t] = previos[-1] < m50 and m50 < m200
    return out


def senyales_a(exploracion: Path) -> dict[tuple[str, int], tuple[float, float, float, str]]:
    """(simbolo real, ts de la vela) -> (entrada, stop, objetivo, por que), en precios REALES. Solo mira el pasado:
    en la vela i usa velas <= i y dias cerrados <= i."""
    from features.indicators import atr, ema
    con = sqlite3.connect(f"file:{exploracion}?mode=ro", uri=True)
    btc_bajista = cortos.bajista_de_btc(exploracion)
    out = {}
    for (s,) in con.execute("SELECT DISTINCT symbol FROM candles").fetchall():
        df = pd.read_sql_query("SELECT ts_open_ms, open, high, low, close FROM candles WHERE symbol=? AND "
                               "timeframe='4h' AND closed=1 ORDER BY ts_open_ms", con, params=(s,))
        e20 = ema(df["close"], 20)
        a14 = atr(df["high"], df["low"], df["close"])
        tendencia = tendencia_bajista(df)
        for i in range(2, len(df)):
            t = int(df["ts_open_ms"].iloc[i])
            if btc_bajista.get(t) is not True or tendencia.get(t) is not True:
                continue                                     # 2.1: bajista en los DOS niveles
            ema_r, atr_r = float(e20.iloc[i - 1]), float(a14.iloc[i - 1])
            ema_c, atr_c = float(e20.iloc[i]), float(a14.iloc[i])
            if any(v != v for v in (ema_r, atr_r, ema_c, atr_c)) or atr_c <= 0:
                continue
            rebote, conf = df.iloc[i - 1], df.iloc[i]
            if float(rebote["high"]) < ema_r - TOLERANCIA_ATR * atr_r:
                continue                                     # 2.2: el rebote no llego a la EMA20
            if not (float(conf["close"]) < ema_c and float(conf["close"]) < float(conf["open"])):
                continue                                     # 2.2: la vela siguiente no confirma el fallo
            entrada = float(conf["close"])
            stop = float(df["high"].iloc[i - 2:i + 1].max()) + MARGEN_STOP_ATR * atr_c
            stop = max(stop, entrada + STOP_MINIMO_ATR * atr_c)
            objetivo = entrada - OBJETIVO_R * (stop - entrada)
            if objetivo <= 0:
                continue
            out[(s, t)] = (entrada, stop, objetivo,
                           f"rebote a la EMA20 ({ema_r:.6g}) que falla: cierre {entrada:.6g} bajo la EMA20 y la apertura")
    con.close()
    return out


# --- medir ------------------------------------------------------------------------------------------------------

def medir(base: Path, exploracion: Path, modo: str) -> list[dict]:
    assert modo in ("idea2", "espejo", "idea2+A")
    import core.config as config_mod
    import portfolio.loop as loop_mod
    import risk.limits as lim_mod
    import strategy.candidates as cand_mod
    import strategy.pipeline as pipe_mod
    from features.regime import Regime
    from strategy.candidates import Generation, Rejection
    from strategy.setups import SetupSignal

    con = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    k = dict(con.execute("SELECT symbol, k FROM espejo"))
    con.close()

    # 16 simbolos: las 8 reales y sus gemelas. Solo en este proceso (el bot sigue con su regla 3 de 8).
    cargar_original = config_mod.load_settings

    def cargar(*a, **kw):
        s = cargar_original(*a, **kw)
        return s.model_copy(update={"whitelist": tuple(s.whitelist) + tuple(gemela(x) for x in s.whitelist)})

    config_mod.load_settings = cargar

    # Quien puede abrir que: largos solo en las reales, cortos solo en las gemelas, y el filtro de BTC.
    bajista = cortos.bajista_de_btc(exploracion)
    generar_original = pipe_mod.generate_for_symbol

    def no(symbol, motivo):
        return Generation(rejections=(Rejection(symbol, "*", "lado", motivo),))

    def generar(symbol, *a, now, **kw):
        estado = bajista.get(int(now.timestamp() * 1000))
        if es_gemela(symbol):
            if modo == "idea2":
                return no(symbol, "sin cortos en este modo")
            if modo == "espejo" and estado is not True:
                return no(symbol, "corto solo con BTC bajista")
        else:
            if modo == "espejo":
                return no(symbol, "sin largos en este modo")
            if estado is True:
                return no(symbol, "largo solo con BTC sobre su media de 200 dias (idea 2)")
        return generar_original(symbol, *a, now=now, **kw)

    pipe_mod.generate_for_symbol = generar

    if modo == "idea2+A":
        senyales = senyales_a(exploracion)
        originales = cand_mod.all_setups()

        def solo_reales(fn):
            return lambda ctx: None if es_gemela(ctx.symbol) else fn(ctx)

        def rebote_fallido(ctx):
            if not es_gemela(ctx.symbol):
                return None
            t = int(ctx.candles["ts_open_ms"].iloc[-1])
            s = senyales.get((real(ctx.symbol), t))
            if s is None:
                return None
            entrada, stop, objetivo, por_que = s
            c = k[ctx.symbol]
            e_inv = c / entrada
            assert abs(e_inv - ctx.close) <= 1e-9 * e_inv, "la gemela no es la inversa exacta de la real"
            return SetupSignal(setup=SETUP_A, entry=ctx.close, stop=c / stop, target=c / objetivo,
                               reasons=(por_que,), features={})

        todos = [(n, r, solo_reales(f)) for n, r, f in originales] + [(SETUP_A, frozenset(Regime), rebote_fallido)]
        cand_mod.all_setups = lambda: todos
        nivel = lim_mod.SLIDER_LEVELS[3]
        lim_mod.SLIDER_LEVELS[3] = {**nivel, "setups": nivel["setups"] | {SETUP_A}}

    # Regla 4, 1 por simbolo: una moneda y su gemela son el mismo simbolo.
    pipeline_original = loop_mod.run_pipeline

    def pipeline(market, state, *a, **kw):
        r = pipeline_original(market, state, *a, **kw)
        ocupadas = {real(p.symbol) for p in state.positions} | {real(p.symbol) for p in state.pending_entries}
        libres = tuple(c for c in r.candidates if real(c.symbol) not in ocupadas)
        return dataclasses.replace(r, candidates=libres) if len(libres) != len(r.candidates) else r

    loop_mod.run_pipeline = pipeline

    cerradas: list = []
    step_original = loop_mod.TradingLoop.step

    def step(self, *a, **kw):
        res = step_original(self, *a, **kw)
        cerradas.extend(res.closed)
        return res

    loop_mod.TradingLoop.step = step

    spec = importlib.util.spec_from_file_location("replay", REPO / "scripts" / "replay_baseline.py")
    replay = importlib.util.module_from_spec(spec)
    sys.argv = ["replay_baseline.py", "--db", str(base), "--since", DESDE, "--tf", "4h"]
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(replay)
        replay.main()

    taker = None
    ops = []
    for t in cerradas:
        if es_gemela(t.symbol):
            o = cortos.a_corto(k[t.symbol], t.entry_price, t.exit_price, t.stop_price, t.qty, t.entry_fee_usd,
                               t.exit_fee_usd, t.opened_ts_ms, t.closed_ts_ms)
            # Informativo: el objetivo cobrado taker (la comision de salida, a la tasa taker de la moneda).
            if str(t.reason) == "target":
                if taker is None:
                    taker = cargar().exchange.fees.taker_pct / 100
                ot = cortos.a_corto(k[t.symbol], t.entry_price, t.exit_price, t.stop_price, t.qty,
                                    t.entry_fee_usd, t.qty * t.exit_price * taker, t.opened_ts_ms, t.closed_ts_ms)
                o["r_con_financiacion_taker"] = ot["r_con_financiacion"]
            else:
                o["r_con_financiacion_taker"] = o["r_con_financiacion"]
            ops.append({"lado": "corto", "simbolo": real(t.symbol), "setup": t.setup, "abierta_ms": t.opened_ts_ms,
                        "cerrada_ms": t.closed_ts_ms, "motivo": str(t.reason), **o})
        else:
            ops.append({"lado": "largo", "simbolo": t.symbol, "setup": t.setup, "abierta_ms": t.opened_ts_ms,
                        "cerrada_ms": t.closed_ts_ms, "motivo": str(t.reason), "r": t.r_multiple,
                        "r_con_financiacion": t.r_multiple, "r_con_financiacion_taker": None,
                        "neto_usd": t.net_pnl_usd})
    return ops


# --- juzgar: el criterio del disenyo, seccion 5 y decision 3 del 28/09 ---------------------------------------------

def dia(ms: int) -> str:
    return str(datetime.fromtimestamp(ms / 1000, tz=UTC).date())


def emparejada(idea: list[dict], ref: list[dict], clave: str = "r_con_financiacion") -> tuple[float, float, float]:
    """R total de cada dia, idea menos referencia, sobre los dias en que alguna cierra algo; IC 90 % por bootstrap
    de esos dias. Lo mismo que `revision-estrategia/emparejada.py` (semilla incluida)."""
    rnd = random.Random(20250926)
    a, b = defaultdict(float), defaultdict(float)
    for o in idea:
        a[dia(o["cerrada_ms"])] += o[clave]
    for o in ref:
        b[dia(o["cerrada_ms"])] += o[clave]
    dias = sorted(set(a) | set(b))
    dif = [a.get(d, 0.0) - b.get(d, 0.0) for d in dias]
    tot = sorted(sum(rnd.choices(dif, k=len(dif))) for _ in range(10_000))
    return sum(dif), tot[500], tot[9500]


def juzgar(idea2: list[dict], combinada: list[dict]) -> int:
    cortos_ops = [o for o in combinada if o["lado"] == "corto"]
    largos_ops = [o for o in combinada if o["lado"] == "largo"]
    sol = cortos.resumen_de(cortos_ops, "r_con_financiacion")
    por_anyo = defaultdict(list)
    for o in cortos_ops:
        por_anyo[dia(o["cerrada_ms"])[:4]].append(o)
    a2022 = cortos.resumen_de(por_anyo.get("2022", []), "r_con_financiacion")
    total, lo, hi = emparejada(combinada, idea2)
    criterio = {
        "cortos: al menos 100 operaciones": sol.get("n", 0) >= 100,
        "cortos: IC 90 % entero por encima de 0": bool(sol.get("ic90") and sol["ic90"][0] > 0),
        "cortos: R medio >= +0,13": sol.get("r_medio", -9) >= 0.13,
        "cortos: 2022 positivo": a2022.get("n", 0) > 0 and a2022["r_medio"] > 0,
        "combinacion mejor que la idea 2 sola (IC de la diferencia entero > 0)": lo > 0,
    }
    print(f"cortos A' (con financiacion pesimista): {json.dumps(sol, ensure_ascii=False)}")
    print("  por anyo: " + ", ".join(f"{a} {len(o)} op. {cortos.resumen_de(o, 'r_con_financiacion')['r_medio']:+.3f}"
                                     for a, o in sorted(por_anyo.items())))
    print(f"  informativo, objetivo taker: {json.dumps(cortos.resumen_de(cortos_ops, 'r_con_financiacion_taker'))}")
    print(f"largos en la combinacion: {json.dumps(cortos.resumen_de(largos_ops, 'r'))}")
    print(f"idea 2 sola: {json.dumps(cortos.resumen_de(idea2, 'r'))}")
    print(f"combinacion entera: {json.dumps(cortos.resumen_de(combinada, 'r_con_financiacion'))}")
    print(f"emparejada (R total de la combinacion menos la idea 2 sola): {total:+.1f} R (IC 90 %: {lo:+.1f} a {hi:+.1f})")
    for nombre, ok in criterio.items():
        print(f"  {'si' if ok else 'NO'}  {nombre}")
    pasa = all(criterio.values())
    print(f"VEREDICTO A': {'PASA la exploracion (la reserva, una vez, al final de la segunda ronda)' if pasa else 'NO PASA'}")
    return 0


def main() -> int:
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    if orden == "preparar":
        preparar(Path(sys.argv[2]), Path(sys.argv[3]))
    elif orden == "medir":
        print(json.dumps(medir(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])))
    elif orden == "juzgar":
        return juzgar(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[2:4]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
