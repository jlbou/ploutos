"""Detector de datos obsoletos (informe seccion 1.3[1]).

Si una fuente deja de actualizar, la moneda pasa a STALE y no genera
candidatos. Si el exchange entero esta STALE, el bot entra en
CLOSE_ONLY_DEGRADED (PRD seccion 5).

Esto no es opcional: un bot que decide sobre precios de hace diez minutos cree
que esta operando el mercado y esta operando un recuerdo.

La clase es pura respecto al reloj (se le pasa `now_ms`), asi que se puede
testear sin esperar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.config import Settings
from core.events import EventBus, EventKind

# Nombres de fuente. `candles:<tf>` se construye al vuelo.
SOURCE_TICKER = "ticker"
SOURCE_ORDERBOOK = "orderbook"


def candle_source(timeframe: str) -> str:
    return f"candles:{timeframe}"


@dataclass
class SourceState:
    source: str
    symbol: str
    last_update_ms: int | None = None
    stale: bool = False
    updates: int = 0
    stale_events: int = 0


@dataclass
class StalenessMonitor:
    """Lleva la cuenta de cuando actualizo cada fuente y decide quien esta STALE."""

    settings: Settings
    bus: EventBus | None = None
    _states: dict[tuple[str, str], SourceState] = field(default_factory=dict)

    # --- umbrales ---

    def threshold_ms(self, source: str) -> float:
        cfg = self.settings.data.staleness
        if source == SOURCE_TICKER:
            return cfg.ticker_seconds * 1000
        if source == SOURCE_ORDERBOOK:
            return cfg.orderbook_seconds * 1000
        if source.startswith("candles:"):
            timeframe = source.split(":", 1)[1]
            if timeframe == "1m":
                return cfg.candle_1m_seconds * 1000
            # Para timeframes mayores, el umbral es el propio timeframe con
            # margen: una vela de 4 h no llega cada 90 s.
            from core.clock import timeframe_ms

            return timeframe_ms(timeframe) * 1.5
        raise ValueError(f"fuente desconocida: {source!r}")

    # --- registro ---

    def touch(self, source: str, symbol: str, now_ms: int) -> bool:
        """Marca que una fuente acaba de actualizar.

        Devuelve True si con esto SALE de STALE (util para notificar).
        """
        state = self._states.setdefault(
            (source, symbol), SourceState(source=source, symbol=symbol)
        )
        state.last_update_ms = now_ms
        state.updates += 1
        recovered = state.stale
        if recovered:
            state.stale = False
            if self.bus:
                self.bus.emit(
                    EventKind.SOURCE_RECOVERED, symbol=symbol, source=source
                )
        return recovered

    def check(self, now_ms: int) -> list[SourceState]:
        """Revisa todas las fuentes. Devuelve las que ACABAN de ponerse STALE."""
        newly_stale: list[SourceState] = []
        for state in self._states.values():
            if state.stale:
                continue
            threshold = self.threshold_ms(state.source)
            if state.last_update_ms is None:
                continue
            age = now_ms - state.last_update_ms
            if age > threshold:
                state.stale = True
                state.stale_events += 1
                newly_stale.append(state)
                if self.bus:
                    self.bus.emit(
                        EventKind.SOURCE_STALE,
                        symbol=state.symbol,
                        source=state.source,
                        age_ms=age,
                        threshold_ms=threshold,
                    )
        return newly_stale

    # --- consultas ---

    def is_stale(self, source: str, symbol: str) -> bool:
        state = self._states.get((source, symbol))
        return True if state is None else state.stale

    def symbol_is_stale(self, symbol: str) -> bool:
        """Una moneda esta STALE si CUALQUIERA de sus fuentes lo esta.

        Conservador a proposito: si no sabemos el libro, no sabemos el spread,
        y sin spread no se puede evaluar la regla 16.
        """
        states = [s for s in self._states.values() if s.symbol == symbol]
        if not states:
            return True
        return any(s.stale for s in states)

    def healthy_symbols(self) -> set[str]:
        return {
            symbol
            for symbol in self.settings.whitelist
            if not self.symbol_is_stale(symbol)
        }

    def stale_symbols(self) -> set[str]:
        return set(self.settings.whitelist) - self.healthy_symbols()

    def exchange_is_degraded(self, threshold_fraction: float = 0.5) -> bool:
        """True si tantas monedas estan STALE que el problema es el exchange.

        Con la mitad o mas de la whitelist caida, no es un par raro: es la
        conexion. Eso dispara CLOSE_ONLY_DEGRADED.
        """
        total = len(self.settings.whitelist)
        if total == 0:
            return True
        return len(self.stale_symbols()) / total >= threshold_fraction

    def states(self) -> list[SourceState]:
        return list(self._states.values())

    def todo_fresco(self, simbolos) -> bool:
        """Para el latido del vigilante externo (24/09/2026): velas de 1 m frescas de
        TODOS los simbolos y ninguna fuente STALE. Mas estricto que "el proceso esta
        vivo": una ingesta viva que no recibe datos no tiene que latir."""
        estados = self.states()
        vivas = {
            s.symbol for s in estados
            if s.source == "candles:1m" and s.last_update_ms is not None and not s.stale
        }
        return bool(estados) and set(simbolos) <= vivas and not any(s.stale for s in estados)
