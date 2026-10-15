"""Modelo de costes (informe seccion 2.2).

EL COSTE MUEVE LA VARA MAS QUE CUALQUIER INDICADOR. Con un stop al 1,5 % y un
objetivo al 3 %, hace falta acertar el 33 % de las veces para empatar si no hay
costes; con un 0,5 % de coste por operacion, el 44,4 %. Por eso el coste se
calcula aparte, con su propio modulo y sus propios tests, en vez de ser una
constante escondida en el generador de candidatos.

TRES DECISIONES QUE CONVIENE NO DESHACER:

1. **Las comisiones se LEEN de la tabla `instruments`, no se fijan aqui.**
   OKX Europa cambia sus comisiones el 25/09/2026 (el informe seccion 2.2 daba
   0,10 % / 0,20 %; lo medido el 22/09/2026 con ccxt fue 0,10 % / 0,15 %). Un
   numero escrito en el codigo se queda viejo en silencio; una lectura de la
   tabla se actualiza sola en cuanto la ingesta refresca el catalogo.

2. **Si no hay comision, no hay precio.** Un simbolo sin fila, con comisiones a
   NULL o con la fila caducada no recibe un valor por defecto: se lanza
   `MissingFeeError` y ese simbolo no genera candidatos. Es la misma regla que
   en `features/indicators.py`: devolver NaN antes que un numero inventado.
   Inventar una comision baja es justo el error que hace que un bot parezca
   rentable en el papel y pierda dinero en vivo.

3. **La pata de salida es TAKER, siempre.** El stop-loss vive en el exchange
   como orden algoritmica (regla 13): cuando se dispara, cruza el libro. No se
   puede ser maker en una salida que por definicion es urgente. Suponer
   maker/maker en las dos patas subestima el coste, y ese error va en la
   direccion peligrosa: deja pasar operaciones que no pagan sus comisiones.

COMO SE CUENTA EL SPREAD. El coste se expresa respecto al precio de referencia
del candidato:

  * una pata **maker** pone su propio precio: o te llenan a tu precio o no hay
    operacion, asi que no paga spread (paga otra cosa, ver mas abajo);
  * una pata **taker** cruza el libro, o sea que va del medio a un lado: paga
    la MITAD del spread.

Impacto de mercado: se supone CERO, y esa suposicion la sostiene el filtro de
profundidad de `strategy/filters.py`, que exige profundidad >= 20x el tamanyo
de la orden (informe seccion 1.3[4]). Con 15 $ contra libros donde la fase 1
midio que la profundidad nunca es la restriccion, el impacto no se distingue
del ruido. Si algun dia se sube el tamanyo o se relaja ese filtro, este modulo
se queda corto.

LO QUE ESTE MODELO **NO** CUENTA, y hay que saberlo:

  * **Seleccion adversa de la pata maker.** Una orden limit de compra se llena
    cuando el precio baja hasta ti, que muchas veces es cuando sigue bajando.
    Es un coste real y no hay forma honesta de estimarlo sin datos propios. La
    fase 6 lo medira comparando el precio de llenado con el de referencia
    (informe seccion 1.9, "slippage real vs estimado").
  * **Las entradas que no se llenan.** No cuestan comision, pero cuestan
    oportunidad.

Las dos cosas hacen que el coste REAL sea mayor que el de aqui. El modelo es
optimista por construccion, asi que el filtro de 3x de la regla 16 es un
minimo, no un margen comodo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo para los tipos
    from data.store.repos import InstrumentRepo

# Parte del spread que paga quien cruza el libro. La mitad, porque cruzar es ir
# del medio a un lado.
TAKER_SPREAD_SHARE = 0.5

# Cuanto puede envejecer una fila de `instruments` antes de que este modulo se
# niegue a poner precio. La ingesta refresca el catalogo en cada arranque, asi
# que una fila de hace mas de una semana significa que el proceso lleva mucho
# tiempo corriendo sin releer comisiones. Negarse deja el bot sin entradas
# nuevas (degradado pero seguro); mentir sobre el coste, no.
MAX_FEE_AGE_MS = 7 * 24 * 60 * 60 * 1000


class MissingFeeError(RuntimeError):
    """No se puede poner precio a este simbolo, y por tanto no se opera."""


class Fill(Enum):
    """Como se llena una pata. Determina comision y spread pagado."""

    MAKER = "maker"
    TAKER = "taker"


@dataclass(frozen=True, slots=True)
class Fees:
    """Comisiones de un simbolo, tal y como las publico el exchange."""

    symbol: str
    maker: float       # tanto por uno: 0,001 = 0,10 %
    taker: float
    fetched_ms: int

    def __post_init__(self) -> None:
        for name, value in (("maker", self.maker), ("taker", self.taker)):
            if value is None or value < 0:
                raise ValueError(f"comision {name} invalida en {self.symbol}: {value}")

    def rate(self, fill: Fill) -> float:
        return self.maker if fill is Fill.MAKER else self.taker

    def age_ms(self, now_ms: int) -> int:
        return now_ms - self.fetched_ms


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """El coste de una ida y vuelta, desglosado y en % del nocional de entrada.

    Desglosado y no en un solo numero porque el panel del PRD seccion 10 tiene
    que poder ensenyar de donde sale, y porque en la fase 6 hay que comparar
    cada pieza con lo que paso de verdad.
    """

    symbol: str
    entry_fill: Fill
    exit_fill: Fill
    entry_fee_pct: float
    exit_fee_pct: float
    entry_spread_pct: float
    exit_spread_pct: float
    spread_pct: float          # el spread observado, para trazabilidad

    @property
    def fees_pct(self) -> float:
        return self.entry_fee_pct + self.exit_fee_pct

    @property
    def slippage_pct(self) -> float:
        return self.entry_spread_pct + self.exit_spread_pct

    @property
    def total_pct(self) -> float:
        """Coste de ida y vuelta, en % del nocional de entrada."""
        return self.fees_pct + self.slippage_pct

    def usd(self, notional_usd: float) -> float:
        return notional_usd * self.total_pct / 100.0

    def __str__(self) -> str:
        return (
            f"{self.symbol}: {self.total_pct:.4f} % "
            f"(comisiones {self.fees_pct:.4f} % {self.entry_fill.value}/"
            f"{self.exit_fill.value}, spread {self.slippage_pct:.4f} % "
            f"de {self.spread_pct:.4f} % observado)"
        )


class CostModel:
    """Pone precio a una ida y vuelta. Sin I/O: se construye ya cargado.

    Se construye una vez por ciclo de decision y se consulta muchas veces. Que
    no toque la base de datos permite probarlo con cualquier tabla de
    comisiones inventada, y evita que el generador de candidatos haga una
    consulta por simbolo y por setup.
    """

    def __init__(
        self,
        fees: dict[str, Fees],
        *,
        now_ms: int,
        max_age_ms: int = MAX_FEE_AGE_MS,
    ) -> None:
        self._fees = dict(fees)
        self._now_ms = now_ms
        self._max_age_ms = max_age_ms

    # --- construccion ---

    @classmethod
    def from_repo(
        cls,
        repo: InstrumentRepo,
        *,
        now_ms: int,
        symbols: list[str] | None = None,
        max_age_ms: int = MAX_FEE_AGE_MS,
    ) -> CostModel:
        """Lee las comisiones de la tabla `instruments`.

        Las filas con comisiones a NULL NO se cargan. Asi el fallo aparece al
        preguntar por ese simbolo, con su nombre, en vez de convertirse en un
        cero silencioso.
        """
        wanted = set(symbols) if symbols else None
        loaded: dict[str, Fees] = {}
        for row in repo.all():
            symbol = row["symbol"]
            if wanted is not None and symbol not in wanted:
                continue
            if row.get("maker_fee") is None or row.get("taker_fee") is None:
                continue
            loaded[symbol] = Fees(
                symbol=symbol,
                maker=float(row["maker_fee"]),
                taker=float(row["taker_fee"]),
                fetched_ms=int(row["fetched_ms"]),
            )
        return cls(loaded, now_ms=now_ms, max_age_ms=max_age_ms)

    # --- consulta ---

    def fees_for(self, symbol: str) -> Fees:
        """Comisiones de un simbolo, o `MissingFeeError` con el motivo."""
        fees = self._fees.get(symbol)
        if fees is None:
            raise MissingFeeError(
                f"{symbol}: sin comisiones en la tabla `instruments`. No se "
                f"generan candidatos de un simbolo cuyo coste no se conoce."
            )
        age = fees.age_ms(self._now_ms)
        if age > self._max_age_ms:
            raise MissingFeeError(
                f"{symbol}: las comisiones se leyeron hace {age / 3_600_000:.1f} h "
                f"y el tope son {self._max_age_ms / 3_600_000:.0f} h. Hay que "
                f"refrescar el catalogo de instrumentos antes de volver a operar."
            )
        return fees

    def knows(self, symbol: str) -> bool:
        """Si este simbolo se puede valorar ahora mismo."""
        try:
            self.fees_for(symbol)
        except MissingFeeError:
            return False
        return True

    def round_trip(
        self,
        symbol: str,
        spread_pct: float,
        *,
        entry_fill: Fill = Fill.MAKER,
        exit_fill: Fill = Fill.TAKER,
        exit_move_pct: float = 0.0,
    ) -> CostBreakdown:
        """Coste de abrir y cerrar, en % del nocional de ENTRADA.

        `exit_move_pct` es cuanto se ha movido el precio al salir. Importa
        porque la comision de salida se cobra sobre el nocional de salida: si
        el objetivo esta un 6,66 % arriba, esa comision es un 6,66 % mayor. Es
        poca cosa (0,01 puntos), pero contarlo bien es gratis y evita tener que
        acordarse de que el numero va un pelin corto.

        Por defecto entrada maker y salida taker: es lo que pasa de verdad
        (informe seccion 1.6 mas regla 13).
        """
        if spread_pct < 0:
            raise ValueError(f"spread negativo en {symbol}: {spread_pct}")
        fees = self.fees_for(symbol)

        entry_fee = fees.rate(entry_fill) * 100.0
        exit_fee = fees.rate(exit_fill) * 100.0 * (1.0 + exit_move_pct / 100.0)

        share = spread_pct * TAKER_SPREAD_SHARE
        entry_slip = 0.0 if entry_fill is Fill.MAKER else share
        exit_slip = 0.0 if exit_fill is Fill.MAKER else share

        return CostBreakdown(
            symbol=symbol,
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            entry_fee_pct=entry_fee,
            exit_fee_pct=exit_fee,
            entry_spread_pct=entry_slip,
            exit_spread_pct=exit_slip,
            spread_pct=spread_pct,
        )

    def breakeven_move_pct(
        self,
        symbol: str,
        spread_pct: float,
        *,
        entry_fill: Fill = Fill.MAKER,
        exit_fill: Fill = Fill.TAKER,
    ) -> float:
        """Cuanto tiene que subir el precio para no perder ni ganar nada."""
        return self.min_target_pct(
            symbol, spread_pct, ratio=1.0, entry_fill=entry_fill, exit_fill=exit_fill
        )

    def min_target_pct(
        self,
        symbol: str,
        spread_pct: float,
        *,
        ratio: float,
        entry_fill: Fill = Fill.MAKER,
        exit_fill: Fill = Fill.TAKER,
    ) -> float:
        """Objetivo minimo (en %) para que valga `ratio` veces el coste.

        La regla 16 pide objetivo >= 3x coste. Hay una trampa pequenya: el
        coste depende del objetivo (la comision de salida se cobra sobre el
        nocional de salida), asi que la condicion es circular. Se resuelve
        despejando en vez de iterando:

            t = r * (A + B * (1 + t/100))        A = comision de entrada + spread
            t = r * (A + B) / (1 - r * B / 100)  B = comision de salida
        """
        if ratio <= 0:
            raise ValueError(f"ratio no positivo: {ratio}")
        base = self.round_trip(
            symbol, spread_pct, entry_fill=entry_fill, exit_fill=exit_fill
        )
        b = base.exit_fee_pct
        a = base.entry_fee_pct + base.slippage_pct
        denominator = 1.0 - ratio * b / 100.0
        if denominator <= 0:  # pragma: no cover - comisiones absurdas
            raise ValueError(
                f"{symbol}: con una comision de salida del {b:.2f} % y ratio "
                f"{ratio} no hay objetivo alcanzable"
            )
        return ratio * (a + b) / denominator

    def as_table(self) -> list[dict[str, Any]]:
        """Para volcar en un log o en el panel. Sin secretos, solo numeros."""
        return [
            {
                "symbol": f.symbol,
                "maker_pct": f.maker * 100.0,
                "taker_pct": f.taker * 100.0,
                "age_hours": f.age_ms(self._now_ms) / 3_600_000,
            }
            for f in sorted(self._fees.values(), key=lambda x: x.symbol)
        ]
