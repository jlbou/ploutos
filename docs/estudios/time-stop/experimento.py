"""Time-stop: el recorrido historico del baseline con y sin cerrar posiciones que no avanzan.

Uso: experimento.py <N velas | none> [siempre|sin_avance]
No toca el codigo del bot: parchea el simulador EN MEMORIA dentro de este proceso, sobre un
worktree de fase-3-integracion (comisiones de settings.yaml) y una copia de la base con un anyo.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI / "repo"))

import portfolio.loop as loop_mod  # noqa: E402
import portfolio.paper as paper  # noqa: E402

TF = 4 * 3600_000
N = None if sys.argv[1] == "none" else int(sys.argv[1])
MODO = sys.argv[2] if len(sys.argv) > 2 else "siempre"
UMBRAL = 0.5                        # "sin avance": no ha hecho ni la mitad del camino al objetivo

cerradas, por_tiempo = [], set()
original = paper.PaperBroker._resolve_position


def resolver(self, pos, bar):
    t = original(self, pos, bar)
    if t is not None or N is None:
        return t
    if (bar.ts_open_ms - pos.opened_ts_ms) // TF < N:
        return None
    if MODO == "sin_avance":
        avance = (bar.close - pos.entry_price) / (pos.target_price - pos.entry_price)
        if avance >= UMBRAL:
            return None
    ins = self.instruments[pos.symbol]
    por_tiempo.add(pos.decision_id)
    return paper.PaperTrade(
        decision_id=pos.decision_id, symbol=pos.symbol, setup=pos.setup, qty=pos.qty,
        entry_price=pos.entry_price, exit_price=bar.close, stop_price=pos.stop_price,
        target_price=pos.target_price, opened_ts_ms=pos.opened_ts_ms, closed_ts_ms=bar.ts_open_ms,
        reason=paper.ExitReason.STOP, entry_fee_usd=pos.entry_fee_usd,
        exit_fee_usd=pos.qty * bar.close * ins.taker_fee, exit_was_maker=False,
        mae_pct=(min(pos.worst_price, bar.low) - pos.entry_price) / pos.entry_price * 100,
        mfe_pct=(max(pos.best_price, bar.high) - pos.entry_price) / pos.entry_price * 100,
    )


paper.PaperBroker._resolve_position = resolver

velas_con_candidatos = [0]
candidatos = [0]
step_original = loop_mod.TradingLoop.step


def step(self, *a, **k):
    r = step_original(self, *a, **k)
    n = len(r.pipeline.generation().candidates) if r.pipeline is not None else 0
    candidatos[0] += n
    velas_con_candidatos[0] += n > 0
    cerradas.extend(r.closed)
    return r


loop_mod.TradingLoop.step = step

import os
sys.argv = ["replay_baseline.py", "--db", str(AQUI / "historia.db")] + (["--since", os.environ["SINCE"]] if os.environ.get("SINCE") else [])
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("replay", AQUI / "repo" / "scripts" / "replay_baseline.py")
replay = importlib.util.module_from_spec(spec)
salida = io.StringIO()
with contextlib.redirect_stdout(salida):
    spec.loader.exec_module(replay)
    replay.main()
texto = salida.getvalue()


def linea(clave):
    for l in texto.splitlines():
        if l.strip().startswith(clave):
            return l.strip()
    return ""


CORTE = 1_775_001_600_000      # 01/04/2026: antes, tramo bajista; despues, alcista
def resumen(ts):
    rs = [t.r_multiple for t in ts]
    return {"n": len(rs), "exp_r": sum(rs) / len(rs) if rs else 0.0,
            "neto": sum(t.net_pnl_usd for t in ts), "aciertos": sum(r > 0 for r in rs)}

print(json.dumps({
    "variante": f"{N} {MODO}" if N else "sin time-stop",
    "velas_con_candidatos": velas_con_candidatos[0], "candidatos": candidatos[0],
    "por_tiempo": len(por_tiempo),
    "r_por_tiempo": [round(t.r_multiple, 2) for t in cerradas if t.decision_id in por_tiempo][:0],
    "todo": resumen(cerradas),
    "bajista": resumen([t for t in cerradas if t.closed_ts_ms < CORTE]),
    "alcista": resumen([t for t in cerradas if t.closed_ts_ms >= CORTE]),
    "exp_por_tiempo": resumen([t for t in cerradas if t.decision_id in por_tiempo])["exp_r"],
    "drawdown": linea("drawdown maximo"), "equity": linea("equity"), "baseline": linea("baseline "),
    "btc": linea("comprar y esperar BTC"), "cesta": linea("comprar y esperar las"),
}, ensure_ascii=False))

if os.environ.get("DUMP"):
    Path(os.environ["DUMP"]).write_text(json.dumps({
        "texto": texto,
        "operaciones": [{"id": t.decision_id, "par": t.symbol, "setup": t.setup,
                         "abre": t.opened_ts_ms, "cierra": t.closed_ts_ms, "r": t.r_multiple,
                         "neto": t.net_pnl_usd, "motivo": str(t.reason), "mfe": t.mfe_pct,
                         "mae": t.mae_pct, "por_tiempo": t.decision_id in por_tiempo}
                        for t in cerradas],
    }, ensure_ascii=False), encoding="utf-8")
