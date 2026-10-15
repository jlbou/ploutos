"""Las reglas duras otra vez, con el estado del DEMO, antes de copiar una orden (fase 4, pieza c; decision 2 del 02/10).

PURO: construye la foto del motor de riesgo (`risk.state.RiskState`) con lo que tiene el demo (equity de la regla 6
con datos del exchange y saldo virtual, posiciones, entradas, cierres del dia, modo del ejecutor) y el mercado de la
ingesta (bids, correlaciones, paridad de USDC, flags de noticias, spread), y pasa el motor ENTERO (`risk.engine`) sobre
la orden de papel. No toca `risk/`: lo usa.

La cantidad (decisiones 1 y 2 del 02/10): la MISMA que la orden de papel, salvo que el motor, con el equity del demo,
apruebe MENOS (regla 12); entonces manda la regla: `min(papel, motor)`, al lote hacia abajo. Las dos carteras empiezan
con 50 $ y casi siempre sale la del papel.

Una lectura de equity NO fiable (falta el bid de una moneda que tenemos) no aprueba nada.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from core.config import Settings
from core.modes import Mode
from execution.espejo import OrdenPapel
from risk.engine import evaluate_with_limits
from risk.equity import EquityBreakdown
from risk.state import ClosedTrade, PendingEntry, Position, RiskState
from risk.types import EntryRequest, Instrument, Verdict

SLIDER = 3            # bloqueado en el nivel 3 hasta cerrar la fase 6 (decision del panel, 25/09)
MEMORIA = 40          # las ultimas cerradas que mira la regla 14 (portfolio.loop.TradingLoop.RECENT_MEMORY)


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class PosicionDemo:
    decision_id: str
    simbolo: str
    cantidad: float
    entrada: float
    stop: float
    objetivo: float
    abierta_ms: int


@dataclass(frozen=True, slots=True)
class EntradaDemo:
    decision_id: str
    simbolo: str
    cantidad: float
    limite: float
    stop: float
    creada_ms: int


@dataclass(frozen=True, slots=True)
class CierreDemo:
    decision_id: str
    simbolo: str
    cerrada_ms: int
    pnl_usd: float
    por_stop: bool


@dataclass(frozen=True, slots=True)
class Mercado:
    """De la ingesta y de los servicios de mercado, como los usa la cartera de papel."""

    bids: Mapping[str, float]
    correlaciones: Mapping[tuple[str, str], float]
    usdc_desviacion_pct: float | None
    flags: Mapping[str, tuple[str, ...]]


def estado(*, ahora_ms: int, equity: EquityBreakdown, modo: Mode, posiciones: Iterable[PosicionDemo],
           entradas: Iterable[EntradaDemo], cierres: Iterable[CierreDemo], mercado: Mercado) -> RiskState:
    posiciones, entradas = tuple(posiciones), tuple(entradas)
    ahora = _dt(ahora_ms)
    registros = sorted((ClosedTrade(c.simbolo, _dt(c.cerrada_ms), c.pnl_usd, c.por_stop, c.decision_id)
                        for c in cierres), key=lambda t: t.closed_at)
    usado = sum(p.cantidad * p.entrada for p in posiciones) + sum(e.cantidad * e.limite for e in entradas)
    return RiskState(
        now=ahora,
        equity_usd=equity.equity_usd,
        free_quote_usd=max(0.0, equity.equity_usd - usado),
        mode=modo,
        # Una entrada llenada POR DEBAJO de su stop (un hueco mientras esperaba) no es una posicion que `Position`
        # acepte, y haria fallar cada copia: cuenta con riesgo cero hasta el stop (revision del 03/10).
        positions=tuple(Position(p.simbolo, p.cantidad, p.entrada, min(p.stop, p.entrada * (1 - 1e-9)), p.objetivo,
                                 _dt(p.abierta_ms), p.decision_id) for p in posiciones),
        pending_entries=tuple(PendingEntry(e.simbolo, e.cantidad, e.limite, e.stop, _dt(e.creada_ms), e.decision_id)
                              for e in entradas),
        closed_today=tuple(r for r in registros if r.closed_at.date() == ahora.date()),
        recent_closed=tuple(registros[-MEMORIA:]),
        marks=dict(mercado.bids),
        correlations=dict(mercado.correlaciones),
        usdc_deviation_pct=mercado.usdc_desviacion_pct,
        event_flags=dict(mercado.flags),
    )


@dataclass(frozen=True, slots=True)
class Aprobacion:
    enviar: bool
    cantidad: float
    motivo: str
    veredicto: Verdict | None = None


def aprobar(orden: OrdenPapel, foto: RiskState, equity: EquityBreakdown, *, instrumento: Instrument,
            spread_pct: float, settings: Settings) -> Aprobacion:
    """Si se copia la orden de papel, y con que cantidad."""
    if not equity.is_reliable:
        return Aprobacion(False, 0.0, f"equity no fiable (sin precio de {', '.join(equity.stale_symbols)})")
    # Las noticias, otra vez JUSTO antes de enviar (revision del 15/10/2026): el filtro de la cartera de papel mira las
    # flags al cierre de su vela, y ninguna de las 19 reglas las mira; una flag puesta entre esa vela y la copia
    # (un deslistado anunciado medio minuto despues) dejaba copiar la orden.
    if foto.event_flags.get(orden.simbolo):
        return Aprobacion(False, 0.0, f"flag de noticias en {orden.simbolo}: {', '.join(foto.event_flags[orden.simbolo])}")
    peticion = EntryRequest(symbol=orden.simbolo, entry_price=orden.entrada, stop_price=orden.stop,
                            target_price=orden.objetivo, setup=orden.setup, instrument=instrumento,
                            decision_id=orden.decision_id, spread_pct=spread_pct)
    v = evaluate_with_limits(peticion, foto, settings, slider_level=SLIDER)
    if not v.approved:
        return Aprobacion(False, 0.0, f"el motor con el estado del demo: {v.reason()}", v)
    lote = instrumento.lot_size
    # Redondeado a los decimales del lote: 6178 x 0,000001 da 0,0061779999... y ccxt TRUNCA a 0,006177, un lote
    # menos que el papel (visto el 03/10 en la adopcion de ETH).
    # El 1e-9 solo sube a un lote entero lo que ya lo era salvo el ruido del float: el exceso sobre lo aprobado es
    # como mucho 1e-9 lotes (revision del 15/10, hallazgo 9; hay test). Un tope estricto haria volver el error del 03/10.
    cantidad = round(math.floor(min(orden.cantidad, v.qty) / lote + 1e-9) * lote, 12)
    if cantidad < instrumento.min_amount or cantidad <= 0:
        return Aprobacion(False, 0.0, f"cantidad {cantidad:g} por debajo del minimo {instrumento.min_amount:g}", v)
    menos = "" if cantidad >= orden.cantidad - lote / 2 else f" (el motor del demo aprueba {v.qty:g}, no {orden.cantidad:g})"
    return Aprobacion(True, cantidad, "aprobada" + menos, v)
