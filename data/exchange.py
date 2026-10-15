"""Envoltorio sobre ccxt para OKX (regla dura 2).

Todo el contacto con el exchange pasa por aqui. El resto del bot no importa
ccxt directamente: asi cambiar de exchange es cambiar este fichero, no
reescribir el bot (informe seccion 3.2).

Fase 1: SOLO datos publicos. No se leen claves, no se firma nada, no se envia
ninguna orden. El constructor lo comprueba y falla si alguien le pasa
credenciales antes de tiempo.
"""

from __future__ import annotations

import json
from typing import Any

import ccxt.pro as ccxtpro

from core.clock import SkewReading, utcnow_ms
from core.config import Settings
from core.logging import get_logger

log = get_logger(__name__)

# OKX responde 403 a clientes sin User-Agent reconocible (comprobado el
# 22/09/2026). ccxt pone el suyo, pero lo dejamos explicito para que un cambio
# en ccxt no nos deje fuera sin avisar.
USER_AGENT = "ploutos/0.1"

EU_HOSTNAME_NOTE = """Medido el 22/09/2026 con una cuenta real de OKX Europe:

    host           demo    real
    www.okx.com    50119   50119    <- el que ccxt usa POR DEFECTO
    eea.okx.com    OK      50101
    my.okx.com     OK      50101
    app.okx.com    50119   50119

Los datos PUBLICOS (velas, libro, instrumentos) son identicos en todos: se
compararon libros de BTC/ETH/TRX y los catalogos de instrumentos, y coinciden.
La diferencia solo afecta a las peticiones AUTENTICADAS.

50119 = "API key doesn't exist". OKX responde eso tanto cuando preguntas al host
equivocado como cuando llamas desde una IP no autorizada: nunca dice cual de las
dos cosas es. Si algun dia vuelve a aparecer, comprobar ambas."""


class ExchangeError(Exception):
    """Fallo al hablar con el exchange."""


class WhitelistMismatchError(ExchangeError):
    """Regla 3: un simbolo de la whitelist no existe o no se puede operar."""


class Exchange:
    """Acceso a OKX. Publico en las fases 1-3, autenticado a partir de la 4."""

    def __init__(self, settings: Settings, public_only: bool = True) -> None:
        self.settings = settings
        self.public_only = public_only
        self._client: ccxtpro.okx | None = None

    # --- ciclo de vida ---

    async def open(self) -> None:
        if self._client is not None:
            return
        config: dict[str, Any] = {
            "enableRateLimit": True,  # informe seccion 2.4: limitador propio
            "options": {"defaultType": "spot"},
            "headers": {"User-Agent": USER_AGENT},
            # Entidad europea. Sin esto, las peticiones autenticadas fallan con
            # 50119 "API key doesn't exist" aunque la clave exista y la IP este
            # en la lista blanca. Ver EU_HOSTNAME_NOTE.
            "hostname": self.settings.exchange.hostname,
        }
        if self.public_only:
            log.info("exchange en modo SOLO PUBLICO: sin claves, sin ordenes")
        else:
            raise NotImplementedError(
                "el modo autenticado llega en la fase 4 (demo de OKX). "
                "Las fases 1-3 funcionan con datos publicos."
            )

        self._client = ccxtpro.okx(config)
        await self._client.load_markets()
        log.info("mercados cargados: %d instrumentos", len(self._client.markets))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def __aenter__(self) -> Exchange:
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def client(self) -> ccxtpro.okx:
        if self._client is None:
            raise ExchangeError("el exchange no esta abierto; llama a open()")
        return self._client

    # --- instrumentos (informe seccion 1.6) ---

    def check_whitelist(self) -> None:
        """Regla 3, punto de validacion 1 de 4, contra el exchange real.

        No basta con que el YAML tenga el formato correcto: el par tiene que
        existir, estar activo, ser spot y cotizar en USDC. Si no, no arrancamos.
        """
        problems: list[str] = []
        for symbol in self.settings.whitelist:
            market = self.client.markets.get(symbol)
            if market is None:
                problems.append(f"{symbol}: no existe en {self.settings.exchange.id}")
                continue
            if not market.get("active", False):
                problems.append(f"{symbol}: existe pero no esta activo")
            if not market.get("spot", False):
                problems.append(f"{symbol}: no es un mercado spot (regla 1)")
            if market.get("quote") != self.settings.exchange.quote:
                problems.append(
                    f"{symbol}: cotiza en {market.get('quote')}, no en "
                    f"{self.settings.exchange.quote} (regla 3)"
                )
        if problems:
            raise WhitelistMismatchError(
                "la whitelist no cuadra con el exchange: " + "; ".join(problems)
            )
        log.info(
            "whitelist verificada contra el exchange: %d pares OK",
            len(self.settings.whitelist),
        )

    def instrument_rows(self) -> list[tuple[Any, ...]]:
        """Filtros de cada instrumento, para guardarlos y redondear con ellos."""
        now = utcnow_ms()
        rows: list[tuple[Any, ...]] = []
        for symbol in self.settings.whitelist:
            market = self.client.markets[symbol]
            limits = market.get("limits") or {}
            precision = market.get("precision") or {}
            rows.append(
                (
                    symbol,
                    market.get("base"),
                    market.get("quote"),
                    int(bool(market.get("active"))),
                    precision.get("price"),
                    precision.get("amount"),
                    (limits.get("amount") or {}).get("min"),
                    (limits.get("cost") or {}).get("min"),
                    market.get("maker"),
                    market.get("taker"),
                    json.dumps(market.get("info", {}), default=str),
                    now,
                )
            )
        return rows

    # --- datos de mercado ---

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int | None = None,
        limit: int = 300,
    ) -> list[list[Any]]:
        """Velas por REST. Para backfill y para rellenar huecos."""
        return await self.client.fetch_ohlcv(symbol, timeframe, since_ms, limit)

    async def watch_ohlcv(self, symbol: str, timeframe: str) -> list[list[Any]]:
        """Velas por WebSocket. Devuelve las actualizadas desde la ultima vez.

        Incluye la vela EN CURSO. Quien llame decide cuales estan cerradas
        (`core.clock.candle_is_closed`).
        """
        return await self.client.watch_ohlcv(symbol, timeframe)

    async def watch_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        return await self.client.watch_order_book(symbol, limit)

    async def watch_ticker(self, symbol: str) -> dict[str, Any]:
        return await self.client.watch_ticker(symbol)

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        return await self.client.fetch_order_book(symbol, limit)

    # --- reloj (informe seccion 1.3[1]) ---

    async def measure_skew(self) -> SkewReading:
        """Mide el desfase entre nuestro reloj y el del exchange."""
        before = utcnow_ms()
        remote = await self.client.fetch_time()
        after = utcnow_ms()
        return SkewReading(
            local_ms=(before + after) // 2,
            remote_ms=int(remote),
            round_trip_ms=after - before,
        )
