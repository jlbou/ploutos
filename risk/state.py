"""Estado de riesgo: la foto que el motor necesita para decidir.

Todo lo que el motor de riesgo mira esta aqui dentro. No consulta bases de
datos, ni el exchange, ni el reloj del sistema: lo que hay en esta foto es todo
lo que sabe.

Ese aislamiento es lo que hace posible el test de propiedades del PRD: generar
miles de estados aleatorios y comprobar que los invariantes se cumplen en todos,
sin montar nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from core.clock import utc_day_start
from core.modes import Mode


class Side(Enum):
    """Solo largos: es spot sin apalancamiento (regla 1)."""

    LONG = "long"


@dataclass(frozen=True, slots=True)
class Position:
    """Una posicion abierta."""

    symbol: str
    qty: float
    entry_price: float
    stop_price: float
    target_price: float
    opened_at: datetime
    decision_id: str
    side: Side = Side.LONG

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError(f"cantidad no positiva: {self.qty}")
        if self.entry_price <= 0:
            raise ValueError(f"precio de entrada no positivo: {self.entry_price}")
        if self.stop_price >= self.entry_price:
            # En largo el stop va DEBAJO. Si no, no es un stop.
            raise ValueError(
                f"stop {self.stop_price} no esta por debajo de la entrada "
                f"{self.entry_price}"
            )

    def notional_at(self, price: float) -> float:
        return self.qty * price

    def risk_to_stop_usd(self, price: float | None = None) -> float:
        """Cuanto se pierde desde AQUI si salta el stop.

        Se mide desde el precio actual, no desde la entrada: una posicion en
        ganancia ya no arriesga lo que arriesgaba al abrirla, y la regla 8
        pregunta por el peor caso a partir de ahora.
        """
        reference = self.entry_price if price is None else price
        return max(0.0, (reference - self.stop_price) * self.qty)


@dataclass(frozen=True, slots=True)
class PendingEntry:
    """Una orden de entrada enviada y todavia sin llenar.

    Regla 4: CUENTA como posicion. Una orden limit sin ejecutar ocupa un hueco;
    si no se contase, al llenarse varias a la vez acabarias con 4 o 5 posiciones.
    """

    symbol: str
    qty: float
    limit_price: float
    stop_price: float
    created_at: datetime
    decision_id: str

    def notional(self) -> float:
        return self.qty * self.limit_price

    def risk_to_stop_usd(self) -> float:
        return max(0.0, (self.limit_price - self.stop_price) * self.qty)


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """Una operacion cerrada. Alimenta los limites diarios y los cooldowns."""

    symbol: str
    closed_at: datetime
    pnl_usd: float
    hit_stop: bool
    decision_id: str

    @property
    def is_loss(self) -> bool:
        return self.pnl_usd < 0


@dataclass(frozen=True, slots=True)
class RiskState:
    """La foto completa. El motor de riesgo no mira nada mas."""

    now: datetime
    equity_usd: float
    free_quote_usd: float
    mode: Mode
    positions: tuple[Position, ...] = ()
    pending_entries: tuple[PendingEntry, ...] = ()
    closed_today: tuple[ClosedTrade, ...] = ()
    recent_closed: tuple[ClosedTrade, ...] = ()
    # symbol -> mejor bid actual, para marcar posiciones a mercado (regla 6)
    marks: dict[str, float] = field(default_factory=dict)
    # (a, b) -> correlacion a 7 d, con a < b alfabeticamente (regla 15)
    correlations: dict[tuple[str, str], float] = field(default_factory=dict)
    # Desviacion de USDC respecto a la paridad, en % (regla 17). None =
    # DESCONOCIDA, y es el valor por defecto a proposito. Hasta el 22/09/2026
    # valia 0,0 ("medida y en paridad"), nadie la calculaba, y la regla 17 no
    # podia saltar nunca. Desconocida bloquea entradas: si alguien se olvida de
    # calcularla, el bot deja de abrir y se nota, en vez de operar a ciegas.
    usdc_deviation_pct: float | None = None
    # Lecturas consecutivas de equity <= suelo (regla 7)
    consecutive_floor_readings: int = 0
    # Banderas de evento por simbolo: hack, delisting... (informe seccion 3.4)
    event_flags: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # --- recuentos ---

    @property
    def occupied_slots(self) -> int:
        """Regla 4: abiertas MAS pendientes."""
        return len(self.positions) + len(self.pending_entries)

    @property
    def symbols_in_use(self) -> frozenset[str]:
        return frozenset(
            [p.symbol for p in self.positions]
            + [p.symbol for p in self.pending_entries]
        )

    @property
    def trades_today(self) -> int:
        """Regla 11. Cuentan las cerradas hoy mas lo que hay vivo ahora."""
        return len(self.closed_today) + self.occupied_slots

    @property
    def pnl_today_usd(self) -> float:
        """Regla 10. Solo realizado: las posiciones vivas aun no han decidido."""
        return sum(t.pnl_usd for t in self.closed_today)

    @property
    def exposure_usd(self) -> float:
        """Regla 15. Posiciones marcadas a mercado mas pendientes a su limite."""
        total = sum(
            p.notional_at(self.marks.get(p.symbol, p.entry_price))
            for p in self.positions
        )
        total += sum(p.notional() for p in self.pending_entries)
        return total

    def total_risk_to_stops_usd(self) -> float:
        """Regla 8: lo que se pierde si TODO salta a su stop."""
        total = sum(
            p.risk_to_stop_usd(self.marks.get(p.symbol))
            for p in self.positions
        )
        total += sum(p.risk_to_stop_usd() for p in self.pending_entries)
        return total

    def notional_at_stops_usd(self) -> float:
        """Regla 8: lo que se venderia si TODO saltara a su stop (sobre esto se paga la comision de salida)."""
        return (sum(p.qty * p.stop_price for p in self.positions)
                + sum(p.qty * p.stop_price for p in self.pending_entries))

    # --- tiempo ---

    def cooldown_until(self, symbol: str, hours: float) -> datetime | None:
        """Regla 14: hasta cuando esta el simbolo en cooldown tras un stop."""
        stops = [
            t for t in self.recent_closed if t.symbol == symbol and t.hit_stop
        ]
        if not stops:
            return None
        last = max(t.closed_at for t in stops)
        return last + timedelta(hours=hours)

    def consecutive_losses(self) -> int:
        """Regla 14: racha de perdidas contando hacia atras desde la ultima."""
        streak = 0
        for trade in sorted(self.recent_closed, key=lambda t: t.closed_at, reverse=True):
            if trade.is_loss:
                streak += 1
            else:
                break
        return streak

    def paused_until(self, count: int, hours: float) -> datetime | None:
        """Regla 14: pausa global tras `count` perdidas seguidas."""
        if self.consecutive_losses() < count:
            return None
        losses = sorted(
            (t for t in self.recent_closed if t.is_loss),
            key=lambda t: t.closed_at,
            reverse=True,
        )
        return losses[0].closed_at + timedelta(hours=hours)

    @property
    def day_start(self) -> datetime:
        """Las reglas 10 y 11 se resetean a las 00:00 UTC."""
        return utc_day_start(self.now)

    # --- correlacion ---

    def correlation(self, a: str, b: str) -> float | None:
        """La correlacion MEDIDA, o `None` si no se ha medido.

        `features/context.py` no registra una pareja sin muestra suficiente,
        y aqui no se rellena: una correlacion desconocida no es un 0,0.
        """
        if a == b:
            return 1.0
        key = (a, b) if a < b else (b, a)
        return self.correlations.get(key)

    def correlated_with(self, symbol: str, threshold: float) -> list[str]:
        """Simbolos ya en cartera que correlacionan mas de `threshold`...
        O CUYA CORRELACION NO SE HA MEDIDO.

        DECISION DEL PROPIETARIO (22/09/2026, opcion 2). Antes una pareja sin medir
        contaba como 0,0, o sea independiente: justo lo que `features/context.py`
        queria evitar al no registrarla. Ahora cuenta como correlacionada, que
        es la direccion segura de la regla 15: sin 7 dias de historia de 1 h,
        como mucho 2 posiciones a la vez. No bloquea el bot entero, pero no
        apila apuestas cuya relacion nadie ha comprobado.
        """
        out = []
        for other in sorted(self.symbols_in_use):
            if other == symbol:
                continue
            c = self.correlation(symbol, other)
            if c is None or c > threshold:
                out.append(other)
        return out

    def unmeasured_with(self, symbol: str) -> list[str]:
        """Los de cartera cuya correlacion con `symbol` no se ha medido."""
        return [
            other for other in sorted(self.symbols_in_use)
            if other != symbol and self.correlation(symbol, other) is None
        ]
