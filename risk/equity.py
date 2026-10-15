"""Calculo del equity (PRD regla 6).

    equity = USDC libre
           + sum(cantidad x mejor bid)
           - comisiones estimadas de salida

Tres detalles que el informe seccion 2.5 senyala como errores clasicos:

* **Mejor BID, no ultimo precio ni mid.** El bid es a lo que puedes vender de
  verdad. El ultimo precio puede ser de hace rato y el mid no existe.
* **Restando las comisiones de salida.** Ese dinero no es tuyo: lo pagaras al
  cerrar. Contarlo infla el equity justo cuando mas importa medirlo bien, que
  es cerca del suelo de 25 $.
* **Con datos del exchange, no de la base de datos local.** La base local puede
  ir retrasada; el suelo depende de medir bien.

El PRD regla 3 deja el equity sin termino en BTC: solo se opera contra USDC.
"""

from __future__ import annotations

from dataclasses import dataclass

from risk.state import Position


@dataclass(frozen=True, slots=True)
class EquityBreakdown:
    """El equity y sus piezas, para poder auditarlo en el panel."""

    free_quote_usd: float
    positions_value_usd: float
    exit_fees_usd: float
    stale_symbols: tuple[str, ...] = ()

    @property
    def equity_usd(self) -> float:
        return self.free_quote_usd + self.positions_value_usd - self.exit_fees_usd

    @property
    def is_reliable(self) -> bool:
        """Sin precio para alguna posicion, el numero no es de fiar."""
        return not self.stale_symbols

    def __str__(self) -> str:
        return (
            f"equity {self.equity_usd:.2f} $ = libre {self.free_quote_usd:.2f} "
            f"+ posiciones {self.positions_value_usd:.2f} "
            f"- comisiones de salida {self.exit_fees_usd:.2f}"
        )


def compute_equity(
    free_quote_usd: float,
    positions: tuple[Position, ...],
    best_bids: dict[str, float],
    taker_fee: float,
) -> EquityBreakdown:
    """Regla 6.

    `taker_fee` sin valor por defecto: antes llevaba 0,0015, la de ccxt, que no es
    la de la cuenta. Quien llama dice cual (la de settings.yaml).

    `taker_fee` porque una salida forzada (un stop) se ejecuta a mercado. Usar
    la comision maker aqui seria optimista justo en el peor momento.
    """
    value = 0.0
    fees = 0.0
    stale: list[str] = []

    for position in positions:
        bid = best_bids.get(position.symbol)
        if bid is None or bid <= 0:
            stale.append(position.symbol)
            continue
        notional = position.qty * bid
        value += notional
        fees += notional * taker_fee

    return EquityBreakdown(
        free_quote_usd=free_quote_usd,
        positions_value_usd=value,
        exit_fees_usd=fees,
        stale_symbols=tuple(sorted(stale)),
    )


def floor_breached(
    equity_usd: float, floor_usd: float, previous_readings: int
) -> tuple[bool, int]:
    """Regla 7: hacen falta DOS lecturas consecutivas por debajo del suelo.

    Dos y no una para que un pico raro de precio, o un libro momentaneamente
    vacio, no enclaven el bot por accidente. Enclavar es facil; salir requiere
    reset manual.

    Devuelve (dispara, nuevo_contador).
    """
    if equity_usd <= floor_usd:
        readings = previous_readings + 1
        return readings >= 2, readings
    return False, 0
