"""De lo que decide la conciliacion a las peticiones que hay que mandar (fase 4, piezas 4 y 5).

PURO: recibe el `Resultado` de `execution.conciliacion.conciliar` y devuelve un `Plan`: las peticiones
a OKX, EN ORDEN y ya pasadas por la guardia (con `execution.peticiones`), y los pasos que solo tocan lo
local (apuntar un llenado, olvidar una entrada...). Mandarlas y apuntar las respuestas es de otra pieza.

Tres reglas:
- **Regla 13 primero.** CREAR_OCO: la OCO por la cantidad que HAY en OKX, con el stop y el objetivo de
  la decision. AJUSTAR_OCO: primero cancelar la que no cubre y despues crear la buena (el mismo
  `algoClOrdId` se puede reutilizar cuando la anterior ya esta cancelada).
- **Entrada a medias: cancelar el resto, lo PRIMERO** (decision del propietario del 02/10). Hasta entonces lo llenado no tiene
  stop; al cancelar, OKX crea la OCO adjunta por lo llenado. Va delante de todo lo demas.
- **Una posicion no bloquea a las demas.** Si a una le faltan el stop y el objetivo, o la guardia
  rechaza su OCO, se apunta (para avisar: es una posicion SIN proteccion) y las demas siguen.
- **Nada de adivinar precios.** El stop y el objetivo salen de lo que se decidio (lo pasa quien llama,
  de su journal); si no estan, no se inventan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from execution import peticiones
from execution.conciliacion import Accion, Paso, Resultado
from execution.guardia import PeticionRechazada

CANCELAR_OCO, CREAR_OCO, CANCELAR_RESTO = "cancelar_oco", "crear_oco", "cancelar_resto"
SOLO_LOCAL = frozenset({Accion.APUNTAR_LLENADO, Accion.ADOPTAR_ENTRADA, Accion.ADOPTAR_POSICION,
                        Accion.OLVIDAR_ENTRADA, Accion.CERRAR_LOCAL})


@dataclass(frozen=True, slots=True)
class Envio:
    que: str                     # cancelar_resto | cancelar_oco | crear_oco
    decision_id: str
    simbolo: str
    peticion: dict[str, Any]


@dataclass
class Plan:
    envios: list[Envio] = field(default_factory=list)
    locales: list[Paso] = field(default_factory=list)
    # decision_id -> por que su posicion se queda SIN OCO en esta pasada. Hay que avisar.
    sin_proteger: dict[str, str] = field(default_factory=dict)


def planear(resultado: Resultado, *, precios: Mapping[str, tuple[float, float]], ex: Any,
            whitelist: Iterable[str]) -> Plan:
    """`precios`: decision_id -> (stop, objetivo), ya al tick. `ex`: ccxt con los mercados cargados."""
    whitelist = tuple(whitelist)
    plan = Plan()
    for paso in resultado.acciones:
        if paso.accion in SOLO_LOCAL:
            plan.locales.append(paso)
            continue
        if paso.accion is Accion.CANCELAR_RESTO:
            try:
                cancelar = peticiones.cancelar_entrada(decision_id=paso.decision_id, simbolo=paso.simbolo,
                                                       whitelist=whitelist)
            except PeticionRechazada as exc:
                plan.sin_proteger[paso.decision_id] = f"no se puede cancelar el resto: {exc}"
                continue
            plan.envios.insert(sum(e.que == CANCELAR_RESTO for e in plan.envios),
                               Envio(CANCELAR_RESTO, paso.decision_id, paso.simbolo, cancelar))
            continue
        if paso.accion not in (Accion.CREAR_OCO, Accion.AJUSTAR_OCO):
            raise ValueError(f"accion sin tratar: {paso.accion}")
        if paso.decision_id not in precios:
            plan.sin_proteger[paso.decision_id] = "sin stop ni objetivo apuntados para esta decision"
            continue
        stop, objetivo = precios[paso.decision_id]
        try:
            crear = peticiones.proteccion(ex, decision_id=paso.decision_id, simbolo=paso.simbolo,
                                          cantidad=paso.cantidad, stop=stop, objetivo=objetivo,
                                          whitelist=whitelist)
            cancelar = (peticiones.cancelar_oco(decision_id=paso.decision_id, simbolo=paso.simbolo,
                                                whitelist=whitelist)
                        if paso.accion is Accion.AJUSTAR_OCO else None)
        except PeticionRechazada as exc:
            plan.sin_proteger[paso.decision_id] = f"la guardia no la deja salir: {exc}"
            continue
        if cancelar is not None:
            plan.envios.append(Envio(CANCELAR_OCO, paso.decision_id, paso.simbolo, cancelar))
        plan.envios.append(Envio(CREAR_OCO, paso.decision_id, paso.simbolo, crear))
    return plan
