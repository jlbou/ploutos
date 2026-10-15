"""Conciliacion: el exchange contra lo local, al arrancar y cada 5 min (fase 4, pieza 5).

PURO: recibe dos fotos (lo que cree el bot y lo que dice OKX) y devuelve que hacer y que
no cuadra. Pedir las fotos a OKX y aplicar las acciones es de otras piezas.

LAS REGLAS (docs/archivo/diseno-fase-4.md, PRD 13, decision 5 del propietario del 24/09/2026):
- **Gana el exchange.** Lo local se corrige para que diga lo mismo que OKX.
- Lo que la conciliacion EXPLICA en la misma pasada no es un descuadre: una entrada que se
  lleno mientras el proceso estaba muerto, una OCO que salto, una orden nuestra que el
  proceso envio y no llego a apuntar (se encuentra por su `clOrdId`).
- **Descuadre** = lo que no se explica (una orden o una OCO que no es nuestra, un saldo que
  no cuadra, una posicion que desaparece sin OCO que la cierre), o una posicion SIN OCO
  durante mas de una pasada (la primera vez se crea; si a la siguiente sigue sin, es un
  descuadre). Eso es lo que cuenta el criterio "1 semana sin descuadres".
- Las ordenes se reconocen por su id (`execution/ids.py`): `clOrdId` para la entrada y
  `algoClOrdId` (sufijo OCO) para su proteccion. Un id que no es nuestro no se toca: se avisa.
- Las cantidades se comparan con media unidad de lote de margen; la comision va en USDC
  (decision 2 de la fase 4), asi que la cantidad de la moneda base es exacta.
- **Entrada llenada A MEDIAS (decision del propietario del 02/10):** se cancela el resto EN EL MOMENTO y NO se crea una OCO
  propia. La entrada lleva su stop y objetivo adjuntos con nuestro `algoClOrdId`, y OKX crea esa OCO al cancelar el
  resto (prueba 4 del demo). Una OCO propia con el mismo id chocaria con la que OKX va a crear (o venderia dos veces
  lo mismo). Si en la pasada siguiente sigue sin OCO, se crea la propia y es un descuadre (no se explica).
- **La venta a mercado de salida** (sufijo `SAL`, decision del 02/10) explica que una posicion desaparezca sin que
  salte su OCO: se cierra en local sin descuadre. Una salida no es nunca una entrada (no se adopta).
- **Los saldos que recibe son los del BOT** (`execution.equity.virtual`, saldo virtual del 02/10), no los de la cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from execution import ids


class Accion(StrEnum):
    APUNTAR_LLENADO = "apuntar_llenado"     # la entrada se lleno (entera o en parte)
    ADOPTAR_ENTRADA = "adoptar_entrada"     # orden nuestra en OKX que lo local no tenia
    ADOPTAR_POSICION = "adoptar_posicion"   # OCO nuestra viva sin posicion local
    OLVIDAR_ENTRADA = "olvidar_entrada"     # cancelada o caducada en OKX, o nunca llego
    CANCELAR_RESTO = "cancelar_resto"       # entrada a medias: cancelar lo que falta (OKX crea la OCO adjunta)
    CREAR_OCO = "crear_oco"                 # posicion sin proteccion (regla 13)
    AJUSTAR_OCO = "ajustar_oco"             # la OCO no cubre la cantidad que hay
    CERRAR_LOCAL = "cerrar_local"           # la posicion ya no existe en OKX


class Descuadre(StrEnum):
    ORDEN_AJENA = "orden_ajena"             # una orden abierta que no es nuestra
    OCO_AJENA = "oco_ajena"
    SIN_OCO_REPETIDO = "sin_oco_repetido"   # sin OCO mas de una pasada
    CIERRE_SIN_EXPLICAR = "cierre_sin_explicar"   # la moneda se fue sin que saltara la OCO
    SALDO_BASE = "saldo_base"               # la cantidad de una moneda no cuadra
    SALDO_USDC = "saldo_usdc"


# --- Las dos fotos -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntradaLocal:
    decision_id: str
    simbolo: str
    cantidad: float


@dataclass(frozen=True, slots=True)
class PosicionLocal:
    decision_id: str
    simbolo: str
    cantidad: float


@dataclass(frozen=True, slots=True)
class Local:
    entradas: tuple[EntradaLocal, ...] = ()
    posiciones: tuple[PosicionLocal, ...] = ()
    usdc: float = 0.0


@dataclass(frozen=True, slots=True)
class OrdenEx:
    """Una orden de OKX: las abiertas y las cerradas recientes."""

    cl_ord_id: str
    simbolo: str
    cantidad: float
    llenado: float
    estado: str          # live | partially_filled | filled | canceled


@dataclass(frozen=True, slots=True)
class OcoEx:
    algo_cl_ord_id: str
    simbolo: str
    cantidad: float
    estado: str                      # live | effective (salto) | canceled
    pata: str | None = None          # sl | tp, si salto
    precio_salida: float | None = None


@dataclass(frozen=True, slots=True)
class Exchange:
    saldos: dict[str, float]         # moneda base -> cantidad total ("NEAR" -> 1,5)
    usdc: float
    ordenes: tuple[OrdenEx, ...] = ()
    ocos: tuple[OcoEx, ...] = ()


# --- El resultado --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paso:
    accion: Accion
    decision_id: str
    simbolo: str
    cantidad: float = 0.0
    detalle: str = ""


@dataclass(frozen=True, slots=True)
class Fallo:
    tipo: Descuadre
    detalle: str


@dataclass
class Resultado:
    acciones: list[Paso] = field(default_factory=list)
    descuadres: list[Fallo] = field(default_factory=list)
    # Las posiciones que se quedan sin OCO en esta pasada: se pasan a la siguiente.
    sin_oco: frozenset[str] = frozenset()

    @property
    def cuadra(self) -> bool:
        return not self.descuadres


def _decision(id_okx: str) -> str | None:
    try:
        return ids.decision_id_de(id_okx)
    except ids.IdInvalido:
        return None


def _base(simbolo: str) -> str:
    return simbolo.split("/", 1)[0]


def conciliar(
    local: Local, ex: Exchange, *, lotes: dict[str, float],
    sin_oco_antes: frozenset[str] = frozenset(), tolerancia_usdc: float = 0.01,
) -> Resultado:
    """Una pasada. `lotes`: tamanyo de lote por simbolo; `sin_oco_antes`: de la pasada anterior."""
    r = Resultado()

    def igual(simbolo: str, a: float, b: float) -> bool:
        return abs(a - b) < lotes[simbolo] / 2

    ordenes = {o.cl_ord_id: o for o in ex.ordenes}
    vendidas = {o.cl_ord_id for o in ex.ordenes if ids.es_salida(o.cl_ord_id) and o.llenado > 0}
    ocos_vivas = {o.algo_cl_ord_id: o for o in ex.ocos if o.estado == "live"}
    ocos_saltadas = {o.algo_cl_ord_id: o for o in ex.ocos if o.estado == "effective"}

    # Lo que deberia haber de cada moneda base despues de esta pasada, segun lo local
    # corregido. Al final se compara con el saldo de OKX.
    esperado: dict[str, float] = {}
    # Posiciones que tienen que estar protegidas: decision_id -> (simbolo, cantidad).
    a_proteger: dict[str, tuple[str, float]] = {}
    toca_caja = False
    # Entradas a medias: se cancela el resto y la OCO la crea OKX (no se protegen aqui en esta pasada).
    cancelando: set[str] = set()

    def a_medias(did: str, o: OrdenEx) -> None:
        nonlocal toca_caja
        r.acciones.append(Paso(Accion.APUNTAR_LLENADO, did, o.simbolo, o.llenado,
                               f"{o.estado}: {o.llenado} de {o.cantidad}"))
        r.acciones.append(Paso(Accion.CANCELAR_RESTO, did, o.simbolo, o.cantidad - o.llenado,
                               "a medias: OKX crea la OCO adjunta por lo llenado al cancelar"))
        toca_caja = True
        cancelando.add(did)
        esperado[_base(o.simbolo)] = esperado.get(_base(o.simbolo), 0.0) + o.llenado

    # 1. Entradas locales pendientes.
    conocidas = set()
    for e in local.entradas:
        conocidas.add(e.decision_id)
        o = ordenes.get(ids.cl_ord_id(e.decision_id))
        if o is None:
            r.acciones.append(Paso(Accion.OLVIDAR_ENTRADA, e.decision_id, e.simbolo,
                                   detalle="OKX no la conoce: nunca llego"))
            continue
        if o.llenado > 0 and o.estado == "partially_filled":
            a_medias(e.decision_id, o)
        elif o.llenado > 0:
            r.acciones.append(Paso(Accion.APUNTAR_LLENADO, e.decision_id, e.simbolo, o.llenado,
                                   f"{o.estado}: {o.llenado} de {o.cantidad}"))
            toca_caja = True
            a_proteger[e.decision_id] = (e.simbolo, o.llenado)
            esperado[_base(e.simbolo)] = esperado.get(_base(e.simbolo), 0.0) + o.llenado
        elif o.estado == "canceled":
            r.acciones.append(Paso(Accion.OLVIDAR_ENTRADA, e.decision_id, e.simbolo,
                                   detalle="cancelada o caducada sin llenarse"))

    # 2. Ordenes abiertas de OKX que lo local no tenia.
    for o in ex.ordenes:
        if o.estado not in ("live", "partially_filled"):
            continue
        did = _decision(o.cl_ord_id)
        if did is None:
            r.descuadres.append(Fallo(Descuadre.ORDEN_AJENA, f"{o.cl_ord_id} en {o.simbolo}"))
            continue
        if ids.es_salida(o.cl_ord_id):
            continue        # una venta a mercado en curso: se mira en el paso 3, cuando se haya llenado
        if did in conocidas:
            continue
        conocidas.add(did)
        r.acciones.append(Paso(Accion.ADOPTAR_ENTRADA, did, o.simbolo, o.cantidad,
                               "enviada y no apuntada (el proceso murio a mitad)"))
        if o.llenado > 0 and o.estado == "partially_filled":
            a_medias(did, o)
        elif o.llenado > 0:
            r.acciones.append(Paso(Accion.APUNTAR_LLENADO, did, o.simbolo, o.llenado, o.estado))
            toca_caja = True
            a_proteger[did] = (o.simbolo, o.llenado)
            esperado[_base(o.simbolo)] = esperado.get(_base(o.simbolo), 0.0) + o.llenado

    # 3. Posiciones locales.
    for p in local.posiciones:
        aid = ids.algo_cl_ord_id(p.decision_id)
        saltada = ocos_saltadas.get(aid)
        if aid in ocos_vivas or saltada is None:
            if aid not in ocos_vivas and ids.cl_ord_id_salida(p.decision_id) in vendidas:
                r.acciones.append(Paso(Accion.CERRAR_LOCAL, p.decision_id, p.simbolo, p.cantidad,
                                       "vendida a mercado (salida que no es stop ni objetivo)"))
                toca_caja = True
                continue
            if aid not in ocos_vivas and ex.saldos.get(_base(p.simbolo), 0.0) < lotes[p.simbolo] / 2:
                # Ni OCO viva, ni OCO que saltara, y la moneda ya no esta.
                r.descuadres.append(Fallo(Descuadre.CIERRE_SIN_EXPLICAR,
                                          f"{p.decision_id}: {p.simbolo} ya no esta y ninguna OCO salto"))
                r.acciones.append(Paso(Accion.CERRAR_LOCAL, p.decision_id, p.simbolo, p.cantidad,
                                       "precio de salida desconocido"))
                toca_caja = True
                continue
            a_proteger[p.decision_id] = (p.simbolo, p.cantidad)
            esperado[_base(p.simbolo)] = esperado.get(_base(p.simbolo), 0.0) + p.cantidad
        else:
            r.acciones.append(Paso(Accion.CERRAR_LOCAL, p.decision_id, p.simbolo, p.cantidad,
                                   f"salto la OCO ({saltada.pata}) a {saltada.precio_salida}"))
            toca_caja = True

    # 4. OCO vivas nuestras sin posicion local: se adopta la posicion (gana el exchange).
    locales = {p.decision_id for p in local.posiciones} | set(a_proteger) | cancelando
    for aid, o in ocos_vivas.items():
        did = _decision(aid)
        if did is None or not aid.endswith(ids.SUFIJO_OCO):
            r.descuadres.append(Fallo(Descuadre.OCO_AJENA, f"{aid} en {o.simbolo}"))
            continue
        if did not in locales:
            r.acciones.append(Paso(Accion.ADOPTAR_POSICION, did, o.simbolo, o.cantidad,
                                   "OCO viva sin posicion local"))
            toca_caja = True
            a_proteger[did] = (o.simbolo, o.cantidad)
            esperado[_base(o.simbolo)] = esperado.get(_base(o.simbolo), 0.0) + o.cantidad

    # 5. Cada posicion, con su OCO por la cantidad que hay (regla 13).
    sin_oco = set(cancelando)
    for did in sorted(cancelando & sin_oco_antes):
        r.descuadres.append(Fallo(Descuadre.SIN_OCO_REPETIDO,
                                  f"{did}: a medias y sin OCO desde la pasada anterior (no se cancelo el resto)"))
    for did, (simbolo, cantidad) in a_proteger.items():
        oco = ocos_vivas.get(ids.algo_cl_ord_id(did))
        if oco is None:
            sin_oco.add(did)
            r.acciones.append(Paso(Accion.CREAR_OCO, did, simbolo, cantidad))
            if did in sin_oco_antes:
                r.descuadres.append(Fallo(Descuadre.SIN_OCO_REPETIDO,
                                          f"{did}: sin OCO desde la pasada anterior"))
        elif not igual(simbolo, oco.cantidad, cantidad):
            r.acciones.append(Paso(Accion.AJUSTAR_OCO, did, simbolo, cantidad,
                                   f"la OCO cubre {oco.cantidad}"))
    r.sin_oco = frozenset(sin_oco)

    # 6. Saldos de cada moneda: lo que dice OKX contra lo esperado tras corregir.
    for simbolo in lotes:
        base = _base(simbolo)
        hay, debe = ex.saldos.get(base, 0.0), esperado.get(base, 0.0)
        if not igual(simbolo, hay, debe):
            r.descuadres.append(Fallo(Descuadre.SALDO_BASE, f"{base}: OKX {hay}, local {debe}"))

    # 7. USDC: solo si en esta pasada no ha cambiado nada que mueva caja. Si algo se lleno o
    #    se cerro, lo local se pone al dia al aplicar las acciones y se compara en la siguiente.
    if not toca_caja and abs(ex.usdc - local.usdc) > tolerancia_usdc:
        r.descuadres.append(Fallo(Descuadre.SALDO_USDC, f"OKX {ex.usdc:.4f}, local {local.usdc:.4f}"))
    return r
