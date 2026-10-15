"""Cuantos candidatos se pierden cuando las dos carteras tienen un equity distinto (29/09/2026).

El techo de ATR de la criba depende del riesgo por operacion (`atr_ceiling_pct`: 100 x riesgo / minimo por orden
/ multiplo), y el riesgo es un % del equity. Las carteras del baseline y de la IA no tienen el mismo equity, asi
que en el borde una ve un candidato y la otra no (NEAR, 29/09 08:00: ATR 5,333 % contra un techo de 5,323 % en la
IA). Y la regla 9 (por debajo de 45 $, riesgo a la mitad) puede abrir esa diferencia de golpe.

Como: el recorrido del bot (`scripts/replay_baseline.py`) SIN cambios. En cada vela se vuelve a pasar la criba
con el riesgo por operacion multiplicado por un factor y se cuentan los candidatos que se pierden (o ganan) frente
a la pasada de referencia. La segunda pasada es pura: el recorrido sale IDENTICO, y se comprueba.

    python divergencia.py <base> --since AAAA-MM-DD > salida.json
"""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

# Factor sobre el riesgo por operacion. 0,9966 y 1,0034 son los +-0,17 % que separan hoy a las dos carteras
# (49,85 $ contra 49,68 $); 0,9 es el escalon de un 10 % menos de equity; 0,5 es la regla 9 (< 45 $).
FACTORES = [0.9966, 0.99, 0.95, 0.90, 0.50, 1.0034, 1.01, 1.05, 1.10]


def medir(base: Path, desde: str) -> dict:
    import portfolio.loop as loop_mod

    pipeline_real = loop_mod.run_pipeline
    step_real = loop_mod.TradingLoop.step
    velas: list[dict] = []
    cerradas: list = []

    def pipeline(market, state, limits, settings, cost, instruments, **k):
        r = pipeline_real(market, state, limits, settings, cost, instruments, **k)
        ref = {(c.symbol, c.setup) for c in r.candidates}
        por_factor = {}
        for f in FACTORES:
            alt = replace(limits, risk_per_trade_pct=limits.risk_per_trade_pct * f)
            rf = pipeline_real(market, state, alt, settings, cost, instruments, **k)
            otros = {(c.symbol, c.setup) for c in rf.candidates}
            por_factor[f] = {"pierde": len(ref - otros), "gana": len(otros - ref)}
        velas.append({"ts": int(k["now"].timestamp() * 1000), "ref": len(ref), "f": por_factor})
        return r

    def step(self, *a, **k):
        res = step_real(self, *a, **k)
        cerradas.extend(res.closed)
        return res

    loop_mod.run_pipeline = pipeline
    loop_mod.TradingLoop.step = step
    spec = importlib.util.spec_from_file_location("replay", REPO / "scripts" / "replay_baseline.py")
    replay = importlib.util.module_from_spec(spec)
    sys.argv = ["replay_baseline.py", "--db", str(base), "--since", desde, "--tf", "4h"]
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(replay)
        replay.main()
    return resumir(velas, cerradas, desde)


def resumir(velas: list[dict], cerradas: list, desde: str) -> dict:
    inicio = int(datetime.fromisoformat(desde).replace(tzinfo=UTC).timestamp() * 1000)
    velas = [v for v in velas if v["ts"] >= inicio]
    total = sum(v["ref"] for v in velas)
    salida = {}
    for f in FACTORES:
        pierde = sum(v["f"][f]["pierde"] for v in velas)
        gana = sum(v["f"][f]["gana"] for v in velas)
        salida[str(f)] = {"pierde": pierde, "gana": gana,
                          "pierde_pct": round(100 * pierde / total, 1) if total else 0.0,
                          "gana_pct": round(100 * gana / total, 1) if total else 0.0}
    return {"desde": desde, "velas": len(velas), "dias": round(len(velas) / 6, 1),
            "operaciones_cerradas": len(cerradas), "candidatos_referencia": total, "por_factor": salida}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("base", type=Path)
    p.add_argument("--since", required=True)
    a = p.parse_args()
    print(json.dumps(medir(a.base, a.since), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
