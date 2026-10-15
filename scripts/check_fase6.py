"""El juez de la fase 6: ¿elige mejor la IA que el baseline? (docs/archivo/protocolo-fase-6.md)

Hermano de `check_gaps.py` y `check_paper.py`: esto es el juez, no una opinion. Las
reglas se fijaron ANTES de ver datos (decisiones del propietario del 24/09/2026) y viven en
`portfolio/comparacion.py`.

Mientras no se cumple el calendario (3 semanas y 30 discrepancias, o 8 semanas), SOLO
dice si los datos estan bien y cuanta muestra hay. El resultado no se ensenya a mitad
de camino: mirarlo cada dia y parar cuando sale bonito es la forma mas comun de
enganyarse con estadistica.

    exit 0 -> veredicto disponible (y datos coherentes)
    exit 1 -> los datos NO cuadran (se dice que): la comparacion no vale hasta arreglarlo
    exit 2 -> datos coherentes, pero todavia no toca el veredicto

Solo LEE, de las tres bases: se puede lanzar en el VPS con todo en marcha.

    .venv/bin/python scripts/check_fase6.py
    .venv/bin/python scripts/check_fase6.py --camino <huella>     # otro tramo
    .venv/bin/python scripts/check_fase6.py --sombra              # la M1 EN SOMBRA, aparte

LA M1 EN SOMBRA (decision 5 del protocolo; opcion B del propietario del 02/10). Con la cartera llena, la IA decide sobre
lo que saldria con hueco (`kind = 'sombra'` en el journal) y no se abre nada. Es OTRA medicion: se juzga aparte,
con las MISMAS reglas (`portfolio/comparacion.py`: resolucion, M1, intervalo, veredicto, calendario desde su
primera vela) y nunca se junta con la de verdad. El baseline "elige" sobre la misma lista, por codigo, como en
la de verdad. Este juez se escribio ANTES de que existiera ningun dato de sombra (02/10).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai.journal import SKIPPED_BUDGET, SKIPPED_QUOTA, SKIPPED_STALE  # noqa: E402
from ai.parser import parse  # noqa: E402
from ai.prompt import candidate_ids, position_ids  # noqa: E402
from core.clock import from_ms, timeframe_ms  # noqa: E402
from core.config import load_settings  # noqa: E402
from portfolio import comparacion as cmp  # noqa: E402
from portfolio.paper import Bar  # noqa: E402

MAX_EJEMPLOS = 5
# Fallos de infraestructura, no de la IA: sin llamada util no hay decision que medir.
EXCLUIDAS = {
    SKIPPED_STALE: "vela atrasada tras una parada",
    SKIPPED_BUDGET: "sin presupuesto (regla 18)",
    SKIPPED_QUOTA: "en CLOSE_ONLY_QUOTA",
    "quota": "cuota de Claude agotada",
    "auth": "login de Claude caducado",
}
# Fallos de la IA: cuentan, como "no abrir nada" (en produccion haria lo mismo).
FALLOS_IA = {"timeout", "error"}
SIN_TRAMO = "(sin huella)"


def solo_lectura(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"no existe {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def entrada_de(prompt: str | None) -> dict[str, Any] | None:
    """El JSON que vio la IA: la primera linea del prompt guardado (ai.prompt.render)."""
    if not prompt:
        return None
    try:
        return json.loads(prompt.split("\n", 1)[0])
    except ValueError:
        return None


_NUM = r"([-+0-9.eE]+)"
_DETALLE = re.compile(rf"entrada {_NUM}, stop {_NUM} .*objetivo {_NUM}")


def numeros_baseline(detalle: str) -> tuple[float, float, float] | None:
    """Entrada, stop y objetivo del `str(Candidate)` que guarda el papel (6 cifras)."""
    m = _DETALLE.search(detalle or "")
    return tuple(float(x) for x in m.groups()) if m else None  # type: ignore[return-value]


class Informe:
    def __init__(self) -> None:
        self.fallos: list[str] = []
        self.notas: list[str] = []

    def falla(self, texto: str) -> None:
        self.fallos.append(texto)


def main() -> int:
    ap = argparse.ArgumentParser(description="Juez de la fase 6: IA contra baseline")
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--main-db", default=str(REPO / "var" / "ploutos.db"))
    ap.add_argument("--paper-db", default=str(REPO / "var" / "ploutos-paper.db"))
    ap.add_argument("--ai-db", default=str(REPO / "var" / "ploutos-paper-ai.db"))
    ap.add_argument("--camino", help="huella del tramo a juzgar (por defecto, el ultimo)")
    ap.add_argument("--ahora-ms", type=int, help="solo para pruebas")
    ap.add_argument("--sombra", action="store_true", help="la M1 en sombra (otra medicion, aparte)")
    args = ap.parse_args()
    tipo = "sombra" if args.sombra else "decision"

    settings = load_settings()
    paso = timeframe_ms(args.tf)
    ahora = args.ahora_ms or int(time.time() * 1000)
    ai_db = solo_lectura(Path(args.ai_db))
    inf = Informe()

    filas = [dict(r) for r in ai_db.execute(
        "SELECT * FROM ai_calls WHERE kind = ? ORDER BY ts_ms, id", (tipo,))]
    if not filas:
        print("La cartera de la IA no ha decidido ninguna vela" + (" en sombra" if args.sombra else "")
              + " todavia.")
        return 2

    # --- Tramos: solo se juntan decisiones tomadas con el mismo camino ---
    tramos = Counter(f.get("camino") or SIN_TRAMO for f in filas)
    elegido = args.camino or (filas[-1].get("camino") or SIN_TRAMO)
    if elegido not in tramos:
        raise SystemExit(f"no hay ningun tramo {elegido!r}; hay: {', '.join(tramos)}")
    filas = [f for f in filas if (f.get("camino") or SIN_TRAMO) == elegido]
    inicio = filas[0]["ts_ms"]

    # --- 1. Datos completos y coherentes con el journal ---
    abiertos_journal: dict[int, set[str]] = defaultdict(set)
    for r in ai_db.execute("SELECT call_id, ref FROM ai_decisions WHERE type = 'open'"):
        abiertos_journal[r["call_id"]].add(r["ref"])

    excluidas: Counter[str] = Counter()
    fallos_ia = 0
    decisiones: list[cmp.Decision] = []
    for f in filas:
        if f["outcome"] in EXCLUIDAS:
            excluidas[f["outcome"]] += 1
            continue
        entrada = entrada_de(f["prompt"])
        if entrada is None or "candidates" not in entrada:
            inf.falla(f"vela {from_ms(f['ts_ms']):%d/%m %H:%M}: la llamada no guardo la entrada")
            continue
        cands = tuple(
            cmp.Cand(c["cid"], c["symbol"], float(c["entry"]), float(c["stop"]),
                     float(c["target"]), str(c.get("regime", "")))
            for c in entrada["candidates"]
        )
        lim = entrada.get("limits", {})
        cupo = min(int(lim.get("slots_free", 0)), int(lim.get("trades_left_today", 0)))
        abiertos: tuple[tuple[str, float], ...] = ()
        if f["outcome"] == "ok":
            estructurada = json.loads(f["structured"]) if f["structured"] else None
            p = parse(estructurada, candidate_ids(entrada), position_ids(entrada))
            if int(p.ok) != int(f["valid"]):
                inf.falla(f"vela {from_ms(f['ts_ms']):%d/%m %H:%M}: el journal dice valid="
                          f"{f['valid']} y la salida guardada da {int(p.ok)}")
            if p.ok:
                abiertos = tuple((o.cid, o.size_multiplier) for o in p.opens)
                if {cid for cid, _ in abiertos} != abiertos_journal.get(f["id"], set()):
                    inf.falla(f"vela {from_ms(f['ts_ms']):%d/%m %H:%M}: los 'open' del journal "
                              "no son los de la salida guardada")
            else:
                fallos_ia += 1
        elif f["outcome"] in FALLOS_IA:
            fallos_ia += 1
        else:
            inf.falla(f"vela {from_ms(f['ts_ms']):%d/%m %H:%M}: resultado desconocido {f['outcome']!r}")
            continue
        decisiones.append(cmp.Decision(f["ts_ms"], cands, abiertos, cupo))

    # --- 2. Mismos candidatos: un cid con los mismos numeros en las dos carteras ---
    vistos_ia = {c.cid: c for d in decisiones for c in d.candidatos}
    comunes = 0
    if args.sombra:
        pass    # la sombra no tiene par en el baseline: el baseline elige sobre la MISMA lista (seleccion_baseline)
    elif Path(args.paper_db).exists():
        base_db = solo_lectura(Path(args.paper_db))
        for r in base_db.execute(
            "SELECT decision_id, detail FROM paper_decisions WHERE kind = 'candidate'"
            " AND ts_ms >= ?", (inicio,),
        ):
            c = vistos_ia.get(r["decision_id"])
            if c is None:
                continue
            nums = numeros_baseline(r["detail"])
            if nums is None:
                # Un candidato comun cuyos numeros no se entienden: si cambia el formato del texto
                # guardado, el juez dejaria de comparar SIN DECIRLO (revision del 25/09).
                inf.falla(f"{c.cid}: no se entienden los numeros del baseline ({(r['detail'] or '')[:60]!r})")
                continue
            comunes += 1
            for nombre, a, b in zip(("entrada", "stop", "objetivo"), (c.entry, c.stop, c.target), nums):
                if abs(a - b) > 1e-5 * abs(a):
                    inf.falla(f"{c.cid}: {nombre} {a} en la IA y {b} en el baseline")
        if vistos_ia and comunes == 0:
            # "0 comparados" no puede pasar en verde: las dos carteras reciben los mismos candidatos.
            inf.falla(f"ninguno de los {len(vistos_ia)} candidatos de la IA esta en el baseline con sus"
                      " numeros: no se ha podido comprobar que vean lo mismo")
    else:
        inf.notas.append("sin la base del baseline: no se comprueba que vean los mismos candidatos")

    # --- Cobertura: velas con candidatos que la IA ni siquiera apunto ---
    con_candidatos = {r[0] for r in ai_db.execute(
        "SELECT DISTINCT ts_ms FROM paper_decisions WHERE kind = 'candidate' AND ts_ms >= ?",
        (inicio,))}
    apuntadas = {f["ts_ms"] for f in filas}
    sin_fila = 0 if args.sombra else len(con_candidatos - apuntadas)
    if sin_fila:
        inf.notas.append(f"{sin_fila} vela(s) con candidatos sin fila del analista: modos de solo"
                         " cierre (DAILY, CAPITAL, DEGRADED), en los que nadie puede abrir")

    # --- 3. Resolver cada candidato contra las velas reales ---
    main_db = solo_lectura(Path(args.main_db))
    fees = {
        r["symbol"]: (r["maker_fee"], r["taker_fee"])
        for r in settings.exchange.fees.apply(
            [dict(x) for x in main_db.execute("SELECT * FROM instruments")])
    }
    simbolos = {c.symbol for d in decisiones for c in d.candidatos}
    bars: dict[str, list[Bar]] = {}
    for s in simbolos:
        bars[s] = [Bar.from_row(dict(x)) for x in main_db.execute(
            "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? AND closed = 1"
            " AND ts_open_ms > ? ORDER BY ts_open_ms", (s, args.tf, inicio))]
    resultados: dict[tuple[int, str], cmp.Resultado] = {}
    for d in decisiones:
        for c in d.candidatos:
            if c.symbol not in fees:
                inf.falla(f"{c.cid}: {c.symbol} sin comisiones en instruments")
                continue
            maker, taker = fees[c.symbol]
            resultados[(d.ts_ms, c.cid)] = cmp.resolver(
                c, d.ts_ms, bars.get(c.symbol, []), tf_ms=paso, maker=maker, taker=taker)
    velas, pendientes = cmp.evaluar(decisiones, resultados)
    discrepancias = sum(v.discrepa for v in velas)
    cal = cmp.Calendario(inicio)

    # --- Informe ---
    titulo = ("Fase 6, M1 EN SOMBRA (otra medicion: se juzga aparte y no se junta con la de verdad)"
              if args.sombra else "Fase 6, IA contra baseline")
    print(f"{titulo}. Tramo {elegido} desde {from_ms(inicio):%d/%m/%Y %H:%M} UTC")
    if len(tramos) > 1:
        otros = ", ".join(f"{t} ({n} filas)" for t, n in tramos.items() if t != elegido)
        print(f"  OJO: hay otros tramos que NO se juntan con este: {otros}")
    print()
    print("  Datos")
    print(f"    {'OK   ' if not inf.fallos else 'FALLA'} journal completo y coherente con la salida guardada")
    if args.sombra:
        print("    --    mismos candidatos en las dos carteras (no aplica: el baseline elige sobre la misma lista)")
    else:
        print(f"    {'OK   ' if not inf.fallos else 'FALLA'} mismos candidatos en las dos carteras "
              f"({comunes} comparados)")
    for texto in inf.fallos[:MAX_EJEMPLOS]:
        print(f"          - {texto}")
    if len(inf.fallos) > MAX_EJEMPLOS:
        print(f"          ... y {len(inf.fallos) - MAX_EJEMPLOS} mas")
    for nota in inf.notas:
        print(f"          OJO: {nota}")
    print()
    print("  Cobertura")
    print(f"    velas apuntadas por el analista: {len(filas)}")
    print(f"    decididas: {len(decisiones)} (de ellas {fallos_ia} con fallo de la IA, que cuentan"
          " como no abrir nada)")
    for motivo, n in excluidas.items():
        print(f"    excluida: {n} x {EXCLUIDAS[motivo]}")
    print()
    print("  Muestra")
    print(f"    juzgables: {len(velas)} velas; {pendientes} esperando su horizonte de "
          f"{cmp.HORIZONTE_VELAS} velas")
    print(f"    velas en que la IA y el baseline discrepan: {discrepancias} de {cmp.MIN_DISCREPANCIAS}")
    print(f"    calendario: minimo {from_ms(cal.minimo_ms):%d/%m/%Y}, tope {from_ms(cal.tope_ms):%d/%m/%Y}")
    print()

    if inf.fallos:
        print("RESULTADO: los datos NO cuadran. La comparacion no vale hasta arreglarlo.")
        return 1
    if not cal.abierto(ahora, discrepancias):
        falta = []
        if ahora < cal.minimo_ms:
            falta.append(f"{(cal.minimo_ms - ahora) / cmp.DIA_MS:.0f} dias")
        if discrepancias < cmp.MIN_DISCREPANCIAS:
            falta.append(f"{cmp.MIN_DISCREPANCIAS - discrepancias} discrepancias")
        print(f"VEREDICTO: todavia no (faltan {' y '.join(falta)}). Los datos estan bien.")
        return 2

    intervalo = cmp.bootstrap_por_dias([(v.ts_ms, v.m1) for v in velas])
    resultado = cmp.veredicto(intervalo, discrepancias)
    print("  M1, seleccion (R por vela: IA menos baseline; > 0 = la IA elige mejor)")
    if intervalo:
        print(f"    media {intervalo.media:+.3f} R, intervalo del 90 % [{intervalo.lo:+.3f}, "
              f"{intervalo.hi:+.3f}] ({intervalo.velas} velas, {intervalo.dias} dias)")
    por_regimen: dict[str, list[float]] = defaultdict(list)
    for v in velas:
        por_regimen[v.regimen].append(v.m1)
    for reg, vals in sorted(por_regimen.items()):
        print(f"    regimen {reg}: {fmean(vals):+.3f} R en {len(vals)} velas")
    ab, n_ab, sa, n_sa = cmp.m2(velas)
    print("  M2, veto (R media de lo que abre y de lo que salta)")
    print(f"    abiertos: {ab if ab is None else f'{ab:+.3f} R'} ({n_ab}); "
          f"saltados: {sa if sa is None else f'{sa:+.3f} R'} ({n_sa})")
    con, sin = cmp.m3(velas)
    print("  M3, tamanyo (R total de lo que abrio, con y sin su multiplicador)")
    print(f"    con {con:+.2f} R, sin {sin:+.2f} R")
    print()
    if not args.sombra:
        print("  Las carteras (solo descriptivo: con tan pocas operaciones, no decide)")
        for nombre, ruta in (("baseline", args.paper_db), ("IA", args.ai_db)):
            if Path(ruta).exists():
                print(f"    {nombre}: {cartera(solo_lectura(Path(ruta)), inicio)}")
        print(f"    comprar y esperar: {esperar(main_db, settings.whitelist, args.tf, inicio)}")
        print()
    print(f"VEREDICTO: {resultado}")
    return 0


def cartera(conn: sqlite3.Connection, desde: int) -> str:
    trades = conn.execute(
        "SELECT net_pnl_usd, r_multiple FROM paper_trades WHERE opened_ts_ms >= ?", (desde,)
    ).fetchall()
    equity = [r[0] for r in conn.execute(
        "SELECT equity_usd FROM paper_equity WHERE ts_ms >= ? ORDER BY ts_ms", (desde,))]
    if not equity:
        return "sin datos"
    pico, caida = equity[0], 0.0
    for e in equity:
        pico = max(pico, e)
        caida = max(caida, (pico - e) / pico if pico else 0.0)
    rs = [t["r_multiple"] for t in trades]
    ganado = sum(t["net_pnl_usd"] for t in trades if t["net_pnl_usd"] > 0)
    perdido = -sum(t["net_pnl_usd"] for t in trades if t["net_pnl_usd"] < 0)
    pf = f"{ganado / perdido:.2f}" if perdido else "-"
    exp = f"{fmean(rs):+.2f} R" if rs else "-"
    return (f"{equity[0]:.2f} -> {equity[-1]:.2f} $, {len(trades)} operaciones, "
            f"expectativa {exp}, profit factor {pf}, caida maxima {caida * 100:.1f} %")


def esperar(main_db: sqlite3.Connection, whitelist: tuple[str, ...], tf: str, desde: int) -> str:
    cambios = {}
    for s in whitelist:
        filas = main_db.execute(
            "SELECT close FROM candles WHERE symbol = ? AND timeframe = ? AND closed = 1"
            " AND ts_open_ms >= ? ORDER BY ts_open_ms", (s, tf, desde)).fetchall()
        if len(filas) >= 2:
            cambios[s] = filas[-1][0] / filas[0][0] - 1
    if not cambios:
        return "sin datos"
    btc = next((v for s, v in cambios.items() if s.startswith("BTC/")), None)
    btc_txt = f"BTC {btc * 100:+.1f} %" if btc is not None else "BTC sin datos"
    return f"{btc_txt}; las {len(cambios)} a partes iguales {fmean(cambios.values()) * 100:+.1f} %"


if __name__ == "__main__":
    sys.exit(main())
