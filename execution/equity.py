"""Equity con datos del EXCHANGE, cada 15 s, y la regla 7 (fase 4, pieza 6).

PURO: recibe los saldos y los mejores bids que ya se han pedido a OKX y devuelve la
lectura; el bucle de 15 s y las peticiones son de otra pieza. Reutiliza la definicion de
`risk.equity` (`EquityBreakdown`, `floor_breached`) sin tocar `risk/`.

Regla 6 (PRD): equity = USDC + sum(cantidad x mejor bid) - comisiones estimadas de salida,
con datos del exchange, no de la base local. Tres detalles que aqui se deciden:

1. **USDC TOTAL, no el "disponible" de OKX.** Con una entrada pendiente, OKX congela su USDC
   (`frozenBal`) y lo quita del disponible (`availBal`). Ese dinero sigue siendo nuestro: si
   se contara solo el disponible, cada orden pendiente bajaria el equity ~15 $ de golpe, y
   cerca del suelo eso enclavaria el bot (regla 7) sin haber perdido un centimo. Se usa el
   total (`cashBal` = disponible + congelado).
2. **La cantidad de cada moneda, del saldo de OKX**, no de las posiciones locales. Solo las
   8 de la whitelist: el polvo de otras monedas no se puede vender con este bot.
3. **La comision de salida es la taker CONFIGURADA** (`settings.yaml`, 0,20 %), no el valor
   por defecto de `risk.equity.compute_equity` (0,15 %, el generico de ccxt, ver CLAUDE.md).

**Saldo virtual (decision del propietario del 02/10, pieza c0).** La cuenta no es solo del bot: el demo trae 5.000 USDC, 1 BTC,
1 ETH y 50.000 XRP, y la real puede tener otros fondos. El ejecutor hace una FOTO del saldo al arrancar por primera vez
(sin posiciones) y cuenta como suyo `capital inicial + lo que haya cambiado desde la foto` (`virtual`). Todo lo de
despues (esta lectura, la regla 7 y la conciliacion) recibe el saldo YA virtualizado y no sabe que existe la foto: un
solo sitio hace la resta. Una cantidad que baja de la foto (una venta a mano en el demo) sale NEGATIVA y se resta a
su precio: el USDC que entro por esa venta no infla el equity. La conciliacion la ve como descuadre.

Regla 7: dos lecturas SEGUIDAS en o bajo el suelo enclavan CLOSE_ONLY_CAPITAL. Una lectura
NO FIABLE (falta el bid de una moneda que tenemos) no cuenta ni como baja ni como buena: el
contador se queda como estaba. Un libro vacio un instante no puede ni enclavar el bot ni
borrar una primera lectura mala de verdad.
"""

from __future__ import annotations

from dataclasses import dataclass

from risk.equity import EquityBreakdown, floor_breached


@dataclass(frozen=True, slots=True)
class SaldoOKX:
    """Lo que devuelve OKX de la cuenta, ya leido (sin ccxt aqui)."""

    usdc_total: float                   # cashBal de USDC: disponible + congelado
    monedas: dict[str, float]           # base -> cantidad total ("NEAR" -> 5,0)


def saldo_de_ccxt(balance: dict, whitelist: tuple[str, ...] | list[str]) -> SaldoOKX:
    """De `fetch_balance()` de ccxt a `SaldoOKX`, leyendo `total` y NUNCA `free`.

    Verificado en ccxt 4.5.82 (`okx.parse_trading_balance`): `total` = `eq` de OKX (lo que
    hay, congelado incluido) y `free` = `availEq`/`availBal` (sin lo congelado). La trampa
    seria leer `free`: ver el punto 1 de la cabecera.
    """
    def total(codigo: str) -> float:
        return float((balance.get(codigo) or {}).get("total") or 0.0)

    return SaldoOKX(
        usdc_total=total("USDC"),
        monedas={par.split("/", 1)[0]: total(par.split("/", 1)[0]) for par in whitelist},
    )


@dataclass(frozen=True, slots=True)
class Foto:
    """El saldo de la cuenta cuando el bot empezo: lo que NO es suyo. Se guarda en la base del ejecutor."""

    usdc_total: float
    monedas: dict[str, float]

    @classmethod
    def de_saldo(cls, saldo: SaldoOKX) -> Foto:
        return cls(saldo.usdc_total, dict(saldo.monedas))

    def a_dict(self) -> dict:
        return {"usdc_total": self.usdc_total, "monedas": dict(sorted(self.monedas.items()))}

    @classmethod
    def de_dict(cls, datos: dict) -> Foto:
        return cls(float(datos["usdc_total"]), {k: float(v) for k, v in datos["monedas"].items()})


def virtual(saldo: SaldoOKX, foto: Foto, *, capital_inicial: float) -> SaldoOKX:
    """El saldo del BOT: `capital_inicial` USDC + lo que haya cambiado cada cosa desde la foto.

    Las monedas son las del saldo (las de la whitelist, `saldo_de_ccxt`); una moneda que no estaba en la foto
    empezo en 0. El resultado puede tener cantidades negativas (ver la cabecera).
    """
    return SaldoOKX(
        usdc_total=capital_inicial + saldo.usdc_total - foto.usdc_total,
        monedas={base: cantidad - foto.monedas.get(base, 0.0) for base, cantidad in saldo.monedas.items()},
    )


def lectura(
    saldo: SaldoOKX, mejores_bids: dict[str, float], *, whitelist: tuple[str, ...] | list[str],
    taker: float,
) -> EquityBreakdown:
    """La regla 6 con datos de OKX. `mejores_bids` por PAR ("NEAR/USDC" -> 3,01)."""
    valor = comisiones = 0.0
    sin_precio: list[str] = []
    for par in whitelist:
        cantidad = saldo.monedas.get(par.split("/", 1)[0], 0.0)
        if cantidad == 0:
            continue
        bid = mejores_bids.get(par)
        if bid is None or bid <= 0:
            sin_precio.append(par)
            continue
        valor += cantidad * bid
        if cantidad > 0:   # negativa = vendida a mano desde la foto (saldo virtual): no hay nada que vender
            comisiones += cantidad * bid * taker
    return EquityBreakdown(
        free_quote_usd=saldo.usdc_total, positions_value_usd=valor,
        exit_fees_usd=comisiones, stale_symbols=tuple(sorted(sin_precio)),
    )


@dataclass(frozen=True, slots=True)
class Vigia:
    """El contador de la regla 7 entre lecturas. Inmutable: cada lectura da uno nuevo."""

    lecturas_bajo_suelo: int = 0

    def con(self, e: EquityBreakdown, suelo_usd: float) -> tuple[bool, Vigia]:
        """(enclava CLOSE_ONLY_CAPITAL, vigia siguiente)."""
        if not e.is_reliable:
            return False, self
        dispara, n = floor_breached(e.equity_usd, suelo_usd, self.lecturas_bajo_suelo)
        return dispara, Vigia(n)
