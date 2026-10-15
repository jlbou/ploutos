"""Prueba en seco del analista: la cadena entera con candidatos REALES, sin bucle.

Autorizada por el propietario el 22/09/2026, antes de integrar nada (plan de la fase 3):
    historia real -> bucle de papel -> candidatos -> prompt -> claude -p -> parser

Mide lo que el criterio de la fase 3 va a pedir, con NUESTRO prompt y no con uno de
prueba: cuantas salidas son invalidas, latencia, tokens, coste equivalente, y que
decide la IA frente a lo que decidio el baseline en la misma vela.

NO toca nada que este corriendo: lee la base LOCAL, simula en memoria y guarda el
resultado en `var/dry_run/`. Gasta cuota de Claude: usa el presupuesto REAL de la
regla 18 (`ai/budget.py`, guardado en `var/dry_run/budget.db`), asi que como mucho
8 llamadas por ventana de 5 h aunque se lance dos veces.

Entorno limpio y configuracion propia (`ai/invoke.py`): el CLI no usa la sesion
del portatil, como en el VPS.

    .venv/Scripts/python.exe scripts/dry_run_analyst.py            # 8 llamadas
    .venv/Scripts/python.exe scripts/dry_run_analyst.py --calls 3
    .venv/Scripts/python.exe scripts/dry_run_analyst.py --vela "25/08 16:00" --vela "25/08 08:00*4"

`--vela` elige velas concretas, y `*N` repite la MISMA entrada N veces: sirve para
medir cuanto cambia la respuesta de Claude sin que cambie nada de lo que ve.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sqlite3
import statistics
import sys
import time
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai.budget import CallBudget  # noqa: E402
from ai.invoke import call_analyst  # noqa: E402
from ai.prompt import LimitsView, PositionView, build_input  # noqa: E402
from core.secrets import Secrets  # noqa: E402
from risk.limits import Limits  # noqa: E402

SALIDA = REPO / "var" / "dry_run"
# Precios de USDC medidos el 22/09/2026: la prueba no va a la red por esto.
USDC_MIDS = {"USDC/USDT": 0.99996, "USDT/USD": 0.99989, "BTC/USD": 86224.05, "BTC/USDC": 86227.25}


def cargar_runner(main_db: Path, paper_db: Path):
    spec = importlib.util.spec_from_file_location("run_paper", REPO / "scripts" / "run_paper.py")
    rp = importlib.util.module_from_spec(spec)
    sys.modules["run_paper"] = rp
    spec.loader.exec_module(rp)
    paper_db.unlink(missing_ok=True)
    r = rp.PaperRunner(Namespace(tf="4h", equity=50.0, slider=3,
                                 main_db=str(main_db), paper_db=str(paper_db)))
    r.usdc_mids = lambda: dict(USDC_MIDS)
    return r


def recoger_velas(runner) -> list[dict]:
    """Pasa el bucle real por la historia y guarda cada vela con candidatos."""
    velas: list[dict] = []
    original = runner.loop.step

    def espia(ts_ms, market, bars, hourly, *, usdc_deviation_pct):
        r = original(ts_ms, market, bars, hourly, usdc_deviation_pct=usdc_deviation_pct)
        if not r.candidates:
            return r
        # La foto es la del MOMENTO DE DECIDIR: despues de que la vela haya llenado,
        # cerrado o caducado lo que tocara, y antes de que el baseline envie nada.
        # Se reconstruye despues del paso quitando lo que el baseline acaba de enviar.
        # (La primera version la tomaba ANTES del paso: el 25/08 16:00 el analista
        # vio 0 huecos libres cuando en esa misma vela se habia cerrado una posicion.)
        enviadas = {c.candidate.cid for c in r.submitted}
        pendientes = [o for o in runner.broker.pending if o.decision_id not in enviadas]
        posiciones = list(runner.broker.positions.values())
        ocupados = len(posiciones) + len(pendientes)
        usado = sum(p.qty * p.entry_price for p in posiciones) + sum(o.notional for o in pendientes)
        lim = Limits.for_state(runner.settings, r.equity_usd, runner.slider)
        hoy, _ = runner.loop.closed_trades(datetime.fromtimestamp(ts_ms / 1000, tz=UTC))
        perdida = -sum(t.pnl_usd for t in hoy)
        velas.append({
            "ts_ms": ts_ms,
            "candidates": list(r.candidates),
            "baseline": sorted(enviadas),
            "equity": r.equity_usd,
            "free_quote": max(0.0, r.equity_usd - usado),
            "positions": [
                PositionView(p.decision_id, p.symbol, p.entry_price,
                             bars[p.symbol].close if p.symbol in bars else p.entry_price,
                             p.stop_price, p.target_price,
                             datetime.fromtimestamp(p.opened_ts_ms / 1000, tz=UTC))
                for p in posiciones
            ],
            "limits": LimitsView(
                max_positions=lim.max_positions,
                slots_free=max(0, lim.max_positions - ocupados),
                risk_per_trade_usd=lim.risk_per_trade_usd,
                daily_loss_left_usd=max(0.0, lim.daily_loss_limit_usd - perdida),
                trades_left_today=max(0, lim.max_trades_per_day - len(hoy) - ocupados),
            ),
            "mode": str(runner.loop.modes.effective),
        })
        return r

    runner.loop.step = espia
    stamps = runner._closed_bars_after(None)
    runner.cursor = stamps[60]           # calentamiento del regimen, como el historico
    runner.catch_up()
    return velas


def elegir(velas: list[dict], n: int) -> list[dict]:
    """Las velas mas interesantes: primero las que obligan a ELEGIR (varios
    candidatos), repartidas en el tiempo."""
    varias = [v for v in velas if len(v["candidates"]) >= 2]
    una = [v for v in velas if len(v["candidates"]) == 1]
    pool = varias + una
    if len(pool) <= n:
        return pool
    paso = len(pool) / n
    return sorted((pool[int(i * paso)] for i in range(n)), key=lambda v: v["ts_ms"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba en seco del analista")
    parser.add_argument("--calls", type=int, default=8)
    parser.add_argument("--main-db", default=str(REPO / "var" / "ploutos.db"))
    parser.add_argument("--vela", action="append", default=[],
                        help='"DD/MM HH:MM" o "DD/MM HH:MM*N" (N repeticiones de la misma entrada)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    token = Secrets().claude_code_oauth_token
    if token is None:
        print("falta CLAUDE_CODE_OAUTH_TOKEN en el .env")
        return 1
    SALIDA.mkdir(parents=True, exist_ok=True)

    runner = cargar_runner(Path(args.main_db), SALIDA / "paper.db")
    velas = recoger_velas(runner)
    if args.vela:
        por_nombre = {datetime.fromtimestamp(v["ts_ms"] / 1000, tz=UTC).strftime("%d/%m %H:%M"): v
                      for v in velas}
        elegidas = []
        for pedido in args.vela:
            nombre, _, veces = pedido.partition("*")
            if nombre.strip() not in por_nombre:
                print(f"no hay candidatos en la vela {nombre!r}; hay: {sorted(por_nombre)}")
                return 1
            elegidas += [por_nombre[nombre.strip()]] * int(veces or 1)
    else:
        elegidas = elegir(velas, args.calls)
    print(f"{len(velas)} velas con candidatos en la historia; se prueban {len(elegidas)}")

    budget = CallBudget.from_settings(sqlite3.connect(SALIDA / "budget.db"), runner.settings)
    resultados = []
    for v in elegidas:
        ahora = int(time.time() * 1000)
        permiso = budget.try_acquire(ahora, kind="dry_run")
        if not permiso.allowed:
            print(f"PARADO por la regla 18: {permiso.reason}")
            break
        entrada = build_input(
            now=datetime.fromtimestamp(v["ts_ms"] / 1000, tz=UTC), mode=v["mode"],
            equity_usd=v["equity"], free_quote_usd=v["free_quote"],
            positions=v["positions"], limits=v["limits"], candidates=v["candidates"],
        )
        llamada = call_analyst(entrada, token=token.get_secret_value().strip(),
                               config_dir=SALIDA / "claude_home",
                               model=runner.settings.claude.model,
                               timeout_s=runner.settings.claude.timeout_seconds)
        ia = [(o.cid, o.size_multiplier, o.confidence) for o in llamada.parsed.opens]
        fila = {
            "vela": datetime.fromtimestamp(v["ts_ms"] / 1000, tz=UTC).strftime("%d/%m %H:%M"),
            "candidatos": [c.cid for c in v["candidates"]],
            "baseline": v["baseline"],
            "ia_open": ia,
            "outcome": llamada.outcome.value,
            "valida": llamada.parsed.ok,
            # Si la llamada fue bien pero la salida no vale, el motivo es del PARSER.
            "detalle": llamada.parsed.reason if llamada.outcome.value == "ok" else llamada.detail,
            "structured": llamada.structured,
            "result_text": llamada.result_text,
            "latencia_s": round(llamada.latency_s, 1),
            "tokens_salida": llamada.output_tokens,
            "cache_creada": llamada.cache_created,
            "coste_equiv": llamada.cost_usd_equiv,
            "turnos": llamada.num_turns,
            "market_read": llamada.parsed.market_read,
        }
        resultados.append(fila)
        print(f"  {fila['vela']}  {len(fila['candidatos'])} cand.  baseline {len(fila['baseline'])}  "
              f"IA {len(ia)} open  {fila['outcome']}/{'OK' if fila['valida'] else 'INVALIDA'}  "
              f"{fila['latencia_s']} s  {fila['coste_equiv']}")

    if not resultados:
        return 1
    validas = [r for r in resultados if r["valida"]]
    lat = [r["latencia_s"] for r in resultados]
    costes = [r["coste_equiv"] for r in resultados if r["coste_equiv"] is not None]
    coincide = sum(set(c for c, _m, _p in r["ia_open"]) == set(r["baseline"]) for r in validas)
    reduce = sum(1 for r in validas for _c, m, _p in r["ia_open"] if m < 1.0)
    print()
    print(f"validas            {len(validas)}/{len(resultados)}")
    print(f"latencia           mediana {statistics.median(lat):.1f} s, max {max(lat):.1f} s (timeout 90 s)")
    if costes:
        print(f"coste equivalente  medio {statistics.fmean(costes):.4f} $, total {sum(costes):.4f} $")
    print(f"misma eleccion que el baseline  {coincide}/{len(validas)}")
    # La misma vela varias veces: cuantas elecciones distintas salen.
    por_vela: dict[str, list] = {}
    for r in validas:
        por_vela.setdefault(r["vela"], []).append(r)
    for vela, filas in por_vela.items():
        if len(filas) < 2:
            continue
        elecciones = [tuple(sorted(c.split("-")[-2] for c, _m, _p in f["ia_open"])) for f in filas]
        distintas = {e: elecciones.count(e) for e in elecciones}
        print(f"misma entrada {vela}, {len(filas)} veces -> {len(distintas)} elecciones distintas: "
              + ", ".join(f"{'+'.join(e) or 'ninguna'} x{n}" for e, n in distintas.items()))
    print(f"aperturas con el tamanyo reducido  {reduce}")
    destino = SALIDA / f"analyst-{datetime.now(UTC):%Y%m%dT%H%M}.json"
    destino.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndetalle en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
