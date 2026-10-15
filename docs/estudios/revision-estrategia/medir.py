"""Mide una estrategia en el tramo de EXPLORACION (docs/archivo/propuesta-revision-estrategia.md, seccion 5).

Lanza el recorrido del bot (`scripts/replay_baseline.py`, SIN cambios: el mismo bucle, las 19 reglas,
las comisiones de settings.yaml) sobre la base de exploracion, recoge cada operacion cerrada y calcula
lo que pide el criterio fijado antes de medir:

- R medio por operacion con su intervalo del 90 % por BOOTSTRAP POR DIAS (se remuestrean dias
  enteros, no operaciones sueltas: las del mismo dia no son independientes);
- el mismo numero por anyo natural (que no gane solo en un tramo);
- por setup, y contra comprar y esperar.

    python medir.py <base> <nombre> [--since AAAA-MM-DD] [--idea N ...] > salida.json

Sin --idea mide la estrategia ACTUAL (la referencia). Cada idea de la lista cerrada (seccion 4 del
metodo) cambia UNA cosa, parcheada EN MEMORIA dentro de este proceso (el bot no se toca):

    --idea 1                       no comprar cayendo: la entrada solo se llena si la vela que toca el
                                   limite CIERRA por encima; se compra al cierre (taker) y esa vela ya
                                   no cuenta para el stop ni el objetivo (paso antes de entrar)
    --idea 2                       tendencia de BTC: sin candidatos si BTC cierra bajo su media de
                                   200 dias (cierres diarios UTC); antes de tener 200 dias, sin filtro
    --idea 3                       solo la ruptura (el nivel 3 del slider sin pullback ni reversion)
    --idea 4 --setup S --mult X    multiplo de ATR del stop del setup S (rango fijado: 1,5-2,5)
    --idea 5 --tf 1d               velas de 1 dia (base con velas de 1d, `agregar_1d.py`); multiplo
                                   de ATR 1,9, el mismo que en 4 h (no se ajusta: no estaba fijado)
"""
import contextlib
import importlib.util
import io
import json
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import portfolio.loop as loop_mod  # noqa: E402

base, nombre = sys.argv[1], sys.argv[2]


def opcion(nombre_opcion, defecto=None):
    return sys.argv[sys.argv.index(nombre_opcion) + 1] if nombre_opcion in sys.argv else defecto


since = opcion("--since", "2020-12-02")
sys_argv = sys.argv[3:]
idea = opcion("--idea")
# "2+3": varias ideas a la vez (combinaciones de dos, seccion 4 del metodo; el propietario, 26/09).
ideas = set(idea.split("+")) if idea else set()
tf = opcion("--tf", "4h")
ITER = 10_000
random.seed(20250925)

cerradas, candidatos = [], [0]
step_original = loop_mod.TradingLoop.step


def step(self, *a, **k):
    r = step_original(self, *a, **k)
    cerradas.extend(r.closed)
    if r.pipeline is not None:
        candidatos[0] += len(r.pipeline.generation().candidates)
    return r


loop_mod.TradingLoop.step = step

# --- las ideas (una cada vez) -----------------------------------------------------------------
if "1" in ideas:
    import portfolio.paper as paper_mod
    al_cierre: set[str] = set()

    def llenar(self, symbol, bar):
        for order in self.orders:
            if order.state is not paper_mod.OrderState.PENDING or order.symbol != symbol:
                continue
            if bar.ts_open_ms <= order.created_ts_ms or bar.low > order.limit_price:
                continue
            if bar.close < order.limit_price:
                continue                 # tocó el nivel pero cerró por debajo: sigue esperando
            ins = self.instruments[order.symbol]
            order.state = paper_mod.OrderState.FILLED
            self.positions[symbol] = paper_mod.PaperPosition(
                decision_id=order.decision_id, symbol=symbol, qty=order.qty, entry_price=bar.close,
                stop_price=order.stop_price, target_price=order.target_price, setup=order.setup,
                opened_ts_ms=bar.ts_open_ms, entry_fee_usd=order.qty * bar.close * ins.taker_fee)
            al_cierre.add(order.decision_id)
            break

    resolver_original = paper_mod.PaperBroker._resolve_position

    def resolver(self, position, bar):
        if position.decision_id in al_cierre and bar.ts_open_ms == position.opened_ts_ms:
            return None                  # se entro al CIERRE: lo de esta vela paso antes
        return resolver_original(self, position, bar)

    paper_mod.PaperBroker._fill_entries = llenar
    paper_mod.PaperBroker._resolve_position = resolver

