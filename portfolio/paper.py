"""Ejecucion en papel contra el libro real (PRD seccion 12, fase 2).

AQUI ES DONDE LOS BACKTESTS SE MIENTEN A SI MISMOS. Un simulador optimista
produce curvas preciosas y decisiones caras. Cada suposicion de este modulo
esta elegida para equivocarse en contra, y esta escrita para que se pueda
discutir una por una.

LAS SIETE SUPOSICIONES, Y POR QUE CADA UNA VA EN CONTRA:

1. **Si el stop y el objetivo caen en la MISMA vela, gana el stop.** Con datos
   OHLC no hay forma de saber cual toco primero. Suponer el objetivo infla los
   resultados de forma brutal y es la trampa mas comun del backtesting casero.
   Ante la duda, la version mala.

2. **La entrada limit se llena a SU precio, nunca mejor.** Si el mercado abre
   por debajo del limite, en la realidad te llenarian mas barato. Aqui no: se
   llena al precio pedido. No regalamos mejoras de precio.

3. **El stop SI sufre los huecos.** Si la vela abre por debajo del stop, se
   sale al precio de apertura, no al del stop. Es asimetrico a proposito
   respecto al punto 2: el hueco malo cuenta y el bueno no, porque asi es como
   duele en vivo. Esto es lo que hace visible el riesgo de hueco de los setups
   con stop estrecho.

4. **El objetivo NO se beneficia de los huecos.** Si la vela abre por encima
   del objetivo, se sale al objetivo y no a la apertura.

5. **Una entrada puede llenarse y saltar el stop en la MISMA vela.** Pasa en
   vivo constantemente: te llenan en la minima y el precio sigue.

6. **Comisiones por pata, leidas del instrumento.** Entrada limit = maker.
   Salida por objetivo = limit = maker. Salida por stop = cruza el libro =
   **taker**. El modelo de costes de `strategy/costs.py` supone taker en la
   salida SIEMPRE, asi que es deliberadamente mas pesimista que esto: sirve
   para FILTRAR antes de operar, mientras que aqui se apunta lo que de verdad
   costaria. Que el filtro sea mas duro que la realidad es la direccion segura.

7. **En la vela que llena la entrada, el objetivo NO cuenta** (revision del
   15/10/2026). Dentro de la vela no se sabe el orden: el maximo pudo pasar
   ANTES de que el precio bajara al limite. Con el stop se gana el peor caso
   (punto 5); con el objetivo, tambien: cuenta desde la vela siguiente. Hasta
   entonces el papel lo cobraba, y eso inflaba el R de la fase 6 y de los
   estudios de setups hechos con este simulador.

LO QUE ESTE MODULO NO HACE, y no es un olvido:

  * **No decide nada.** Recibe veredictos ya aprobados por `risk/engine.py`.
  * **No mueve stops ni aplica time-stop.** Eso es el gestor de posiciones del
    informe seccion 1.3[9], y no toca en esta fase.
  * **No modela la seleccion adversa de la pata maker** (que te llenen la
    compra justo cuando el precio va a seguir bajando). No hay forma honesta de
    estimarla sin datos propios; la fase 6 la medira comparando el precio de
    llenado con el de referencia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from risk.types import Instrument

# Velas que una orden de entrada espera antes de cancelarse. El candidato
# nace de una vela concreta: si dos velas despues el precio no ha vuelto, la
# lectura que lo genero ya no describe el mercado y perseguirla seria operar
# una senyal caducada.
ENTRY_BARS_TO_LIVE = 2


class OrderState(Enum):
    PENDING = "pending"
    FILLED = "filled"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


class ExitReason(Enum):
    STOP = "stop"
    TARGET = "target"
    CANCELLED = "cancelled"
    # Salida a mercado por una flag CRITICA de noticias (deslistado, hackeo, suspension): PRD 5,
    # decision 2 del propietario del 25/09. Al cierre de la vela, como taker.
    NEWS = "news"
    # "Cerrar todo" desde el panel (el propietario, 26/09): a mercado, al cierre de la vela, como taker.
    MANUAL = "manual"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Bar:
    """Una vela cerrada. El simulador solo avanza con velas cerradas."""

    ts_open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Bar:
        return cls(
            ts_open_ms=int(row["ts_open_ms"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0)),
        )


@dataclass(slots=True)
class PaperOrder:
    """Una orden de entrada limit, esperando a que el precio venga."""

    decision_id: str
    symbol: str
    qty: float
    limit_price: float
    stop_price: float
    target_price: float
    setup: str
    created_ts_ms: int
    state: OrderState = OrderState.PENDING
    bars_waited: int = 0

    @property
    def notional(self) -> float:
        return self.qty * self.limit_price


@dataclass(slots=True)
class PaperPosition:
    """Una posicion abierta en papel, con su OCO ya puesta (regla 13)."""

    decision_id: str
    symbol: str
    qty: float
    entry_price: float
    stop_price: float
    target_price: float
    setup: str
    opened_ts_ms: int
    entry_fee_usd: float
    # Para MAE/MFE (informe seccion 1.9: metricas honestas).
    worst_price: float = 0.0
    best_price: float = 0.0

    def __post_init__(self) -> None:
        if self.worst_price == 0.0:
            self.worst_price = self.entry_price
        if self.best_price == 0.0:
            self.best_price = self.entry_price

    @property
    def risk_usd(self) -> float:
        """Lo que se pierde si salta el stop, sin contar comisiones."""
        return (self.entry_price - self.stop_price) * self.qty


@dataclass(frozen=True, slots=True)
class PaperTrade:
    """Una operacion cerrada. Es la unidad de medida de la fase 6."""

    decision_id: str
    symbol: str
    setup: str
    qty: float
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    opened_ts_ms: int
    closed_ts_ms: int
    reason: ExitReason
    entry_fee_usd: float
    exit_fee_usd: float
    exit_was_maker: bool
    mae_pct: float
    mfe_pct: float

    @property
    def gross_pnl_usd(self) -> float:
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def fees_usd(self) -> float:
        return self.entry_fee_usd + self.exit_fee_usd

    @property
    def net_pnl_usd(self) -> float:
        return self.gross_pnl_usd - self.fees_usd

    @property
    def planned_risk_usd(self) -> float:
        return (self.entry_price - self.stop_price) * self.qty

    @property
    def r_multiple(self) -> float:
        """Resultado en R: cuantas veces el riesgo planificado se gano o perdio.

        Es la metrica que pide el informe seccion 1.9 y la unica que permite
        comparar operaciones de tamanyos distintos. Se mide NETA de comisiones,
        porque una operacion que gana 1R bruto y 0,2R neto no es una operacion
        que gana 1R.
        """
        risk = self.planned_risk_usd
        if risk <= 0:
            return 0.0
        return self.net_pnl_usd / risk

    @property
    def hit_stop(self) -> bool:
        return self.reason is ExitReason.STOP

    def __str__(self) -> str:
        return (
            f"{self.symbol} {self.setup} [{self.reason}] "
            f"{self.net_pnl_usd:+.3f} $ = {self.r_multiple:+.2f}R "
            f"(bruto {self.gross_pnl_usd:+.3f} $, comisiones "
            f"{self.fees_usd:.3f} $)"
        )


class PaperBroker:
    """Simula ordenes contra velas reales. Sin I/O y sin reloj propio.

    Se le van dando velas cerradas con `on_bar()` y el va llenando, saltando
    stops y cerrando en objetivo. Que no consulte el reloj es lo que permite
    usar el MISMO codigo para el recorrido historico y para la ejecucion en
    vivo de las 72 h del criterio de avance.
    """

    def __init__(self, instruments: dict[str, Instrument]) -> None:
        self.instruments = dict(instruments)
        self.orders: list[PaperOrder] = []
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[PaperTrade] = []
        self.rejected_submissions: list[tuple[str, str]] = []

    # --- entrada de ordenes ---

    def submit(
        self,
        decision_id: str,
        symbol: str,
        qty: float,
        limit_price: float,
        stop_price: float,
        target_price: float,
        setup: str,
        ts_ms: int,
    ) -> PaperOrder | None:
        """Manda una entrada limit. Devuelve `None` si no tiene sentido.

        No comprueba reglas de riesgo: eso ya lo hizo `risk/engine.py` y
        repetirlo aqui daria una segunda opinion que no manda sobre nada. Lo
        que si comprueba son cosas que harian imposible simular: cantidad cero,
        un stop que no esta debajo, o un simbolo ya ocupado.
        """
        if qty <= 0 or limit_price <= 0:
            self.rejected_submissions.append((decision_id, "cantidad o precio no validos"))
            return None
        if not (stop_price < limit_price < target_price):
            self.rejected_submissions.append(
                (decision_id, "los precios no estan en orden stop < entrada < objetivo")
            )
            return None
        if symbol in self.positions or any(
            o.symbol == symbol and o.state is OrderState.PENDING for o in self.orders
        ):
            self.rejected_submissions.append((decision_id, "ya hay algo vivo en ese simbolo"))
            return None
        if symbol not in self.instruments:
            self.rejected_submissions.append((decision_id, "instrumento desconocido"))
            return None

        order = PaperOrder(
            decision_id=decision_id,
            symbol=symbol,
            qty=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            target_price=target_price,
            setup=setup,
            created_ts_ms=ts_ms,
        )
        self.orders.append(order)
        return order

    def cancel_pending(self, symbol: str | None = None) -> int:
        """Cancela entradas pendientes. Al entrar en cualquier modo de solo
        cierre hay que hacerlo (PRD seccion 5)."""
        cancelled = 0
        for order in self.orders:
            if order.state is not OrderState.PENDING:
                continue
            if symbol is not None and order.symbol != symbol:
                continue
            order.state = OrderState.CANCELLED
            cancelled += 1
        return cancelled

    def close_at_market(self, symbol: str, bar: Bar, reason: ExitReason = ExitReason.NEWS) -> PaperTrade | None:
        """Vende la posicion de `symbol` al CIERRE de `bar`, a mercado (flag critica de noticias).

        Va DESPUES de `on_bar` de esa misma vela: si la vela ya toco el stop o el objetivo, la
        posicion ya no esta y no hay nada que vender. Al cierre y no a la apertura porque la flag
        se mira cuando se decide, al cerrar la vela. Taker: cruza el libro.
        """
        position = self.positions.get(symbol)
        if position is None:
            return None
        position.worst_price = min(position.worst_price, bar.low)
        position.best_price = max(position.best_price, bar.high)
        instrument = self.instruments[symbol]
        trade = PaperTrade(
            decision_id=position.decision_id, symbol=symbol, setup=position.setup, qty=position.qty,
            entry_price=position.entry_price, exit_price=bar.close, stop_price=position.stop_price,
            target_price=position.target_price, opened_ts_ms=position.opened_ts_ms,
            closed_ts_ms=bar.ts_open_ms, reason=reason,
            entry_fee_usd=position.entry_fee_usd,
            exit_fee_usd=position.qty * bar.close * instrument.taker_fee, exit_was_maker=False,
            mae_pct=(position.worst_price - position.entry_price) / position.entry_price * 100.0,
            mfe_pct=(position.best_price - position.entry_price) / position.entry_price * 100.0,
        )
        self.trades.append(trade)
        del self.positions[symbol]
        return trade

    # --- avance del tiempo ---

    def on_bar(self, symbol: str, bar: Bar) -> list[PaperTrade]:
        """Avanza una vela. Devuelve las operaciones que se hayan cerrado.

        ORDEN DE LOS PASOS, que importa: primero se mira si se llena una
        entrada pendiente y luego, sobre la MISMA vela, si esa posicion recien
        abierta salta. Hacerlo al reves (posiciones antes que entradas) daria
        a cada posicion una vela de gracia que en vivo no existe.
        """
        closed: list[PaperTrade] = []

        llenada_ahora = self._fill_entries(symbol, bar)

        position = self.positions.get(symbol)
        if position is not None:
            trade = self._resolve_position(position, bar, objetivo_posible=not llenada_ahora)
            if trade is not None:
                closed.append(trade)
                self.trades.append(trade)
                del self.positions[symbol]

        self._expire_entries(symbol)
        return closed

    def _fill_entries(self, symbol: str, bar: Bar) -> bool:
        """Llena la entrada pendiente de `symbol` si la vela llega a su limite. True si se lleno en ESTA vela."""
        for order in self.orders:
            if order.state is not OrderState.PENDING or order.symbol != symbol:
                continue
            # La vela que crea la orden no puede llenarla: la senyal se genera
            # con el CIERRE de esa vela, asi que su minima ya ha pasado.
            if bar.ts_open_ms <= order.created_ts_ms:
                continue
            if bar.low > order.limit_price:
                continue

            # Suposicion 2: se llena a SU precio, aunque el mercado haya abierto
            # mas abajo y en la realidad te hubieran llenado mejor.
            instrument = self.instruments[order.symbol]
            fee = order.qty * order.limit_price * instrument.maker_fee
            order.state = OrderState.FILLED
            self.positions[symbol] = PaperPosition(
                decision_id=order.decision_id,
                symbol=symbol,
                qty=order.qty,
                entry_price=order.limit_price,
                stop_price=order.stop_price,
                target_price=order.target_price,
                setup=order.setup,
                opened_ts_ms=bar.ts_open_ms,
                entry_fee_usd=fee,
            )
            return True
        return False

    def _resolve_position(
        self, position: PaperPosition, bar: Bar, *, objetivo_posible: bool = True
    ) -> PaperTrade | None:
        """`objetivo_posible=False` en la vela que llena la entrada (suposicion 7, revision del 15/10/2026): dentro de
        la vela no se sabe si el maximo fue antes o despues de bajar al limite; lo prudente, como con el stop, es que
        el objetivo cuente desde la vela siguiente. El stop si cuenta (suposicion 5)."""
        position.worst_price = min(position.worst_price, bar.low)
        position.best_price = max(position.best_price, bar.high)

        hits_stop = bar.low <= position.stop_price
        hits_target = objetivo_posible and bar.high >= position.target_price

        if not hits_stop and not hits_target:
            return None

        instrument = self.instruments[position.symbol]

        if hits_stop:
            # Suposicion 1: si tambien tocaba el objetivo, gana el stop.
            # Suposicion 3: el hueco a la baja SI se paga.
            price = min(position.stop_price, bar.open)
            fee = position.qty * price * instrument.taker_fee
            reason, maker = ExitReason.STOP, False
        else:
            # Suposicion 4: el hueco al alza NO se cobra.
            price = position.target_price
            fee = position.qty * price * instrument.maker_fee
            reason, maker = ExitReason.TARGET, True

        return PaperTrade(
            decision_id=position.decision_id,
            symbol=position.symbol,
            setup=position.setup,
            qty=position.qty,
            entry_price=position.entry_price,
            exit_price=price,
            stop_price=position.stop_price,
            target_price=position.target_price,
            opened_ts_ms=position.opened_ts_ms,
            closed_ts_ms=bar.ts_open_ms,
            reason=reason,
            entry_fee_usd=position.entry_fee_usd,
            exit_fee_usd=fee,
            exit_was_maker=maker,
            mae_pct=(position.worst_price - position.entry_price)
            / position.entry_price
            * 100.0,
            mfe_pct=(position.best_price - position.entry_price)
            / position.entry_price
            * 100.0,
        )

    def _expire_entries(self, symbol: str) -> None:
        for order in self.orders:
            if order.state is not OrderState.PENDING or order.symbol != symbol:
                continue
            order.bars_waited += 1
            if order.bars_waited > ENTRY_BARS_TO_LIVE:
                order.state = OrderState.EXPIRED

    # --- lectura del estado ---

    @property
    def pending(self) -> list[PaperOrder]:
        return [o for o in self.orders if o.state is OrderState.PENDING]

    @property
    def occupied_slots(self) -> int:
        """Regla 4: abiertas MAS pendientes."""
        return len(self.positions) + len(self.pending)

    def exposure_usd(self, marks: dict[str, float] | None = None) -> float:
        prices = marks or {}
        total = sum(
            p.qty * prices.get(s, p.entry_price) for s, p in self.positions.items()
        )
        total += sum(o.notional for o in self.pending)
        return total

    def stats(self) -> dict[str, Any]:
        """Las metricas honestas del informe seccion 1.9.

        Sin `profit factor` cuando no hay perdidas ni `win rate` cuando no hay
        operaciones: un ratio sobre cero operaciones no es un 100 %, es nada.
        """
        if not self.trades:
            return {"trades": 0}

        rs = [t.r_multiple for t in self.trades]
        wins = [t for t in self.trades if t.net_pnl_usd > 0]
        losses = [t for t in self.trades if t.net_pnl_usd < 0]
        ganado = sum(t.net_pnl_usd for t in wins)
        perdido = -sum(t.net_pnl_usd for t in losses)

        out: dict[str, Any] = {
            "trades": len(self.trades),
            "win_rate_pct": len(wins) / len(self.trades) * 100.0,
            "expectancy_r": sum(rs) / len(rs),
            "net_pnl_usd": sum(t.net_pnl_usd for t in self.trades),
            "gross_pnl_usd": sum(t.gross_pnl_usd for t in self.trades),
            "fees_usd": sum(t.fees_usd for t in self.trades),
            "stops": sum(1 for t in self.trades if t.hit_stop),
            "targets": sum(1 for t in self.trades if t.reason is ExitReason.TARGET),
            "maker_exit_pct": sum(1 for t in self.trades if t.exit_was_maker)
            / len(self.trades)
            * 100.0,
            "mae_pct_medio": sum(t.mae_pct for t in self.trades) / len(self.trades),
            "mfe_pct_medio": sum(t.mfe_pct for t in self.trades) / len(self.trades),
        }
        if perdido > 0:
            out["profit_factor"] = ganado / perdido
        return out


@dataclass(slots=True)
class PaperLedger:
    """Equity de la cartera de papel, para el criterio de avance de 72 h."""

    starting_usd: float
    broker: PaperBroker
    history: list[tuple[int, float]] = field(default_factory=list)

    @property
    def realized_usd(self) -> float:
        return sum(t.net_pnl_usd for t in self.broker.trades)

    def equity_usd(self, marks: dict[str, float]) -> float:
        """Regla 6, version de papel: libre mas posiciones al mejor bid.

        Las comisiones de salida se descuentan como TAKER, que es el peor caso
        y lo mismo que hace `risk/equity.py` con dinero de verdad.

        La comision de ENTRADA de una posicion abierta tambien se resta: ya se
        pago, asi que el USDC libre de la regla 6 ya no la tiene. Hasta el
        22/09/2026 no se restaba, y el equity salia inflado en ~0,015 $ por
        posicion abierta: poco, pero en la direccion que el simulador tiene
        prohibida (todas sus suposiciones van EN CONTRA).
        """
        total = self.starting_usd + self.realized_usd
        for symbol, position in self.broker.positions.items():
            mark = marks.get(symbol, position.entry_price)
            instrument = self.broker.instruments[symbol]
            valor = position.qty * mark
            total += valor - position.qty * position.entry_price
            total -= position.entry_fee_usd
            total -= valor * instrument.taker_fee
        return total

    def record(self, ts_ms: int, marks: dict[str, float]) -> float:
        equity = self.equity_usd(marks)
        self.history.append((ts_ms, equity))
        return equity

    def max_drawdown_pct(self) -> float:
        if not self.history:
            return 0.0
        peak = self.history[0][1]
        worst = 0.0
        for _ts, equity in self.history:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak * 100.0)
        return worst
