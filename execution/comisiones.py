"""Que pares se pueden operar segun las comisiones REALES de la cuenta (fase 4; decisiones del propietario del 23/09 y 02/10).

PURO: recibe lo que contesto OKX (`GET /api/v5/account/trade-fee`, un `instId` por llamada) y devuelve los pares
operables y, de los otros, por que no.

- **23/09:** si las comisiones reales son MAS CARAS que las configuradas (`settings.yaml`, `exchange.fees`), no se
  opera: el filtro de costes (regla 16) y el sizing estarian calculados con un coste que no es el de verdad.
- **02/10: par por par.** OKX cobra por GRUPO de instrumento (`groupId`): en el demo, NEAR-USDC (grupo 13) paga
  0,20 % / 0,35 % y los otros cuatro (grupo 12) 0,10 % / 0,20 %. Mirando un solo par no se ve. Un par mas caro se
  queda fuera (en el demo, NEAR solo en papel); los demas se operan.
- Dos detalles de esa API: el signo va al reves (negativo = comision que pagas) y para los pares contra USDC se leen
  `makerUSDC`/`takerUSDC`, no `maker`/`taker` (son los de los pares contra USDT).
- Sin respuesta para un par (o sin el campo), ese par NO se opera: no se puede comparar.
"""

from __future__ import annotations

from typing import Any

EPS = 1e-12


def comision_usdc(respuesta: dict[str, Any]) -> tuple[float | None, float | None]:
    """(maker, taker) en % POSITIVO para los pares contra USDC, o None si no viene."""
    datos = (respuesta or {}).get("data") or [{}]

    def pct(clave: str) -> float | None:
        valor = datos[0].get(clave)
        if valor in (None, ""):
            return None
        return -float(valor) * 100.0     # OKX: negativo = comision que pagas
    return pct("makerUSDC"), pct("takerUSDC")


def motivos_par(par: str, reales: tuple[float | None, float | None] | None,
                configuradas: tuple[float, float]) -> list[str]:
    """Por que NO se opera `par` (vacio = se opera). `configuradas` y `reales` en % (0,10 = 0,10 %)."""
    if reales is None:
        return [f"{par}: OKX no devolvio sus comisiones: no se puede comparar"]
    motivos = []
    for nombre, real, conf in zip(("maker", "taker"), reales, configuradas):
        if real is None:
            motivos.append(f"{par}: OKX no devolvio la comision {nombre}: no se puede comparar")
        elif real > conf + EPS:
            motivos.append(f"{par}: comision {nombre} real {real:.3f} % > {conf:.3f} % configurada "
                           "(decision del 23/09)")
    return motivos


def operables(pares: tuple[str, ...] | list[str], reales: dict[str, tuple[float | None, float | None]],
              configuradas: tuple[float, float]) -> tuple[tuple[str, ...], list[str]]:
    """(pares que se operan, en el orden dado; motivos de los que no). `reales` por par ("NEAR/USDC")."""
    si, motivos = [], []
    for par in pares:
        m = motivos_par(par, reales.get(par), configuradas)
        if m:
            motivos += m
        else:
            si.append(par)
    return tuple(si), motivos
