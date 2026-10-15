"""El juez del embudo de noticias (`docs/diseno-embudo-noticias.md`, el propietario, 11/10/2026). Sale con 0 (bien), 1 (FALLA) o
2 (aun no ha empezado), como los demas jueces de cada noche. FALLA si:
- la ultima pasada tiene mas de 2 h (el embudo no corre; el temporizador va cada 30 min);
- en algun dia UTC hizo mas de 6 llamadas a la IA, o el total con el analista paso de 40 en un dia o de 8 en 5 h
  (regla 18);
- alguna salida invalida de la IA se dio por buena (una llamada no valida con un veredicto que no sea "sin veredicto").

    .venv/bin/python scripts/check_embudo.py [--base var/ploutos-embudo.db] [--ahora-ms N]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from embudo_noticias import ANALISTA, BASE, INICIO, PRESUPUESTO_DIA, REGLA18_5H, REGLA18_DIA, ms  # noqa: E402

FRESCURA_MS = 2 * 3600_000
DIA_MS = 86_400_000


def juzgar(emb: sqlite3.Connection | None, analista: sqlite3.Connection | None, ahora_ms: int) -> tuple[int, list[str]]:
    if ahora_ms < ms(INICIO) + FRESCURA_MS:
        return 2, [f"el embudo empieza el {INICIO}: aun no hay nada que juzgar"]
    if emb is None:
        return 1, ["FALLA: el embudo no ha corrido nunca (no hay base)"]
    lineas, falla = [], False
    ultima = emb.execute("SELECT MAX(ms) FROM pasadas WHERE ok = 1").fetchone()[0]
    if ultima is None or ahora_ms - ultima > FRESCURA_MS:
        lineas.append("FALLA: el embudo no corre (ultima pasada: "
                      + ("nunca" if ultima is None else f"hace {(ahora_ms - ultima) / 3600_000:.1f} h") + ")")
        falla = True
    llamadas = [r[0] for r in emb.execute("SELECT ms FROM llamadas ORDER BY ms")]
    por_dia: dict[int, int] = {}
    for t in llamadas:
        por_dia[t // DIA_MS] = por_dia.get(t // DIA_MS, 0) + 1
    if any(n > PRESUPUESTO_DIA for n in por_dia.values()):
        lineas.append(f"FALLA: mas de {PRESUPUESTO_DIA} llamadas del embudo en un dia: {max(por_dia.values())}")
        falla = True
    suyas: list[int] = []
    if analista is not None:
        try:
            suyas = [r[0] for r in analista.execute(
                "SELECT called_ms FROM ai_calls WHERE outcome NOT LIKE 'skipped%' AND called_ms >= ?", (ms(INICIO),))]
        except sqlite3.OperationalError:
            suyas = []
    todas = sorted(llamadas + suyas)
    dias: dict[int, int] = {}
    for t in todas:
        dias[t // DIA_MS] = dias.get(t // DIA_MS, 0) + 1
    if any(n > REGLA18_DIA for n in dias.values()):
        lineas.append(f"FALLA: regla 18, mas de {REGLA18_DIA} llamadas a la IA en un dia (analista + embudo)")
        falla = True
    for i, t in enumerate(todas):
        if sum(1 for u in todas[i:] if u < t + 5 * 3600_000) > REGLA18_5H:
            lineas.append(f"FALLA: regla 18, mas de {REGLA18_5H} llamadas a la IA en 5 h (analista + embudo)")
            falla = True
            break
    malas = emb.execute("SELECT COUNT(*) FROM llamadas WHERE valida = 0 AND veredicto IS NOT NULL").fetchone()[0]
    if malas:
        lineas.append(f"FALLA: {malas} salida(s) invalida(s) de la IA dadas por buenas")
        falla = True
    resumen = {e: n for e, n in emb.execute("SELECT COALESCE(veredicto, estado), COUNT(*) FROM casos GROUP BY 1")}
    lineas.append(f"casos: {resumen or 'ninguno'}; llamadas a la IA: {len(llamadas)}")
    lineas.append("RESULTADO: FALLA" if falla else "RESULTADO: en orden")
    return (1 if falla else 0), lineas


def main() -> int:
    ap = argparse.ArgumentParser(description="El juez del embudo de noticias")
    ap.add_argument("--base", default=str(BASE))
    ap.add_argument("--ahora-ms", type=int, default=None)
    args = ap.parse_args()

    def ro(ruta: Path) -> sqlite3.Connection | None:
        return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True) if ruta.exists() else None

    codigo, lineas = juzgar(ro(Path(args.base)), ro(ANALISTA), args.ahora_ms or int(time.time() * 1000))
    print("Embudo de noticias (en sombra)")
    for linea in lineas:
        print(linea)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