if "2" in ideas:
    import sqlite3
    import strategy.pipeline as pipe_mod
    from strategy.candidates import Generation, Rejection
    con = sqlite3.connect(base)
    btc = {int(ts): c for ts, c in con.execute(
        "SELECT ts_open_ms, close FROM candles WHERE symbol='BTC/USDC' AND timeframe='4h' ORDER BY ts_open_ms")}
    con.close()
    diarios = {}                         # dia -> (ts de su ultima vela de 4 h, cierre)
    for ts, c in btc.items():
        d = ts // 86_400_000
        if d not in diarios or ts > diarios[d][0]:
            diarios[d] = (ts, c)
    completos = sorted(v for v in diarios.values() if v[0] % 86_400_000 == 20 * 3600_000)
    bajista: dict[int, bool] = {}
    for ts in btc:
        previos = [c for t, c in completos if t <= ts][-200:]
        if len(previos) == 200:
            bajista[ts] = btc[ts] < sum(previos) / 200
    generar_original = pipe_mod.generate_for_symbol

    def generar(symbol, *a, now, **k):
        t = int(now.timestamp() * 1000)
        if bajista.get(t, False):
            return Generation(rejections=(Rejection(symbol, "*", "btc", "BTC bajo su media de 200 dias"),))
        return generar_original(symbol, *a, now=now, **k)

    pipe_mod.generate_for_symbol = generar

if "3" in ideas:
    import risk.limits as lim_mod
    lim_mod.SLIDER_LEVELS[3] = {**lim_mod.SLIDER_LEVELS[3], "setups": frozenset({"range_breakout"})}

if "4" in ideas:
    import dataclasses
    import strategy.candidates as cand_mod
    objetivo, mult = opcion("--setup"), float(opcion("--mult"))
    assert 1.5 <= mult <= 2.5, "fuera del rango fijado antes de medir"
    todos = cand_mod.all_setups()
    assert objetivo in {n for n, _r, _f in todos}

    def con_mult(fn):
        return lambda ctx: fn(dataclasses.replace(ctx, atr_multiple=mult))

    cand_mod.all_setups = lambda: [(n, r, con_mult(f) if n == objetivo else f) for n, r, f in todos]

if "5" in ideas:
    assert tf == "1d", "la idea 5 va con --tf 1d"
if ideas - {"1", "2", "3", "4", "5"}:
    raise SystemExit(f"idea desconocida: {idea}")
spec = importlib.util.spec_from_file_location("replay", REPO / "scripts" / "replay_baseline.py")
replay = importlib.util.module_from_spec(spec)
sys.argv = ["replay_baseline.py", "--db", base, "--since", since, "--tf", tf]
texto = io.StringIO()
with contextlib.redirect_stdout(texto):
    spec.loader.exec_module(replay)
    if tf not in ("4h", "1h"):
        ajustes = replay.load_settings()
        ajustes.strategy.atr_multiple[tf] = 1.9      # idea 5: el mismo multiplo que en 4 h
        replay.load_settings = lambda: ajustes
    replay.main()
salida = texto.getvalue()


paso_ms = {"4h": 4 * 3600_000, "1d": 86_400_000, "1h": 3600_000}[tf]


def dia(ms):
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def bootstrap(trades):
    """IC del 90 % del R medio, remuestreando DIAS de cierre."""
    por_dia = defaultdict(list)
    for t in trades:
        por_dia[dia(t.closed_ts_ms)].append(t.r_multiple)
    dias = list(por_dia.values())
    if len(dias) < 2:
        return None, None
    medias = []
    for _ in range(ITER):
        muestra = [r for d in random.choices(dias, k=len(dias)) for r in d]
        medias.append(sum(muestra) / len(muestra))
    medias.sort()
    return medias[int(0.05 * ITER)], medias[int(0.95 * ITER)]


def resumen(trades):
    rs = [t.r_multiple for t in trades]
    if not rs:
        return {"n": 0}
    lo, hi = bootstrap(trades)
    return {"n": len(rs), "aciertos_pct": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "r_medio": round(sum(rs) / len(rs), 3), "ic90": [round(lo, 3), round(hi, 3)] if lo is not None else None,
            "neto_usd": round(sum(t.net_pnl_usd for t in trades), 2)}


def linea(clave):
    return next((l.strip() for l in salida.splitlines() if l.strip().startswith(clave)), "")


por_anyo = defaultdict(list)
por_setup = defaultdict(list)
for t in cerradas:
    por_anyo[str(dia(t.closed_ts_ms).year)].append(t)
    por_setup[t.setup].append(t)

print(json.dumps({
    "estrategia": nombre, "idea": idea, "argumentos": sys_argv, "desde": since, "datos": "USDT como sustituto de USDC, exploracion 12/2020-06/2024",
    "candidatos": candidatos[0], "todo": resumen(cerradas),
    "por_anyo": {a: resumen(ts) for a, ts in sorted(por_anyo.items())},
    "por_setup": {s: resumen(ts) for s, ts in sorted(por_setup.items())},
    "periodo": linea("Periodo:"), "equity": linea("equity"), "drawdown": linea("drawdown maximo"),
    "baseline": linea("baseline "), "btc": linea("comprar y esperar BTC"), "cesta": linea("comprar y esperar las"),
    # Cada operacion (dia de cierre, R), para la comparacion emparejada con la referencia.
    "operaciones": [[str(dia(t.closed_ts_ms)), round(t.r_multiple, 4)] for t in cerradas],
    "muertas_0_1_velas": sum(1 for t in cerradas if (t.closed_ts_ms - t.opened_ts_ms) <= paso_ms),
}, ensure_ascii=False, indent=1))
