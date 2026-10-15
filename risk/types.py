"""Tipos que entran y salen del motor de riesgo."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal


# Parte del spread que paga quien cruza el libro: la mitad, porque cruzar es ir
# del medio a un lado. Mismo criterio que `strategy/costs.py`, duplicado a
# proposito: el motor de riesgo es la ultima barrera y no importa nada de la
# capa a la que vigila.
TAKER_SPREAD_SHARE = 0.5


def _floor_to_step(value: float, step: float) -> float:
    """El multiplo de `step` mas grande que no pasa de `value`, sin coma flotante.

    POR QUE DECIMAL (hallazgo del 22/09/2026): `floor(value / step) * step` en
    coma flotante perdia un paso entero sin motivo. 0,58 / 0,01 da 57,999... en
    binario, asi que 0,58 TRX salia 0,57; 0,3 AVAX salia 0,2999. Y devolvia
    cantidades sucias como 0,5700000000000001, que no son multiplo del lote.
    Siempre hacia abajo, eso si: nunca compraba de mas, pero perdia un lote y,
    justo en el minimo del par (1 XRP, 10 DOGE), podia tumbar una orden valida.

    `repr` da el decimal mas corto que vuelve al mismo float, asi que el
    resultado nunca queda por encima de `value`: si coincide con el, es el
    mismo float; si no, esta al menos un paso por debajo.
    """
    if step <= 0:
        return value
    paso = Decimal(repr(step))
    pasos = (Decimal(repr(value)) / paso).to_integral_value(rounding=ROUND_FLOOR)
    return float(pasos * paso)


@dataclass(frozen=True, slots=True)
class Instrument:
    """Filtros del instrumento, leidos del exchange (informe seccion 1.6).

    OKX NO publica minimo nocional: `limits.cost.min` viene a None en ccxt.
    Hay que calcularlo como `min_amount * precio`. Para BTC/USDC eso son 8,58 $
    (medido el 22/09/2026), asi que una salida parcial del 50 % sobre una
    posicion de 15 $ quedaria por debajo del minimo. El disenyo no lleva
    salidas parciales.

    LAS COMISIONES NO TIENEN VALOR POR DEFECTO, y es deliberado. OKX Europa las
    cambia el 25/09/2026: un valor por defecto escrito aqui se quedaria viejo
    sin que nadie se entere, y la regla 16 estaria comparando el objetivo
    contra un coste inventado. Quien construye un `Instrument` tiene que decir
    de donde saca las comisiones; `from_row()` las saca de la tabla
    `instruments` y se planta si faltan.
    """

    symbol: str
    tick_size: float
    lot_size: float
    min_amount: float
    maker_fee: float       # tanto por uno: 0,001 = 0,10 %
    taker_fee: float
    min_cost_usd: float | None = None

    def __post_init__(self) -> None:
        for name, value in (("maker", self.maker_fee), ("taker", self.taker_fee)):
            if value is None or value < 0:
                raise ValueError(
                    f"comision {name} invalida en {self.symbol}: {value}"
                )

    @classmethod
    def from_row(cls, row: dict) -> Instrument:
        """Construye desde una fila de la tabla `instruments`.

        Se planta si faltan las comisiones en vez de rellenarlas: un simbolo
        cuyo coste no se conoce no se opera.
        """
        symbol = row["symbol"]
        if row.get("maker_fee") is None or row.get("taker_fee") is None:
            raise ValueError(
                f"{symbol}: la tabla `instruments` no trae comisiones. Hay que "
                f"refrescar el catalogo antes de poder juzgar la regla 16."
            )
        return cls(
            symbol=symbol,
            tick_size=float(row["tick_size"]),
            lot_size=float(row["lot_size"]),
            min_amount=float(row["min_amount"]),
            maker_fee=float(row["maker_fee"]),
            taker_fee=float(row["taker_fee"]),
            min_cost_usd=(
                float(row["min_cost"]) if row.get("min_cost") is not None else None
            ),
        )

    def round_amount_down(self, amount: float) -> float:
        """Redondea la cantidad al lote, SIEMPRE hacia abajo (informe 1.6).

        Hacia abajo y no al mas cercano: redondear hacia arriba puede dejarte
        comprando mas de lo que el motor de riesgo aprobo, que es precisamente
        lo que las reglas duras existen para impedir.
        """
        return _floor_to_step(amount, self.lot_size)

    def round_price_down(self, price: float) -> float:
        """Redondea el precio al tick, hacia abajo.

        OJO: a 22/09/2026 no lo llama nadie. Los precios de entrada de los
        candidatos NO se redondean al tick, y el exchange rechaza un limite
        que no lo sea. Hay que hacerlo en `execution/` (fase 4), justo antes
        de mandar la orden.
        """
        return _floor_to_step(price, self.tick_size)

    def min_notional_usd(self, price: float) -> float:
        """Minimo efectivo por orden, en dolares."""
        by_amount = self.min_amount * price
        if self.min_cost_usd is not None:
            return max(by_amount, self.min_cost_usd)
        return by_amount

    def round_trip_cost_pct(
        self,
        spread_pct: float = 0.0,
        *,
        entry_maker: bool = True,
        exit_maker: bool = False,
        exit_move_pct: float = 0.0,
    ) -> float:
        """Coste de abrir y cerrar, en % del nocional de entrada.

        LA SALIDA ES TAKER POR DEFECTO, y ahi esta lo importante. El stop-loss
        vive en el exchange como orden algoritmica (regla 13): cuando salta,
        cruza el libro. Una salida urgente no puede ser maker. Suponer
        maker/maker en las dos patas subestima el coste, y subestimarlo hace
        que la regla 16 deje pasar operaciones que no pagan sus comisiones.

        El spread solo lo paga la pata que cruza, y paga la mitad: cruzar es ir
        del medio a un lado.
        """
        entry_fee = (self.maker_fee if entry_maker else self.taker_fee) * 100.0
        exit_fee = (self.maker_fee if exit_maker else self.taker_fee) * 100.0
        # La comision de salida se cobra sobre el nocional de salida: si el
        # objetivo esta un 6,66 % arriba, esa comision es un 6,66 % mayor.
        exit_fee *= 1.0 + exit_move_pct / 100.0

        share = max(0.0, spread_pct) * TAKER_SPREAD_SHARE
        slippage = (0.0 if entry_maker else share) + (0.0 if exit_maker else share)
        return entry_fee + exit_fee + slippage


@dataclass(frozen=True, slots=True)
class EntryRequest:
    """Una peticion de abrir posicion, ya con entrada, stop y objetivo.

    El motor de riesgo NO calcula donde va el stop: eso lo decide el generador
    de candidatos a partir del ATR. Aqui solo se juzga si lo que proponen cabe
    dentro de las reglas.
    """

    symbol: str
    entry_price: float
    stop_price: float
    target_price: float
    setup: str
    instrument: Instrument
    decision_id: str
    spread_pct: float = 0.0
    # La IA solo puede REDUCIR el tamanyo: [0,5; 1,0] (PRD seccion 6).
    size_multiplier: float = 1.0
    # Confianza que declaro la IA. Se registra pero no se usa tal cual: los
    # LLM estan mal calibrados (informe seccion 1.5).
    ai_confidence: float | None = None

    @property
    def stop_distance_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.entry_price - self.stop_price) / self.entry_price * 100.0

    @property
    def target_distance_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.target_price - self.entry_price) / self.entry_price * 100.0

    @property
    def reward_risk(self) -> float:
        risk = self.entry_price - self.stop_price
        if risk <= 0:
            return 0.0
        return (self.target_price - self.entry_price) / risk


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Veredicto de UNA regla."""

    number: int
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "OK " if self.passed else "VETO"
        return f"[{mark}] regla {self.number:2d} ({self.name}): {self.detail}"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Resultado completo. Incluye TODAS las reglas, no solo las que vetaron.

    El panel "que esta pensando la IA" del PRD seccion 10 necesita ensenyar por
    que se bloqueo algo, y con un cortocircuito en la primera regla que falla
    solo verias una causa aunque hubiera cinco.
    """

    approved: bool
    results: tuple[RuleResult, ...]
    qty: float = 0.0
    notional_usd: float = 0.0
    risk_usd: float = 0.0
    decision_id: str = ""
    sizing_detail: str = ""

    @property
    def vetoes(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def veto_numbers(self) -> tuple[int, ...]:
        return tuple(r.number for r in self.vetoes)

    def reason(self) -> str:
        if self.approved:
            return "aprobado"
        return "; ".join(f"regla {r.number}: {r.detail}" for r in self.vetoes)

    def __str__(self) -> str:
        head = "APROBADO" if self.approved else "VETADO"
        lines = [f"{head} ({self.decision_id})"]
        if self.approved:
            lines.append(
                f"  cantidad {self.qty} = {self.notional_usd:.2f} $, "
                f"riesgo {self.risk_usd:.2f} $"
            )
        lines += [f"  {r}" for r in self.results if not r.passed]
        return "\n".join(lines)
