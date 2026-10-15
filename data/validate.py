"""Validacion de datos de mercado (informe seccion 2.4, "datos erroneos").

Una vela incoherente que entra en la base de datos contamina todos los
indicadores que se calculen despues, y el bot decide sobre una realidad que no
existe. Se descarta en la puerta y se registra el motivo.

Todo es puro: entra un dato, sale un veredicto. Sin I/O, facil de testear.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.clock import floor_to_timeframe, timeframe_ms, utcnow_ms
from data.store.repos import Candle

# Margen de tolerancia para timestamps en el futuro.
#
# Tiene que absorber el desfase de reloj REAL, no solo la latencia de red: si
# nuestro reloj va atrasado, una vela recien abierta por el exchange nos llega
# con un timestamp "del futuro" y rechazarla nos dejaria sin datos.
# (Comprobado el 22/09/2026: la maquina de desarrollo iba 10 s atrasada.)
#
# 60 s es generoso para el desfase plausible y sigue siendo estrecho para datos
# corruptos. Detectar el desfase en si NO es tarea de aqui: eso lo hace
# `core.clock.SkewReading`, que avisa a partir de 2 s.
FUTURE_TOLERANCE_MS = 60_000

# Un precio que se sale de este factor respecto a la referencia reciente se
# considera atipico. Las criptos se mueven mucho, pero no x2 en una vela de 1 m.
OUTLIER_FACTOR = 5.0


@dataclass(frozen=True, slots=True)
class Validation:
    ok: bool
    reason: str | None = None

    @classmethod
    def valid(cls) -> Validation:
        return cls(True)

    @classmethod
    def invalid(cls, reason: str) -> Validation:
        return cls(False, reason)


def validate_candle(
    candle: Candle,
    now_ms: int | None = None,
    reference_price: float | None = None,
) -> Validation:
    """Comprueba que una vela es internamente coherente y plausible.

    `reference_price` es el ultimo cierre conocido de ese simbolo, si lo hay.
    Sirve para detectar precios atipicos; si no se pasa, ese control se omite.
    """
    now = utcnow_ms() if now_ms is None else now_ms

    prices = (candle.open, candle.high, candle.low, candle.close)

    if any(p != p for p in prices):  # NaN
        return Validation.invalid("precio NaN")
    if any(p <= 0 for p in prices):
        return Validation.invalid(f"precio no positivo: {prices}")
    if candle.volume != candle.volume or candle.volume < 0:
        return Validation.invalid(f"volumen invalido: {candle.volume}")

    if candle.high < candle.low:
        return Validation.invalid(f"high {candle.high} < low {candle.low}")
    if candle.high < max(candle.open, candle.close):
        return Validation.invalid(
            f"high {candle.high} por debajo de open/close "
            f"({candle.open}, {candle.close})"
        )
    if candle.low > min(candle.open, candle.close):
        return Validation.invalid(
            f"low {candle.low} por encima de open/close "
            f"({candle.open}, {candle.close})"
        )

    if candle.ts_open_ms <= 0:
        return Validation.invalid(f"timestamp invalido: {candle.ts_open_ms}")
    if candle.ts_open_ms > now + FUTURE_TOLERANCE_MS:
        return Validation.invalid(
            f"timestamp en el futuro: {candle.ts_open_ms} > {now}"
        )

    try:
        step = timeframe_ms(candle.timeframe)
    except ValueError as exc:
        return Validation.invalid(str(exc))
    if candle.ts_open_ms % step != 0:
        aligned = floor_to_timeframe(candle.ts_open_ms, candle.timeframe)
        return Validation.invalid(
            f"timestamp {candle.ts_open_ms} no alineado a {candle.timeframe} "
            f"(deberia ser {aligned})"
        )

    if reference_price is not None and reference_price > 0:
        ratio = max(candle.high / reference_price, reference_price / max(candle.low, 1e-12))
        if ratio > OUTLIER_FACTOR:
            return Validation.invalid(
                f"precio atipico: rango [{candle.low}, {candle.high}] frente a "
                f"referencia {reference_price} (factor {ratio:.1f}x)"
            )

    return Validation.valid()


def validate_orderbook(
    bids: list[tuple[float, float]], asks: list[tuple[float, float]]
) -> Validation:
    """Comprueba que un libro de ordenes tiene sentido."""
    if not bids or not asks:
        return Validation.invalid("libro vacio en algun lado")

    best_bid, best_ask = bids[0][0], asks[0][0]
    if best_bid <= 0 or best_ask <= 0:
        return Validation.invalid(f"precios no positivos: bid {best_bid}, ask {best_ask}")
    if best_bid >= best_ask:
        # Un libro cruzado significa datos corruptos o desincronizados.
        return Validation.invalid(f"libro cruzado: bid {best_bid} >= ask {best_ask}")

    if any(p <= 0 or q < 0 for p, q in bids + asks):
        return Validation.invalid("nivel con precio o cantidad invalidos")

    if any(a[0] < b[0] for a, b in zip(bids, bids[1:])):
        return Validation.invalid("bids sin ordenar de mayor a menor")
    if any(a[0] > b[0] for a, b in zip(asks, asks[1:])):
        return Validation.invalid("asks sin ordenar de menor a mayor")

    return Validation.valid()
