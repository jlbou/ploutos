"""El espejo: que hace el demo con lo que hace la cartera de la IA en papel (fase 4, pieza c; decisiones del 02/10).

PURO: recibe las ordenes y los cierres de la cartera de papel (leidos de su base en `mode=ro`) y lo que el ejecutor
ya tiene, y devuelve las acciones, EN ORDEN. Enviarlas (y pasar antes el motor de riesgo con el estado del demo) es
del servicio.

Las cuatro decisiones del propietario del 02/10 (`docs/archivo/diseno-fase-4.md`):
1. **La MISMA orden:** cantidad, precio de entrada, stop y objetivo de la orden de papel.
2. Antes de enviar, el motor de riesgo entero con el estado del DEMO: lo hace el servicio con `Copiar`.
3. **Caducidad con reloj propio:** la misma regla que el papel. La orden se crea con la hora de APERTURA de la vela que
   decide (`created_ts_ms`), se puede llenar en las 3 velas siguientes y caduca al cierre de la tercera
   (`portfolio.paper.ENTRY_BARS_TO_LIVE` = 2 velas SIN llenarse): vive hasta `creada + (2 + 2) velas`.
4. **Salidas que no son stop ni objetivo** (`news`, `manual`): se vende a mercado lo que tenga el demo de esa decision.

Y lo que el espejo anyade por su cuenta, porque sin ello no seria un espejo:
- **Lo que el papel CANCELA, el demo tambien** (un modo de solo cierre o una pausa cancelan en papel las entradas
  pendientes: PRD 5).
- **Solo las decisiones posteriores al arranque del ejecutor** (la foto del saldo): las de antes no se copian.
- **Solo los pares operables** (`execution.comisiones.operables`: en el demo, BTC, ETH, SOL y DOGE).
- Cada decision se copia u omite UNA vez: el servicio guarda las ya tratadas.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from portfolio.paper import ENTRY_BARS_TO_LIVE

# Velas que vive una entrada desde su `created_ts_ms` (la apertura de la vela que decide): esa vela, mas las
# ENTRY_BARS_TO_LIVE que puede esperar sin llenarse, mas la ultima en la que aun se puede llenar.
VELAS_DE_VIDA = ENTRY_BARS_TO_LIVE + 2
SALIDAS_A_MERCADO = frozenset({"news", "manual"})   # portfolio.paper.ExitReason: lo que no cierra la OCO


class Que(StrEnum):
    VENDER = "vender"          # cancelar la OCO y vender a mercado lo que haya
    CANCELAR = "cancelar"      # la entrada del demo: caducada o cancelada en papel
    COPIAR = "copiar"          # nueva: pasar el motor de riesgo y, si aprueba, enviar
    OMITIR = "omitir"          # no se copia nunca (se apunta por que)


@dataclass(frozen=True, slots=True)
class OrdenPapel:
    decision_id: str
    simbolo: str
    cantidad: float
    entrada: float
    stop: float
    objetivo: float
    creada_ms: int
    estado: str                # pending | filled | expired | cancelled
    setup: str = ""            # lo pide el motor de riesgo (paper_orders.setup)


@dataclass(frozen=True, slots=True)
class CierrePapel:
    decision_id: str
    motivo: str                # stop | target | news | manual | cancelled


@dataclass(frozen=True, slots=True)
class Demo:
    """Lo que el ejecutor ya tiene (de su base, corregido por la conciliacion)."""

    entradas_vivas: frozenset[str] = frozenset()     # decision_id con entrada pendiente en OKX
    posiciones: frozenset[str] = frozenset()         # decision_id con posicion abierta en el demo
    tratadas: frozenset[str] = frozenset()           # ya copiadas u omitidas (no se vuelven a mirar)
    vendiendo: frozenset[str] = frozenset()          # salida ya pedida


@dataclass(frozen=True, slots=True)
class Accion:
    que: Que
    decision_id: str
    motivo: str = ""
    orden: OrdenPapel | None = None


def vence_ms(creada_ms: int, tf_ms: int) -> int:
    return creada_ms + VELAS_DE_VIDA * tf_ms


def decidir(ordenes: Iterable[OrdenPapel], cierres: Iterable[CierrePapel], demo: Demo, *,
            operables: Iterable[str], arranque_ms: int, ahora_ms: int, tf_ms: int) -> list[Accion]:
    """Las acciones de esta vuelta: primero vender, despues cancelar, al final copiar."""
    operables = set(operables)
    ordenes = list(ordenes)
    vender, cancelar, copiar = [], [], []

    for c in cierres:
        if c.motivo in SALIDAS_A_MERCADO and c.decision_id in demo.posiciones and c.decision_id not in demo.vendiendo:
            vender.append(Accion(Que.VENDER, c.decision_id, f"cerrada en papel por {c.motivo}"))

    por_id = {o.decision_id: o for o in ordenes}
    for did in sorted(demo.entradas_vivas):
        o = por_id.get(did)
        if o is not None and o.estado == "cancelled":
            cancelar.append(Accion(Que.CANCELAR, did, "cancelada en papel (modo de solo cierre o pausa)"))
        elif o is not None and ahora_ms >= vence_ms(o.creada_ms, tf_ms):
            cancelar.append(Accion(Que.CANCELAR, did, f"caducada: {VELAS_DE_VIDA - 1} velas sin llenarse"))

    for o in sorted(ordenes, key=lambda x: (x.creada_ms, x.decision_id)):
        if o.decision_id in demo.tratadas:
            continue
        if o.creada_ms + tf_ms < arranque_ms:
            copiar.append(Accion(Que.OMITIR, o.decision_id, "decidida antes del arranque del ejecutor", o))
        elif o.simbolo not in operables:
            copiar.append(Accion(Que.OMITIR, o.decision_id, f"{o.simbolo} no se opera en el demo", o))
        elif o.estado == "cancelled":
            copiar.append(Accion(Que.OMITIR, o.decision_id, "cancelada en papel antes de copiarla", o))
        elif ahora_ms >= vence_ms(o.creada_ms, tf_ms):
            copiar.append(Accion(Que.OMITIR, o.decision_id, "caducada antes de copiarla", o))
        else:
            copiar.append(Accion(Que.COPIAR, o.decision_id, orden=o))
    return vender + cancelar + copiar
