"""Tiempo UTC y deteccion de desfase de reloj.

Todo en Ploutos usa UTC con timezone explicita (PRD seccion 13: trazabilidad).
Nunca `datetime.now()` sin tz, nunca hora local.

El desfase importa porque las firmas de la API llevan timestamp y el exchange
rechaza peticiones desfasadas (informe seccion 1.3[1]). En el VPS lo corrige
`chrony`; aqui solo lo detectamos y avisamos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# Duracion de cada timeframe en milisegundos.
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def utcnow() -> datetime:
    """Ahora, en UTC y con timezone. Unica fuente de 'ahora' del proyecto."""
    return datetime.now(UTC)


def utcnow_ms() -> int:
    """Ahora en milisegundos desde epoch (el formato que usa ccxt)."""
    return int(utcnow().timestamp() * 1000)


def to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("datetime sin timezone: en Ploutos todo es UTC explicito")
    return int(dt.timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def timeframe_ms(timeframe: str) -> int:
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError:
        raise ValueError(f"timeframe desconocido: {timeframe!r}") from None


def candle_is_closed(ts_open_ms: int, timeframe: str, now_ms: int | None = None) -> bool:
    """True si la vela que abrio en `ts_open_ms` ya ha cerrado.

    Informe seccion 1.3[1]: los indicadores solo usan velas cerradas. Usar la
    vela en curso es la causa mas comun de look-ahead bias.
    """
    now = utcnow_ms() if now_ms is None else now_ms
    return now >= ts_open_ms + timeframe_ms(timeframe)


def floor_to_timeframe(ts_ms: int, timeframe: str) -> int:
    """Baja un timestamp al inicio de su vela."""
    size = timeframe_ms(timeframe)
    return (ts_ms // size) * size


def utc_day_start(dt: datetime | None = None) -> datetime:
    """Inicio del dia UTC. Las reglas 10 y 11 se resetean a las 00:00 UTC."""
    d = dt or utcnow()
    return d.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def next_utc_midnight(dt: datetime | None = None) -> datetime:
    """Proxima medianoche UTC: cuando expira CLOSE_ONLY_DAILY (regla 10)."""
    return utc_day_start(dt) + timedelta(days=1)


@dataclass(frozen=True, slots=True)
class SkewReading:
    """Una medida del desfase entre nuestro reloj y el del exchange."""

    local_ms: int
    remote_ms: int
    round_trip_ms: int

    @property
    def skew_seconds(self) -> float:
        """Desfase estimado, corrigiendo la mitad de la latencia de ida y vuelta."""
        return (self.local_ms - self.remote_ms - self.round_trip_ms / 2) / 1000.0

    def is_acceptable(self, max_skew_seconds: float) -> bool:
        return abs(self.skew_seconds) <= max_skew_seconds
