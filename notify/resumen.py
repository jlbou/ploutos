"""Los numeros del resumen diario, sacados de una base de papel. Solo LEE.

Todo sale de lo guardado (`paper_equity`, `paper_trades`, `paper_mode_changes`,
`ai_calls`), no de la memoria de un proceso: el resumen tiene que decir lo mismo
aunque el bucle se haya reiniciado a mitad del dia. Una base sin las tablas de
la IA (la del baseline) no tiene llamadas a Claude, y eso no es un error.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from core.config import Settings
from notify.messages import ResumenCartera
from portfolio.store import load_modes

# Filas del journal del analista que NO llamaron a Claude (no gastan presupuesto).
NO_LLAMO = ("skipped_budget", "skipped_quota", "skipped_stale")


def _ms(momento: datetime) -> int:
    return int(momento.timestamp() * 1000)


def resumen_desde_base(
    conn: sqlite3.Connection, cartera: str, dia: date, settings: Settings,
    *, capital_inicial: float | None = None,
) -> ResumenCartera:
    """El resumen de `cartera` para el dia UTC `dia`, con lo guardado hasta su final."""
    conn.row_factory = sqlite3.Row
    inicio = _ms(datetime.combine(dia, time(0), tzinfo=UTC))
    fin = _ms(datetime.combine(dia + timedelta(days=1), time(0), tzinfo=UTC))
    capital = capital_inicial if capital_inicial is not None else settings.capital.initial_capital_usd

    curva = [
        (int(r["ts_ms"]), float(r["equity_usd"]), int(r["positions"]))
        for r in conn.execute("SELECT * FROM paper_equity WHERE ts_ms < ? ORDER BY ts_ms", (fin,))
    ]
    equity = curva[-1][1] if curva else capital
    posiciones = curva[-1][2] if curva else 0
    antes = [e for ts, e, _p in curva if ts < inicio]
    al_empezar = antes[-1] if antes else capital

    pico, peor = capital, 0.0
    for _ts, e, _p in curva:
        pico = max(pico, e)
        peor = max(peor, (pico - e) / pico * 100 if pico > 0 else 0.0)

    hoy = [
        float(r["net_pnl_usd"])
        for r in conn.execute(
            "SELECT net_pnl_usd FROM paper_trades WHERE closed_ts_ms >= ? AND closed_ts_ms < ?",
            (inicio, fin),
        )
    ]

    llamadas: int | None = None
    presupuesto: int | None = None
    if cartera == "ai":
        presupuesto = settings.claude.max_calls_per_day
        try:
            llamadas = conn.execute(
                "SELECT COUNT(*) FROM ai_calls WHERE called_ms >= ? AND called_ms < ?"
                f" AND outcome NOT IN ({', '.join('?' * len(NO_LLAMO))})",
                (inicio, fin, *NO_LLAMO),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            llamadas = 0     # base sin 005_ai.sql: no ha llamado nunca

    try:
        modo = load_modes(conn).effective.name
    except sqlite3.OperationalError:
        modo = "NORMAL"      # base sin 004_modes.sql

    return ResumenCartera(
        cartera=cartera,
        equity_usd=equity,
        cambio_dia_usd=equity - al_empezar,
        drawdown_max_pct=peor,
        cerradas_hoy=len(hoy),
        resultado_hoy_usd=sum(hoy),
        posiciones=posiciones,
        max_posiciones=settings.risk.max_positions,
        modo=modo,
        ultima_vela_ms=curva[-1][0] if curva else None,
        llamadas_claude=llamadas,
        presupuesto_claude=presupuesto,
    )
