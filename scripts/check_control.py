"""El juez de los comandos de Telegram (docs/diseno-comandos-telegram.md, pieza 7).

Relee la base de control y las de las carteras, y comprueba:

1. el servicio no se ha parado (una vuelta cada <= 10 min; el sondeo largo da una cada ~25 s);
2. cada comando ejecutado recibio su respuesta;
3. ningun comando de Telegram se ejecuto tarde (> 2 min) y ninguno levanto un /kill; lo del VPS,
   solo levantar el /kill y con motivo;
4. la pausa solo cayo con un /si a <= 60 s de su /resume, y la parada solo desde el VPS
   (comprobado paso a paso con reglas escritas aqui, no con la funcion que se juzga);
5. cada cartera tuvo en cada vela exactamente la pausa y la parada que tocaban.

Que no se abrio nada con una pausa ya lo juzga `check_paper.py --control-db`.

    exit 0 -> criterio CUMPLIDO: >= 7 dias de servicio y todo coherente
    exit 1 -> hay incoherencias (se dice cuales)
    exit 2 -> coherente, pero aun no hay 7 dias

Solo LEE (mode=ro): se puede lanzar en el VPS con todo en marcha.

    .venv/bin/python scripts/check_control.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.clock import timeframe_ms  # noqa: E402
from notify import control  # noqa: E402
from notify.comandos import CONFIRMAR_MS, EDAD_MAX_MS, Comando, Orden, reconstruir  # noqa: E402

HUECO_MAX_MS = 10 * 60_000
DIAS_CRITERIO = 7
MAX_EJEMPLOS = 5
MANUALES = ("CLOSE_ONLY_MANUAL", "HALTED")


class Check:
    def __init__(self, nombre: str):
        self.nombre, self.fallos, self.comprobados = nombre, [], 0

    @property
    def ok(self) -> bool:
        return not self.fallos


def _fmt(ms: int) -> str:
    return time.strftime("%d/%m %H:%M:%S", time.gmtime(ms / 1000))


def juzgar(ctl: sqlite3.Connection, carteras: dict[str, sqlite3.Connection],
           tf_ms: int) -> tuple[list[Check], int]:
    """Las comprobaciones, y cuantos ms de servicio hay (de la primera a la ultima vuelta)."""
    vueltas = [r[0] for r in ctl.execute("SELECT ms FROM control_lecturas ORDER BY ms")]
    filas = [dict(r) for r in ctl.execute("SELECT * FROM control_comandos ORDER BY id")]
    avisos = {r["clave"]: dict(r) for r in ctl.execute("SELECT * FROM paper_avisos")}
    comandos = control.comandos(ctl)
    checks = []

    c = Check("el servicio no se ha parado (una vuelta cada <= 10 min)")
    for a, b in zip(vueltas, vueltas[1:]):
        c.comprobados += 1
        if b - a > HUECO_MAX_MS:
            c.fallos.append(f"sin vueltas de {_fmt(a)} a {_fmt(b)} ({(b - a) / 60_000:.0f} min)")
    checks.append(c)

    c = Check("cada comando de Telegram recibio su respuesta")
    for f in filas:
        if f["origen"] != "telegram":
            continue                     # el panel contesta en pantalla; el VPS, en la terminal
        c.comprobados += 1
        aviso = avisos.get(f"comando:{f['id']}")
        if aviso is None:
            c.fallos.append(f"{f['orden']} de las {_fmt(f['ts_ms'])}: sin respuesta")
        elif aviso["enviado_ms"] is None:
            c.fallos.append(f"{f['orden']} de las {_fmt(f['ts_ms'])}: respuesta sin enviar"
                            f" ({aviso['ultimo_error'] or 'sin error apuntado'})")
    checks.append(c)

    c = Check("comandos a tiempo, y el /kill solo se levanta en el VPS o el panel con motivo")
    for f in filas:
        c.comprobados += 1
        cuando = f"{f['orden']} de las {_fmt(f['ts_ms'])}"
        if f["origen"] == "telegram":
            if f["recibido_ms"] - f["ts_ms"] > EDAD_MAX_MS:
                c.fallos.append(f"{cuando}: ejecutado tarde (recibido a las {_fmt(f['recibido_ms'])})")
            if f["orden"] == Orden.LEVANTAR_KILL.value:
                c.fallos.append(f"{cuando}: levantar el /kill desde Telegram")
            if f["orden"] == Orden.CERRAR_TODO.value:
                c.fallos.append(f"{cuando}: cerrar todo desde Telegram (solo el panel)")
        elif f["origen"] == "vps":
            if f["orden"] != Orden.LEVANTAR_KILL.value:
                c.fallos.append(f"{cuando}: desde el VPS solo se levanta el /kill")
            if not (f["texto"] or "").strip():
                c.fallos.append(f"{cuando}: sin motivo")
        elif f["origen"] == "panel":
            if f["orden"] == Orden.LEVANTAR_KILL.value and not (f["texto"] or "").strip():
                c.fallos.append(f"{cuando}: sin motivo")
        else:
            c.fallos.append(f"{cuando}: origen desconocido {f['origen']!r}")
    checks.append(c)

    c = Check("la pausa solo cae con /si a tiempo; la parada, solo desde el VPS o el panel")
    antes = reconstruir([])
    for i, (f, cmd) in enumerate(zip(filas, comandos)):
        c.comprobados += 1
        despues = reconstruir(comandos[: i + 1])
        cuando = f"{f['orden']} de las {_fmt(f['ts_ms'])}"
        if antes.kill_ms is not None and despues.kill_ms is None:
            if not (f["origen"] in ("vps", "panel") and cmd.orden is Orden.LEVANTAR_KILL):
                c.fallos.append(f"{cuando}: quito la parada sin ser el VPS ni el panel")
        if antes.pausa_ms is not None and despues.pausa_ms is None:
            previos = [p for p in comandos[:i] if p.orden is not Orden.STATUS]
            resume = previos[-1] if previos and previos[-1].orden is Orden.RESUME else None
            if not (f["origen"] in ("telegram", "panel") and cmd.orden is Orden.SI and resume is not None
                    and 0 <= cmd.ts_ms - resume.ts_ms <= CONFIRMAR_MS):
                c.fallos.append(f"{cuando}: quito la pausa sin un /si a tiempo de su /resume")
        antes = despues
    checks.append(c)

    c = Check("cada cartera tuvo la pausa y la parada que tocaban en cada vela")
    for nombre, conn in carteras.items():
        cambios = [(int(r["ts_ms"]), r["mode"], bool(r["activated"])) for r in conn.execute(
            "SELECT ts_ms, mode, activated FROM paper_mode_changes ORDER BY id")
            if r["mode"] in MANUALES]
        for (ts,) in conn.execute("SELECT ts_ms FROM paper_equity ORDER BY ts_ms"):
            c.comprobados += 1
            activos: set[str] = set()
            for t, modo, activado in cambios:
                if t <= ts:
                    (activos.add if activado else activos.discard)(modo)
            esperados = {m.name for m in _estado_en(comandos, ts + tf_ms).modos}
            if activos != esperados:
                c.fallos.append(f"{nombre}, vela de las {_fmt(ts)}: tenia {sorted(activos) or 'nada'}"
                                f" y tocaba {sorted(esperados) or 'nada'}")
    checks.append(c)

    servicio = vueltas[-1] - vueltas[0] if len(vueltas) > 1 else 0
    return checks, servicio


def _estado_en(comandos: list[Comando], decision_ms: int):
    return reconstruir([c for c in comandos if c.ts_ms <= decision_ms])


def main() -> int:
    ap = argparse.ArgumentParser(description="Juez de los comandos de Telegram")
    ap.add_argument("--control-db", default=str(REPO / "var" / "ploutos-control.db"))
    ap.add_argument("--paper-db", action="append",
                    help="una base de cartera (se puede repetir); por defecto, las dos")
    ap.add_argument("--tf", default="4h")
    args = ap.parse_args()

    ctl = control.solo_lectura(args.control_db)
    if ctl is None:
        print(f"No existe {args.control_db}: el servicio de comandos no ha arrancado.")
        return 2
    rutas = args.paper_db or [str(REPO / "var" / "ploutos-paper.db"), str(REPO / "var" / "ploutos-paper-ai.db")]
    carteras = {}
    for ruta in rutas:
        if Path(ruta).exists():
            conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            carteras[Path(ruta).stem] = conn
    checks, servicio = juzgar(ctl, carteras, timeframe_ms(args.tf))

    print(f"Comandos: {servicio / 86_400_000:.1f} dias de servicio; carteras: {', '.join(carteras) or 'ninguna'}")
    for c in checks:
        print(f"  {'OK   ' if c.ok else 'FALLA'} {c.nombre}  ({c.comprobados} comprobados)")
        for f in c.fallos[:MAX_EJEMPLOS]:
            print(f"          - {f}")
        if len(c.fallos) > MAX_EJEMPLOS:
            print(f"          ... y {len(c.fallos) - MAX_EJEMPLOS} mas")
    print()
    if any(not c.ok for c in checks):
        print("RESULTADO: hay incoherencias. El criterio NO se cumple.")
        return 1
    if servicio < DIAS_CRITERIO * 86_400_000:
        print(f"RESULTADO: coherente, pero aun no hay {DIAS_CRITERIO} dias de servicio.")
        return 2
    print("RESULTADO: CUMPLIDO.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
