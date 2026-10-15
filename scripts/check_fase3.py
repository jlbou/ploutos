"""El juez de la fase 3: ¿una semana estable, sin salidas sin controlar y con el consumo medido?

El criterio (PRD 12 e informe 6, juntados en `docs/archivo/plan-fase-3.md` seccion 5) no tenia juez: el 02/10
habria que mirarlo a mano, y un criterio sin juez no es un criterio. Este lo mide de las bases:

1. **Una semana estable.** Las dos carteras cubren 7 dias desde su primera vela, van al dia (la ultima
   vela cerrada esta procesada, con 15 min de margen) y ninguna vela se perdio por una parada
   (`skipped_stale`: el servicio estuvo caido mas de una vela entera).
2. **Cero salidas invalidas SIN CONTROLAR.** Cada vela con candidatos de la IA tiene su fila en el
   journal (`ai_calls`). Si el analista lanza una excepcion, el bucle no hace nada y NO deja fila: esa es
   la salida sin controlar. Las invalidas controladas (timeout, error, salida fuera de contrato) se cuentan
   y se ensenyan, pero no son una FALLA: acaban en "no hacer nada", que es lo que pide el criterio. Que una
   salida invalida no deje decisiones ni ordenes lo juzga `check_paper` (el punto 4).
3. **Consumo medido**: llamadas por dia y por ventana de 5 h (regla 18), tokens, coste equivalente y
   latencia. La cuota semanal la mira el propietario en Settings > Usage (no hay API para leerla).
4. **El juez de papel en verde para las DOS carteras**: se lanza `check_paper.py` de cada una (se salta
   con `--sin-papel`, que es como lo lanzan los jueces diarios, que ya los pasan).

Y, para la decision 5 del protocolo de la fase 6 (candidatos en sombra), cuantos candidatos ve cada
cartera al dia y cuantas velas paso con la cartera llena.

    exit 0 -> criterio CUMPLIDO: 7 dias y todo en orden
    exit 1 -> FALLA (se dice que)
    exit 2 -> todo en orden, pero aun no hay 7 dias

Solo LEE (bases en `mode=ro`): se puede lanzar en el VPS con todo en marcha.

    .venv/bin/python scripts/check_fase3.py
    .venv/bin/python scripts/check_fase3.py --sin-papel      # sin volver a pasar check_paper
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai.journal import SKIPPED_BUDGET, SKIPPED_QUOTA, SKIPPED_STALE  # noqa: E402
from core.clock import timeframe_ms  # noqa: E402
from core.config import load_settings  # noqa: E402

DIA_MS = 24 * 3600_000
SEMANA_MS = 7 * DIA_MS
VENTANA_5H_MS = 5 * 3600_000
MARGEN_MS = 15 * 60_000           # tras el cierre de una vela, tiempo para procesarla
NO_LLAMO = (SKIPPED_BUDGET, SKIPPED_QUOTA, SKIPPED_STALE)
MAX_EJEMPLOS = 5
TIMEOUT_PAPEL_S = 600


def solo_lectura(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"no existe {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%d/%m %H:%M")


def percentil(xs: Sequence[float], p: float) -> float:
    """Percentil por el rango mas cercano (sin interpolar): con pocas llamadas, un valor que existio."""
    orden = sorted(xs)
    return orden[max(0, min(len(orden), math.ceil(p / 100 * len(orden))) - 1)]


@dataclass(frozen=True, slots=True)
class Cartera:
    """Lo que el juez necesita de una base de papel."""
    nombre: str
    inicio_ms: int | None                      # primera vela con equity
    cursor_ms: int | None                      # ultima vela procesada (su apertura)
    candidatos: dict[int, int]                 # vela -> candidatos generados
    llenas: int                                # velas con posiciones + pendientes >= el maximo
    velas: int                                 # velas con equity

    @classmethod
    def de(cls, nombre: str, conn: sqlite3.Connection, tf: str, max_posiciones: int) -> Cartera:
        eq = conn.execute("SELECT MIN(ts_ms), COUNT(*), SUM(positions + pending >= ?) FROM paper_equity",
                          (max_posiciones,)).fetchone()
        cur = conn.execute("SELECT last_ts_ms FROM paper_cursor WHERE timeframe = ?", (tf,)).fetchone()
        cands = dict(conn.execute("SELECT ts_ms, COUNT(*) FROM paper_decisions WHERE kind = 'candidate'"
                                  " GROUP BY ts_ms").fetchall())
        return cls(nombre, eq[0], cur[0] if cur else None, cands, int(eq[2] or 0), int(eq[1] or 0))


def llamadas_de(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT id, ts_ms, called_ms, kind, outcome, valid, n_candidates, latency_s, input_tokens,"
        " output_tokens, cache_created, cost_usd_equiv FROM ai_calls ORDER BY id")]


@dataclass
class Informe:
    fallas: list[str] = field(default_factory=list)
    lineas: list[str] = field(default_factory=list)
    cubierto_ms: int = 0

    def falla(self, texto: str) -> None:
        self.fallas.append(texto)

    def __call__(self, texto: str = "") -> None:
        self.lineas.append(texto)


def _ejemplos(ts: Sequence[int]) -> str:
    mas = f" y {len(ts) - MAX_EJEMPLOS} mas" if len(ts) > MAX_EJEMPLOS else ""
    return ", ".join(fmt(t) for t in ts[:MAX_EJEMPLOS]) + mas


def estabilidad(inf: Informe, carteras: Sequence[Cartera], llamadas: Sequence[dict[str, Any]],
                ahora_ms: int, paso_ms: int) -> None:
    """Criterio 1: cubren la semana, van al dia y no se perdio ninguna vela por una parada."""
    inf("1. Una semana estable")
    cubiertos = []
    ultima_cerrada = (ahora_ms // paso_ms) * paso_ms - paso_ms
    # Recien cerrada una vela, el bucle aun puede estar con ella: se admite la anterior.
    exigida = ultima_cerrada if ahora_ms - (ultima_cerrada + paso_ms) > MARGEN_MS else ultima_cerrada - paso_ms
    for c in carteras:
        if c.inicio_ms is None or c.cursor_ms is None:
            inf.falla(f"la cartera {c.nombre} no ha procesado ninguna vela")
            cubiertos.append(0)
            continue
        cubierto = c.cursor_ms + paso_ms - c.inicio_ms
        cubiertos.append(cubierto)
        inf(f"   {c.nombre:<9} desde {fmt(c.inicio_ms)}: {cubierto / DIA_MS:.1f} dias, ultima vela {fmt(c.cursor_ms)}")
        if c.cursor_ms < exigida:
            inf.falla(f"la cartera {c.nombre} va atrasada: ultima vela procesada {fmt(c.cursor_ms)}, "
                      f"y ya estaba cerrada la de {fmt(exigida)}")
    inf.cubierto_ms = min(cubiertos) if cubiertos else 0
    perdidas = sorted(int(x["ts_ms"]) for x in llamadas if x["outcome"] == SKIPPED_STALE)
    if perdidas:
        inf.falla(f"{len(perdidas)} vela(s) de la IA sin decidir por una parada: {_ejemplos(perdidas)}")
    else:
        inf("   ninguna vela perdida por una parada")


def control(inf: Informe, ia: Cartera, llamadas: Sequence[dict[str, Any]]) -> None:
    """Criterio 2: cada vela con candidatos tiene su fila en el journal, y cuadra."""
    inf("2. Salidas invalidas: todas controladas")
    por_vela: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for x in llamadas:
        if x["kind"] == "decision":
            por_vela[int(x["ts_ms"])].append(x)
    sin_fila = sorted(ts for ts in ia.candidatos if ts not in por_vela)
    if sin_fila:
        inf.falla(f"{len(sin_fila)} vela(s) con candidatos y sin fila en el journal (el analista fallo sin "
                  f"control): {_ejemplos(sin_fila)}")
    for ts, filas in sorted(por_vela.items()):
        n = ia.candidatos.get(ts, 0)
        if n == 0:
            inf.falla(f"vela {fmt(ts)}: fila en el journal sin candidatos apuntados")
        for x in filas:
            if int(x["n_candidates"]) != n:
                inf.falla(f"vela {fmt(ts)}: el journal dice {x['n_candidates']} candidato(s) y hay {n}")
    repetidas = sorted(ts for ts, f in por_vela.items() if len(f) > 1)
    if repetidas:
        inf(f"   aviso: {len(repetidas)} vela(s) con mas de una fila: {_ejemplos(repetidas)}")
    decisiones = [x for x in llamadas if x["kind"] == "decision"]
    resultados = Counter("invalida (fuera de contrato)" if x["outcome"] == "ok" and not x["valid"]
                         else "valida" if x["outcome"] == "ok" else x["outcome"] for x in decisiones)
    inf(f"   {len(decisiones)} vela(s) para decidir: " + (", ".join(f"{k} {v}" for k, v in
                                                                resultados.most_common()) or "ninguna"))
    controladas = len(decisiones) - resultados["valida"]
    if controladas:
        inf(f"   {controladas} sin decision util, todas en 'no hacer nada' (que no dejen ordenes lo juzga check_paper)")


def consumo(inf: Informe, llamadas: Sequence[dict[str, Any]], max_dia: int, max_5h: int,
            timeout_s: float, paso_ms: int) -> None:
    """Criterio 3: llamadas, tokens, coste equivalente y latencia. Es una medida, no un veredicto."""
    inf("3. Consumo de la IA")
    hechas = [x for x in llamadas if x["outcome"] not in NO_LLAMO]
    if not hechas:
        inf("   ninguna llamada todavia")
        return
    dias = Counter(datetime.fromtimestamp(x["called_ms"] / 1000, tz=UTC).date() for x in hechas)
    tiempos = sorted(int(x["called_ms"]) for x in hechas)
    pico_5h = max(sum(1 for u in tiempos if t - VENTANA_5H_MS < u <= t) for t in tiempos)
    sondas = sum(1 for x in hechas if x["kind"] == "probe")
    dias_cubiertos = max(inf.cubierto_ms / DIA_MS, 1.0)
    inf(f"   llamadas: {len(hechas)} ({sondas} sonda(s)); media {len(hechas) / dias_cubiertos:.1f}/dia, "
        f"pico {max(dias.values())}/dia (tope {max_dia}) y {pico_5h} en 5 h (tope {max_5h})")

    def suma(k: str) -> int:
        return sum(int(x[k] or 0) for x in hechas)
    coste = sum(float(x["cost_usd_equiv"] or 0) for x in hechas)
    inf(f"   tokens: {suma('input_tokens')} de entrada, {suma('output_tokens')} de salida, "
        f"{suma('cache_created')} de cache creada")
    inf(f"   coste equivalente (cuota, no dinero): {coste:.3f} $ en total, {coste / len(hechas):.4f} $/llamada,"
        f" ~{coste / dias_cubiertos * 7:.2f} $/semana")
    lat = [float(x["latency_s"]) for x in hechas if x["latency_s"] is not None]
    if lat:
        inf(f"   latencia: mediana {percentil(lat, 50):.1f} s, p95 {percentil(lat, 95):.1f} s, "
            f"maxima {max(lat):.1f} s (timeout {timeout_s:g} s)")
    retrasos = [(int(x["called_ms"]) - int(x["ts_ms"]) - paso_ms) / 1000 for x in hechas if x["kind"] == "decision"]
    if retrasos:
        inf(f"   llamada tras el cierre de la vela: mediana {percentil(retrasos, 50):.0f} s, maxima {max(retrasos):.0f} s")
    inf("   la cuota semanal: mirarla en Settings > Usage (no hay API para leerla)")


def candidatos(inf: Informe, carteras: Sequence[Cartera]) -> None:
    """Para la decision 5 del protocolo de la fase 6: cuanta muestra da el dia a dia."""
    inf("Para decidir los candidatos en sombra (decision 5 de la fase 6)")
    dias = max(inf.cubierto_ms / DIA_MS, 1.0)
    for c in carteras:
        total = sum(c.candidatos.values())
        inf(f"   {c.nombre:<9} {total} candidato(s) en {len(c.candidatos)} vela(s): {total / dias:.1f}/dia; "
            f"cartera llena en {c.llenas} de {c.velas} velas")


def papel(inf: Informe, correr: Callable[[Sequence[str]], tuple[int | None, str]]) -> None:
    """Criterio 4: el juez de papel de las dos carteras."""
    inf("4. El juez de papel de las dos carteras")
    for nombre, args in (("baseline", ("scripts/check_paper.py",)),
                         ("IA", ("scripts/check_paper.py", "--decider", "ai", "--paper-db",
                                 "var/ploutos-paper-ai.db"))):
        codigo, salida = correr(args)
        final = next((l.strip() for l in reversed(salida.splitlines()) if l.strip()), "")
        inf(f"   {nombre:<9} codigo {codigo}: {final}")
        if codigo not in (0, 2):
            inf.falla(f"el juez de papel del {nombre} da codigo {codigo}: {final}")


def ejecutar(args: Sequence[str]) -> tuple[int | None, str]:
    try:
        r = subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True,
                           timeout=TIMEOUT_PAPEL_S)
        return r.returncode, r.stdout + r.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"no se pudo ejecutar: {type(exc).__name__}"


def juzgar(base: Cartera, ia: Cartera, llamadas: Sequence[dict[str, Any]], *, ahora_ms: int, paso_ms: int,
           max_dia: int, max_5h: int, timeout_s: float,
           correr: Callable[[Sequence[str]], tuple[int | None, str]] | None) -> tuple[int, Informe]:
    inf = Informe()
    estabilidad(inf, (base, ia), llamadas, ahora_ms, paso_ms)
    inf()
    control(inf, ia, llamadas)
    inf()
    consumo(inf, llamadas, max_dia, max_5h, timeout_s, paso_ms)
    inf()
    if correr is not None:
        papel(inf, correr)
        inf()
    candidatos(inf, (base, ia))
    if inf.fallas:
        return 1, inf
    return (0 if inf.cubierto_ms >= SEMANA_MS else 2), inf


def main() -> int:
    ap = argparse.ArgumentParser(description="Juez de la fase 3: el analista en sombra")
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--paper-db", default=str(REPO / "var" / "ploutos-paper.db"))
    ap.add_argument("--ai-db", default=str(REPO / "var" / "ploutos-paper-ai.db"))
    ap.add_argument("--sin-papel", action="store_true", help="no lanzar check_paper (ya lo hacen los jueces diarios)")
    ap.add_argument("--ahora-ms", type=int, help="solo para pruebas")
    args = ap.parse_args()

    s = load_settings()
    paso = timeframe_ms(args.tf)
    base_db, ai_db = solo_lectura(Path(args.paper_db)), solo_lectura(Path(args.ai_db))
    base = Cartera.de("baseline", base_db, args.tf, s.risk.max_positions)
    ia = Cartera.de("IA", ai_db, args.tf, s.risk.max_positions)
    codigo, inf = juzgar(base, ia, llamadas_de(ai_db), ahora_ms=args.ahora_ms or int(time.time() * 1000),
                         paso_ms=paso, max_dia=s.claude.max_calls_per_day,
                         max_5h=s.claude.max_calls_per_5h_window, timeout_s=s.claude.timeout_seconds,
                         correr=None if args.sin_papel else ejecutar)
    print("\n".join(inf.lineas))
    print()
    for f in inf.fallas:
        print(f"FALLA {f}")
    if codigo == 1:
        print("RESULTADO: hay FALLAS.")
    elif codigo == 2:
        print(f"RESULTADO: todo en orden, pero solo {inf.cubierto_ms / DIA_MS:.1f} dias de 7. Aun no.")
    else:
        print("RESULTADO: CUMPLIDO (falta que el propietario mire la cuota semanal en Settings > Usage).")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
