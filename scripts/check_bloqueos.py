"""El juez de los bloqueos silenciosos: una cartera que lleva velas sin poder entrar por un motivo de SISTEMA.

Lo que es un bloqueo y por que existe este juez: `portfolio/bloqueos.py` (01/10/2026, la paridad de USDC
bloqueo 20 h y ningun juez lo vio porque el bot cumplia la regla).

    exit 0 -> ningun bloqueo de MIN_VELAS o mas que llegue a las ultimas `--horas`
    exit 1 -> FALLA: lo hay (se dice desde cuando, cuantas velas y por que)
    exit 2 -> sin velas que mirar (una cartera que no ha arrancado)

Los bloqueos mas viejos se ensenyan como nota, sin FALLA: ya pasaron y se avisaron (o no) en su dia. Lo lanza
`jueces_diarios.py` cada noche; la ventana de 24 h es la de esa pasada. Solo LEE (mode=ro).

    .venv/bin/python scripts/check_bloqueos.py
    .venv/bin/python scripts/check_bloqueos.py --paper-db <copia> --ahora-ms <hora de la copia>
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.config import load_settings  # noqa: E402
from portfolio.bloqueos import tramos_bloqueados  # noqa: E402

MIN_VELAS = 3          # 12 h en 4 h: menos puede ser una vela rara; mas ya no es casualidad
HORAS = 24
NOTAS_DIAS = 7


def _hora(ms: int) -> str:
    return time.strftime("%d/%m %H:%M", time.gmtime(ms / 1000))


def juzgar(conn: sqlite3.Connection, whitelist: list[str], ahora_ms: int, horas: int,
           min_velas: int) -> tuple[list[str], list[str], int]:
    """(fallos, notas, velas miradas) de una cartera."""
    desde_notas = ahora_ms - NOTAS_DIAS * 86_400_000
    velas = [r[0] for r in conn.execute(
        "SELECT ts_ms FROM paper_equity WHERE ts_ms >= ? AND ts_ms <= ? ORDER BY ts_ms", (desde_notas, ahora_ms))]
    filas = conn.execute(
        "SELECT ts_ms, symbol, kind, detail FROM paper_decisions WHERE ts_ms >= ? AND ts_ms <= ?",
        (desde_notas, ahora_ms)).fetchall()
    fallos, notas = [], []
    for t in tramos_bloqueados(velas, filas, whitelist):
        if t.velas < min_velas:
            continue
        texto = (f"{t.velas} velas seguidas sin poder entrar ({_hora(t.desde_ms)} - {_hora(t.hasta_ms)} UTC),"
                 f" por: {', '.join(t.motivos)}")
        if t.hasta_ms >= ahora_ms - horas * 3_600_000:
            fallos.append(texto)
        else:
            notas.append(texto)
    return fallos, notas, len(velas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--paper-db", action="append",
                    help="la base de una cartera (se puede repetir); por defecto, las dos del VPS")
    ap.add_argument("--horas", type=int, default=HORAS)
    ap.add_argument("--min-velas", type=int, default=MIN_VELAS)
    ap.add_argument("--ahora-ms", type=int, default=None)
    args = ap.parse_args()
    ahora = args.ahora_ms if args.ahora_ms is not None else int(time.time() * 1000)
    bases = args.paper_db or [str(REPO / "var" / "ploutos-paper.db"), str(REPO / "var" / "ploutos-paper-ai.db")]
    whitelist = list(load_settings().whitelist)

    hay_fallo, alguna = False, False
    print(f"Bloqueos silenciosos: {args.min_velas}+ velas seguidas sin poder entrar por un motivo de sistema"
          f" (ventana {args.horas} h; notas de {NOTAS_DIAS} dias)")
    for ruta in bases:
        nombre = Path(ruta).name
        if not Path(ruta).exists():
            print(f"  ---   {nombre}: no existe")
            continue
        conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        try:
            fallos, notas, n = juzgar(conn, whitelist, ahora, args.horas, args.min_velas)
        finally:
            conn.close()
        if n == 0:
            print(f"  ---   {nombre}: sin velas en los ultimos {NOTAS_DIAS} dias")
            continue
        alguna = True
        print(f"  {'FALLA' if fallos else 'OK   '} {nombre}: {n} velas miradas")
        for f in fallos:
            print(f"          - {f}")
        for x in notas:
            print(f"          (antes) {x}")
        hay_fallo |= bool(fallos)
    print()
    if hay_fallo:
        print("RESULTADO: una cartera lleva velas sin poder entrar por un motivo que no es el mercado. Revisalo.")
        return 1
    if not alguna:
        print("RESULTADO: sin velas que mirar.")
        return 2
    print("RESULTADO: sin bloqueos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
