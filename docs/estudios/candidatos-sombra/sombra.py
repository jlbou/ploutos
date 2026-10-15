"""Cuantos candidatos EN SOMBRA saldrian con la cartera llena (decision 5 del protocolo de la fase 6).

Hoy, con los huecos de la regla 4 ocupados, el filtro "hueco libre" corta y no sale ningun candidato: la IA
no ve nada y la muestra de la M1 crece despacio (25-28/09: 17 de 19 velas con la cartera llena). La
decision 5 se toma el 02/10 con el recuento real; esto da el numero con la historia.

Como: el recorrido del bot (`scripts/replay_baseline.py`) SIN cambios. En cada vela, si alguna moneda cae
SOLO por tener los huecos ocupados, se vuelve a pasar la criba con el tope de posiciones abierto (99) y se
apuntan los candidatos que salen de mas: esos serian los de sombra ("si hubiera hueco, que abririas?").
La segunda pasada es pura (no toca el estado ni la cartera): el recorrido sale IDENTICO, y se comprueba.

Lo que NO cambia: las demas reglas de la criba (1 por simbolo, cooldown, correlacion, spread, ATR...).
Una moneda con posicion abierta tampoco daria sombra: eso es otra pregunta.

    python sombra.py <base> --since AAAA-MM-DD > salida.json
"""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

LLENA = "huecos ocupados"
TOPE_ABIERTO = 99


def solo_por_llena(screening) -> bool:
    """La moneda cae UNICAMENTE porque no quedan huecos (no por otra regla a la vez)."""
    rechazos = screening.rejections
    return bool(rechazos) and all(r.name == "hueco libre" and LLENA in r.detail for r in rechazos)


def medir(base: Path, desde: str) -> dict:
    import portfolio.loop as loop_mod

    pipeline_real = loop_mod.run_pipeline
    step_real = loop_mod.TradingLoop.step
    velas: list[dict] = []
    cerradas: list = []

    def pipeline(market, state, limits, settings, cost, instruments, **k):
        r = pipeline_real(market, state, limits, settings, cost, instruments, **k)
        llenas = {s.symbol for s in r.screenings if solo_por_llena(s)}
        sombra = []
        if llenas:
            abierto = pipeline_real(
                market, state, replace(limits, max_positions=TOPE_ABIERTO), settings, cost, instruments, **k
            )
            sombra = [c for c in abierto.candidates if c.symbol in llenas]
        velas.append({
            "ts": int(k["now"].timestamp() * 1000),
            "llena": bool(llenas) or state.occupied_slots >= limits.max_positions,
            "reales": len(r.candidates),
            "reales_de": [{"symbol": c.symbol, "setup": c.setup} for c in r.candidates],
            "sombra": [{"symbol": c.symbol, "setup": c.setup} for c in sombra],
        })
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


def episodios(velas: list[dict], clave: str) -> int:
    """Candidatos DISTINTOS: el mismo simbolo y setup en velas seguidas cuenta una vez.

    Un pullback que sigue valido tres velas sale tres veces; para la M1 son tres decisiones, pero muy
    parecidas entre si (no independientes). Este numero es el suelo honesto de la muestra.
    """
    n, antes = 0, set()
    for v in velas:
        ahora = {(c["symbol"], c["setup"]) for c in v[clave]}
        n += len(ahora - antes)
        antes = ahora
    return n


def resumir(velas: list[dict], cerradas: list, desde: str) -> dict:
    inicio = int(datetime.fromisoformat(desde).replace(tzinfo=UTC).timestamp() * 1000)
    velas = [v for v in velas if v["ts"] >= inicio]
    dias = len(velas) / 6 if velas else 0
    reales = sum(v["reales"] for v in velas)
    sombra = sum(len(v["sombra"]) for v in velas)
    con_reales = sum(1 for v in velas if v["reales"])
    con_sombra = sum(1 for v in velas if v["sombra"])
    return {
        "desde": desde,
        "velas": len(velas),
        "dias": round(dias, 1),
        "velas_con_la_cartera_llena": sum(1 for v in velas if v["llena"]),
        "operaciones_cerradas": len(cerradas),
        "candidatos_reales": reales,
        "candidatos_sombra": sombra,
        "por_dia": {"reales": round(reales / dias, 2), "sombra": round(sombra / dias, 2),
                    "juntos": round((reales + sombra) / dias, 2)},
        # Cada vela con candidatos es una llamada a la IA (decision B de la fase 3).
        "llamadas_por_dia": {"hoy": round(con_reales / dias, 2),
                             "con_sombra": round((con_reales + con_sombra) / dias, 2)},
        "distintos": {"reales": episodios(velas, "reales_de"), "sombra": episodios(velas, "sombra")},
        "sombra_por_setup": dict(Counter(s["setup"] for v in velas for s in v["sombra"])),
        "sombra_por_moneda": dict(Counter(s["symbol"] for v in velas for s in v["sombra"])),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("base", type=Path)
    p.add_argument("--since", required=True)
    a = p.parse_args()
    print(json.dumps(medir(a.base, a.since), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
