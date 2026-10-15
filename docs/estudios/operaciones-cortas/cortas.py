"""Operaciones de horas: R4, H1 y H2 (README.md, seccion 2). El bot no se toca: todo se parchea EN MEMORIA.

    python cortas.py <base de exploracion> <nombre> --tf 4h|1h --mult X [--objetivo-maker] > salida.json

Lanza `revision-estrategia/medir.py` (el recorrido del bot sin cambios) con dos cambios:
- el objetivo se cobra TAKER (salvo con `--objetivo-maker`, que es la validacion: reproduce la primera ronda);
- el multiplo de ATR del stop del timeframe, el de `--mult`.
Y anyade lo descriptivo: duracion, operaciones por dia, comisiones sobre el bruto y posiciones topadas en 20 $.
"""
import contextlib
import dataclasses
import io
import json
import runpy
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import core.config as config_mod  # noqa: E402
import portfolio.paper as paper_mod  # noqa: E402

MEDIR = REPO / "docs" / "estudios" / "revision-estrategia" / "medir.py"


def opcion(nombre, defecto=None):
    return sys.argv[sys.argv.index(nombre) + 1] if nombre in sys.argv else defecto


base, nombre = sys.argv[1], sys.argv[2]
tf, mult = opcion("--tf", "4h"), float(opcion("--mult", "1.9"))
objetivo_maker = "--objetivo-maker" in sys.argv

if not objetivo_maker:
    resolver_original = paper_mod.PaperBroker._resolve_position

    def resolver(self, position, bar):
        t = resolver_original(self, position, bar)
        if t is not None and t.reason is paper_mod.ExitReason.TARGET:
            ins = self.instruments[position.symbol]
            t = dataclasses.replace(t, exit_fee_usd=t.qty * t.exit_price * ins.taker_fee, exit_was_maker=False)
        return t

    paper_mod.PaperBroker._resolve_position = resolver

cargar_original = config_mod.load_settings


def cargar(*a, **k):
    s = cargar_original(*a, **k)
    s.strategy.atr_multiple[tf] = mult
    return s


config_mod.load_settings = cargar          # replay_baseline lo importa por nombre al cargarse: llega este

sys.argv = [str(MEDIR), base, nombre, "--tf", tf]
texto = io.StringIO()
with contextlib.redirect_stdout(texto):
    g = runpy.run_path(str(MEDIR), run_name="__main__")
salida = json.loads(texto.getvalue())
cerradas = g["cerradas"]

horas = [(t.closed_ts_ms - t.opened_ts_ms) / 3_600_000 for t in cerradas]
bruto = sum(t.gross_pnl_usd for t in cerradas)
comisiones = sum(t.fees_usd for t in cerradas)
dias = (max(t.closed_ts_ms for t in cerradas) - min(t.opened_ts_ms for t in cerradas)) / 86_400_000 if cerradas else 0
q = statistics.quantiles(horas, n=4) if len(horas) >= 2 else [None, None, None]
salida["modelo"] = {"tf": tf, "mult_atr": mult, "objetivo": "maker" if objetivo_maker else "taker"}
salida["descriptivo"] = {
    "duracion_horas": {"p25": q[0], "mediana": q[1], "p75": q[2]},
    "cerradas_en_menos_de_24h_pct": round(100 * sum(h < 24 for h in horas) / len(horas), 1) if horas else None,
    "operaciones_por_dia": round(len(cerradas) / dias, 3) if dias else None,
    "bruto_usd": round(bruto, 2), "comisiones_usd": round(comisiones, 2),
    "comisiones_sobre_bruto_pct": round(100 * comisiones / bruto, 1) if bruto > 0 else None,
    "topadas_en_20_pct": round(100 * sum(t.qty * t.entry_price >= 19.99 for t in cerradas) / len(cerradas), 1)
    if cerradas else None,
    "riesgo_medio_usd": round(statistics.mean(t.planned_risk_usd for t in cerradas), 3) if cerradas else None,
}
print(json.dumps(salida, ensure_ascii=False, indent=1))
