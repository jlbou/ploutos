"""Ideas C (time-stop) y D (sin reversion) de la segunda ronda, en la exploracion. El bot no se toca: todo se
parchea EN MEMORIA sobre `revision-estrategia/medir.py` (el recorrido del bot sin cambios).

    python medir_cd.py <base de exploracion> <nombre> --objetivo maker|taker [--idea C|D|2|2+D] [--modo siempre|sin_avance]
                       [--asegurar]   # idea I: el stop a +1 R tras un cierre a +2 R (el propietario, 09/10)
                       [--since AAAA-MM-DD]   # donde empiezan las decisiones (las velas de antes, calentamiento)

Criterio fijado ANTES de medir: `docs/archivo/plan-segunda-ronda-estrategia.md`, "C y D: APROBADAS por el propietario el 07/10".
- `--objetivo taker`: el objetivo se cobra taker, como en OKX (el de `operaciones-cortas/cortas.py`).
- `--idea C`: time-stop de 18 velas, el de `time-stop/experimento.py` del 25/09 tal cual: tras 18 velas abierta se
  vende al cierre de la vela, taker; `sin_avance`, solo si no ha hecho la mitad del camino al objetivo.
- `--idea D`: el nivel 3 del slider sin `mean_reversion` (como la idea 3 de la primera ronda quita dos).
- `--idea 2`: la idea 2 de la primera ronda tal cual (la de `medir.py`: BTC bajo su media de 200 dias, sin
  candidatos); con `2+D`, las dos a la vez (aprobada por el propietario el 08/10, antes de medir).
Sin `--idea`: la referencia, que tiene que salir EXACTA a la de la primera ronda (validacion).
"""
import contextlib
import dataclasses
import io
import json
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import portfolio.paper as paper_mod  # noqa: E402
import risk.limits as lim_mod  # noqa: E402

MEDIR = REPO / "docs" / "estudios" / "revision-estrategia" / "medir.py"
TF_MS = 4 * 3600_000
VELAS_TIME_STOP = 18
UMBRAL_AVANCE = 0.5


def opcion(nombre, defecto=None):
    return sys.argv[sys.argv.index(nombre) + 1] if nombre in sys.argv else defecto


base, nombre = sys.argv[1], sys.argv[2]
objetivo = opcion("--objetivo")
idea = opcion("--idea")
modo = opcion("--modo", "siempre")
assert objetivo in ("maker", "taker"), "--objetivo maker|taker"
assert idea in (None, "C", "D", "2", "2+D"), "--idea C|D|2|2+D"
assert modo in ("siempre", "sin_avance")

if objetivo == "taker":
    resolver_maker = paper_mod.PaperBroker._resolve_position

    def resolver_taker(self, position, bar):
        t = resolver_maker(self, position, bar)
        if t is not None and t.reason is paper_mod.ExitReason.TARGET:
            ins = self.instruments[position.symbol]
            t = dataclasses.replace(t, exit_fee_usd=t.qty * t.exit_price * ins.taker_fee, exit_was_maker=False)
        return t

    paper_mod.PaperBroker._resolve_position = resolver_taker

# Idea I (aprobada por el propietario el 09/10): cuando una vela de 4 h CIERRA a +2 R o mas, desde la vela siguiente el stop pasa
# a +1 R. El R se sigue contando contra el stop original (el riesgo planificado).
asegurar = "--asegurar" in sys.argv
movidas: set[str] = set()
if asegurar:
    resolver_sin_asegurar = paper_mod.PaperBroker._resolve_position

    def resolver_asegurado(self, pos, bar):
        riesgo = pos.entry_price - pos.stop_price
        if pos.decision_id in movidas:
            copia = dataclasses.replace(pos, stop_price=pos.entry_price + riesgo)
            t = resolver_sin_asegurar(self, copia, bar)
            pos.worst_price, pos.best_price = copia.worst_price, copia.best_price
            return None if t is None else dataclasses.replace(t, stop_price=pos.stop_price)
        t = resolver_sin_asegurar(self, pos, bar)
        if t is None and riesgo > 0 and bar.close >= pos.entry_price + 2 * riesgo:
            movidas.add(pos.decision_id)
        return t

    paper_mod.PaperBroker._resolve_position = resolver_asegurado

por_tiempo: set[str] = set()
if idea == "C":
    resolver_sin_tiempo = paper_mod.PaperBroker._resolve_position

    def resolver_con_tiempo(self, pos, bar):
        t = resolver_sin_tiempo(self, pos, bar)
        if t is not None or (bar.ts_open_ms - pos.opened_ts_ms) // TF_MS < VELAS_TIME_STOP:
            return t
        if modo == "sin_avance" and (bar.close - pos.entry_price) / (pos.target_price - pos.entry_price) >= UMBRAL_AVANCE:
            return None
        ins = self.instruments[pos.symbol]
        por_tiempo.add(pos.decision_id)
        return paper_mod.PaperTrade(
            decision_id=pos.decision_id, symbol=pos.symbol, setup=pos.setup, qty=pos.qty,
            entry_price=pos.entry_price, exit_price=bar.close, stop_price=pos.stop_price,
            target_price=pos.target_price, opened_ts_ms=pos.opened_ts_ms, closed_ts_ms=bar.ts_open_ms,
            reason=paper_mod.ExitReason.STOP, entry_fee_usd=pos.entry_fee_usd,
            exit_fee_usd=pos.qty * bar.close * ins.taker_fee, exit_was_maker=False,
            mae_pct=(min(pos.worst_price, bar.low) - pos.entry_price) / pos.entry_price * 100,
            mfe_pct=(max(pos.best_price, bar.high) - pos.entry_price) / pos.entry_price * 100,
        )

    paper_mod.PaperBroker._resolve_position = resolver_con_tiempo

if idea in ("D", "2+D"):
    nivel = lim_mod.SLIDER_LEVELS[3]
    lim_mod.SLIDER_LEVELS[3] = {**nivel, "setups": nivel["setups"] - {lim_mod.SETUP_MEAN_REVERSION}}

desde = opcion("--since")                   # el anyo USDC de la segunda tanda de tendencia (10/10)
sys.argv = [str(MEDIR), base, nombre] + (["--idea", "2"] if idea in ("2", "2+D") else [])
if desde:
    sys.argv += ["--since", desde]
texto = io.StringIO()
with contextlib.redirect_stdout(texto):
    g = runpy.run_path(str(MEDIR), run_name="__main__")
salida = json.loads(texto.getvalue())
cerradas = g["cerradas"]
salida["modelo"] = {"objetivo": objetivo, "idea": idea, "modo": modo if idea == "C" else None, "asegurar": asegurar}
if asegurar:
    con = [t for t in cerradas if t.decision_id in movidas]
    salida["asegurar"] = {
        "stop_movido": len(con),
        "acabaron_en_objetivo": sum(1 for t in con if t.reason is paper_mod.ExitReason.TARGET),
        "acabaron_en_el_stop_movido": sum(1 for t in con if t.reason is paper_mod.ExitReason.STOP),
        "r_medio_de_las_movidas": round(sum(t.r_multiple for t in con) / len(con), 3) if con else None,
    }
if idea == "C":
    cortadas = [t for t in cerradas if t.decision_id in por_tiempo]
    salida["time_stop"] = {"cortadas": len(cortadas),
                           "r_medio_cortadas": round(sum(t.r_multiple for t in cortadas) / len(cortadas), 3)
                           if cortadas else None}
print(json.dumps(salida, ensure_ascii=False, indent=1))
