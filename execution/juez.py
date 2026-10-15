"""El juez de la fase 4 (pieza 8): "1 semana sin descuadres" en el demo, con juez como las 72 h.

PURO, como el resto de piezas: recibe lo que dice OKX (el historial de ordenes, OCO, fills y los saldos al
principio y al final de la ventana) y lo que apunto el bot (sus operaciones y cada pasada de la
conciliacion), y devuelve las FALLAS. Pedirle el historial a OKX (con la clave de solo lectura y
trading) y leer la base del ejecutor es de `scripts/check_exec.py`, que se escribe con el ejecutor.

**No reutiliza el codigo del ejecutor** (`conciliacion`, `plan`, `peticiones`, `equity`): si el juez
razonara con la misma logica, un error compartido pasaria sin que nadie lo viera. Solo usa `ids`, que
no es logica sino el contrato de los identificadores (y el juez comprueba aparte que no choquen). Hay
un test de arquitectura que lo vigila.

Lo que se mide (docs/archivo/diseno-fase-4.md, decisiones 1, 3 y 5 del propietario):

1. **La guardia, vista desde OKX**: toda orden y toda OCO en `cash` (regla 1) y de la whitelist
   (regla 3); las entradas, compras post-only (decision 3); las OCO, ventas; y la unica otra orden, la
   VENTA A MERCADO de salida (sufijo `SAL`; flag critica de noticias o "cerrar todo", decision del 02/10):
   como mucho una por decision, de una decision que compro, y que la cartera de la IA cerro en papel por
   ese motivo (`salidas_espejo`) O que se vendio con el precio ya pasado su stop o su objetivo (decision de
   el propietario del 03/10: OKX rechaza crear una OCO asi); eso se mira con el precio del llenado y los niveles de la
   orden de papel (`niveles`), no con lo que apunto el bot.
2. **Ids**: ninguna orden ajena, y una sola entrada por decision (consultar antes de reenviar).
3. **Espejo** (decision 1): cada orden del demo es una que la cartera de la IA envio en papel, o una de las posiciones
   de papel que estaban ABIERTAS en la foto y se adoptaron una sola vez para arrancar la fase 4 (`adoptadas`,
   decision del propietario del 03/10: su entrada es una compra limit que cruza, no post-only; se cuentan aparte). Las que
   el demo no llego a mandar (post-only rechazada, par que el demo no tiene, DEGRADED) se cuentan.
4. **Proteccion** (regla 13 y decision 5): desde el primer fill hasta la salida, la posicion tiene una
   OCO viva por la cantidad llenada. Se admite un hueco de hasta DOS pasadas (10 min): la primera
   pasada puede encontrarla sin OCO y crearla; si a la siguiente sigue sin, es un descuadre.
5. **Fills contra lo local**: cantidad y precio medio de entrada y de salida de cada operacion.
6. **Saldos**: lo que cambia cada moneda en OKX entre el principio y el final es EXACTAMENTE lo que
   explican nuestros fills (la comision va en USDC, decision 2: la moneda base es exacta). Un
   movimiento que no sale de un fill nuestro (una operacion a mano en la web del demo) es FALLA.
7. **La conciliacion corrio** cada pasada (sin huecos de mas de 3 pasadas) y **no apunto ningun
   descuadre**: un juez que no ve no aprueba.
8. **Hubo actividad** (decision del propietario del 03/10): como minimo UNA operacion completa en el demo (compra llenada,
   protegida por su OCO y cerrada). Sin eso, siete dias sin descuadres no prueban nada de las ordenes: sale 2 ("aun
   no") hasta que la haya, aunque pasen los siete dias.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from execution import ids

PASADA_MS = 5 * 60_000
MAX_SIN_OCO_MS = 2 * PASADA_MS        # una pasada la encuentra sin OCO y la crea; la segunda, ya es descuadre
MAX_HUECO_PASADAS_MS = 3 * PASADA_MS  # un reinicio (el de las 07:15) tarda 1-2 min
SEMANA_MS = 7 * 24 * 3600_000
MIN_COMPLETAS = 1                     # decision del propietario del 03/10: la semana solo vale con actividad
TOLERANCIA_USDC = 0.01
TOLERANCIA_PRECIO = 1e-6              # relativa: los precios salen de los mismos fills
TOLERANCIA_NIVEL = 0.002              # relativa: el demo redondea stop y objetivo a su tick (ETH: 1 $)


# --- Lo que dice OKX -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Orden:
    """Una orden normal de OKX (historial): las nuestras son las entradas."""
    cl_ord_id: str
    simbolo: str
    lado: str             # buy | sell
    tipo: str             # ordType de OKX: post_only, limit, market...
    td_mode: str
    cantidad: float
    llenado: float
    estado: str           # live | partially_filled | filled | canceled
    creada_ms: int


@dataclass(frozen=True, slots=True)
class Oco:
    """Una OCO (orden algoritmica). Varias por decision si se cancelo y se volvio a crear."""
    algo_cl_ord_id: str
    simbolo: str
    lado: str
    td_mode: str
    cantidad: float
    estado: str           # live | effective (salto) | canceled
    creada_ms: int
    fin_ms: int | None    # cuando dejo de estar viva (salto o se cancelo); None si sigue viva


@dataclass(frozen=True, slots=True)
class Fill:
    """Un llenado. `id_propio`: el clOrdId de la entrada o el algoClOrdId de la OCO que lo produjo."""
    id_propio: str
    simbolo: str
    lado: str
    cantidad: float
    precio: float
    comision_usdc: float  # lo pagado, en positivo
    ts_ms: int


@dataclass(frozen=True, slots=True)
class Okx:
    ordenes: tuple[Orden, ...]
    ocos: tuple[Oco, ...]
    fills: tuple[Fill, ...]
    saldos_inicio: Mapping[str, float]   # moneda -> total ("USDC", "BTC"...), al empezar la ventana
    saldos_fin: Mapping[str, float]


# --- Lo que apunto el bot --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Operacion:
    decision_id: str
    simbolo: str
    cantidad_entrada: float
    precio_entrada: float
    cantidad_salida: float = 0.0          # 0 mientras sigue abierta
    precio_salida: float | None = None


@dataclass(frozen=True, slots=True)
class Pasada:
    ts_ms: int
    descuadres: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Bot:
    operaciones: tuple[Operacion, ...]
    pasadas: tuple[Pasada, ...]


# --- El veredicto ----------------------------------------------------------------------


@dataclass
class Veredicto:
    fallas: list[str] = field(default_factory=list)
    medidas: dict[str, int] = field(default_factory=dict)
    cubierto_ms: int = 0
    completas: int = 0                    # operaciones completas (compra, OCO, cierre) en la ventana

    @property
    def codigo(self) -> int:
        """0 cumplido, 1 FALLA, 2 todo en orden pero aun no hay una semana, o no ha habido ninguna operacion completa."""
        if self.fallas:
            return 1
        return 0 if self.cubierto_ms >= SEMANA_MS and self.completas >= MIN_COMPLETAS else 2


def _decision(id_okx: str) -> str | None:
    try:
        return ids.decision_id_de(id_okx)
    except ids.IdInvalido:
        return None


def _base(simbolo: str) -> str:
    return simbolo.split("/", 1)[0]


def _hora(ms: int) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%d/%m %H:%M")


def juzgar(okx: Okx, bot: Bot, *, whitelist: Iterable[str], lotes: Mapping[str, float],
           espejo: Iterable[str], hasta_ms: int, salidas_espejo: Iterable[str] = (),
           niveles: Mapping[str, tuple[float, float]] | None = None, adoptadas: Iterable[str] = ()) -> Veredicto:
    """`espejo`: los decision_id que la cartera de la IA envio en papel en la ventana (en los pares
    del demo). `salidas_espejo`: los que esa cartera cerro en papel por algo que no es stop ni objetivo.
    `niveles`: decision_id -> (stop, objetivo) de la orden de papel.
    `hasta_ms`: el final de la ventana (cuando se pidio el historial)."""
    v = Veredicto()
    permitidos = set(whitelist)
    espejo = set(espejo)
    salidas_espejo = set(salidas_espejo)
    adoptadas = set(adoptadas)

    def media_lote(simbolo: str) -> float:
        return lotes.get(simbolo, 0.0) / 2

    # 1. La guardia, desde OKX.
    for o in okx.ordenes:
        if o.td_mode != "cash":
            v.fallas.append(f"regla 1: la orden {o.cl_ord_id} va en '{o.td_mode}', no en cash")
        if o.simbolo not in permitidos:
            v.fallas.append(f"regla 3: la orden {o.cl_ord_id} es de {o.simbolo}, fuera de la whitelist")
        if ids.es_salida(o.cl_ord_id):
            if o.lado != "sell" or o.tipo != "market":
                v.fallas.append(f"la orden {o.cl_ord_id} es '{o.lado} {o.tipo}': las salidas son ventas a mercado")
        elif o.lado != "buy" or o.tipo not in (("post_only", "limit") if _decision(o.cl_ord_id) in adoptadas
                                               else ("post_only",)):
            v.fallas.append(f"la orden {o.cl_ord_id} es '{o.lado} {o.tipo}': las entradas son compras post-only")
    for a in okx.ocos:
        if a.td_mode != "cash":
            v.fallas.append(f"regla 1: la OCO {a.algo_cl_ord_id} va en '{a.td_mode}', no en cash")
        if a.simbolo not in permitidos:
            v.fallas.append(f"regla 3: la OCO {a.algo_cl_ord_id} es de {a.simbolo}, fuera de la whitelist")
        if a.lado != "sell":
            v.fallas.append(f"la OCO {a.algo_cl_ord_id} es '{a.lado}': las OCO venden")

    # 2. Ids: nada ajeno, una sola entrada por decision, y los ids no chocan.
    entradas: dict[str, list[Orden]] = defaultdict(list)
    salidas: dict[str, list[Orden]] = defaultdict(list)
    for o in okx.ordenes:
        did = _decision(o.cl_ord_id)
        if did is None or o.cl_ord_id.endswith(ids.SUFIJO_OCO):
            v.fallas.append(f"orden ajena en OKX: {o.cl_ord_id} ({o.simbolo})")
            continue
        (salidas if ids.es_salida(o.cl_ord_id) else entradas)[did].append(o)
    for did, lista in sorted(salidas.items()):
        if len(lista) > 1:
            v.fallas.append(f"{did}: {len(lista)} ventas de salida para una sola decision")
        if did not in entradas:
            v.fallas.append(f"{did}: venta de salida de una decision sin entrada en el demo")
        # Si la IA no la hizo en papel, se mira despues con el precio del llenado (precio ya pasado).
    for did, lista in sorted(entradas.items()):
        if len(lista) > 1:
            v.fallas.append(f"{did}: {len(lista)} entradas en OKX para una sola decision")
    ocos: dict[str, list[Oco]] = defaultdict(list)
    for a in okx.ocos:
        did = _decision(a.algo_cl_ord_id)
        if did is None or not a.algo_cl_ord_id.endswith(ids.SUFIJO_OCO):
            v.fallas.append(f"OCO ajena en OKX: {a.algo_cl_ord_id} ({a.simbolo})")
            continue
        ocos[did].append(a)
    propios = {did: ids.cl_ord_id(did) for did in entradas}
    if len(set(propios.values())) != len(propios):
        v.fallas.append("dos decisiones distintas dan el mismo clOrdId")

    # 3. El espejo de la cartera de la IA.
    for did in sorted(entradas):
        if did not in espejo and did not in adoptadas:
            v.fallas.append(f"{did}: orden en el demo que la cartera de la IA no envio")
    v.medidas["enviadas en papel"] = len(espejo)
    v.medidas["mandadas al demo"] = len(set(entradas) & espejo)
    v.medidas["adoptadas"] = len(set(entradas) & adoptadas)
    v.medidas["salidas a mercado"] = len(salidas)

    # Los fills, por decision y lado.
    compras: dict[str, list[Fill]] = defaultdict(list)
    ventas: dict[str, list[Fill]] = defaultdict(list)
    for f in okx.fills:
        did = _decision(f.id_propio)
        if did is None:
            v.fallas.append(f"fill ajeno en OKX: {f.id_propio} {f.lado} {f.cantidad} {f.simbolo}")
            continue
        (compras if f.lado == "buy" else ventas)[did].append(f)
        de_la_entrada = not f.id_propio.endswith(ids.SUFIJOS)
        if (f.lado == "buy") != de_la_entrada:   # se compra con la entrada; se vende con la OCO o con la salida
            v.fallas.append(f"{did}: fill de {f.lado} que no sale de donde deberia ({f.id_propio})")

    # La salida que no hizo la cartera de papel solo vale con el precio ya pasado su stop o su objetivo.
    niveles = niveles or {}
    v.medidas["salidas por precio pasado"] = 0
    for did in sorted(salidas):
        if did in salidas_espejo:
            continue
        fs = [f for f in ventas.get(did, ()) if ids.es_salida(f.id_propio)]
        total = sum(f.cantidad for f in fs)
        medio = sum(f.cantidad * f.precio for f in fs) / total if total > 0 else None
        stop, objetivo = niveles.get(did, (None, None))
        if medio is not None and stop is not None and (
                medio <= stop * (1 + TOLERANCIA_NIVEL) or medio >= objetivo * (1 - TOLERANCIA_NIVEL)):
            v.medidas["salidas por precio pasado"] += 1
        else:
            v.fallas.append(f"{did}: venta de salida que la cartera de la IA no hizo en papel"
                            + ("" if medio is None else f" (a {medio:g}, entre stop {stop} y objetivo {objetivo})"))

    # 4. Proteccion: la posicion (primer fill de compra -> ultimo de venta) cubierta por una OCO viva.
    for did, fs in sorted(compras.items()):
        simbolo = fs[0].simbolo
        desde = min(f.ts_ms for f in fs)
        llenado = sum(f.cantidad for f in fs)
        vendido = sum(f.cantidad for f in ventas.get(did, ()))
        cerrada = bool(ventas.get(did)) and vendido >= llenado - media_lote(simbolo)
        hasta = max(f.ts_ms for f in ventas[did]) if cerrada else hasta_ms
        tramos = sorted((a.creada_ms, a.fin_ms if a.fin_ms is not None else hasta_ms) for a in ocos.get(did, ()))
        cursor, peor = desde, 0
        for ini, fin in tramos:
            if fin <= cursor:
                continue
            peor = max(peor, ini - cursor)
            cursor = max(cursor, fin)
            if cursor >= hasta:
                break
        peor = max(peor, hasta - cursor)
        if cerrada and ocos.get(did):
            v.completas += 1
        if peor > MAX_SIN_OCO_MS:
            v.fallas.append(f"{did}: {peor // 60_000} min sin OCO con la posicion abierta "
                            f"(maximo {MAX_SIN_OCO_MS // 60_000})")
        # La ultima OCO de la posicion tiene que cubrir lo llenado (la de un llenado parcial se ajusta).
        vivas = [a for a in ocos.get(did, ()) if a.estado in ("live", "effective")]
        if vivas:
            ultima = max(vivas, key=lambda a: a.creada_ms)
            if abs(ultima.cantidad - llenado) > media_lote(simbolo):
                v.fallas.append(f"{did}: la OCO cubre {ultima.cantidad:g} y se lleno {llenado:g}")

    # 5. Los fills contra lo que apunto el bot.
    locales = {op.decision_id: op for op in bot.operaciones}
    for did in sorted(set(compras) | set(locales)):
        op, fs = locales.get(did), compras.get(did, [])
        if op is None:
            v.fallas.append(f"{did}: OKX tiene fills y el bot no tiene la operacion")
            continue
        if not fs:
            v.fallas.append(f"{did}: el bot tiene la operacion y OKX no tiene ningun fill")
            continue
        _cuadra(v, did, "entrada", op.simbolo, fs, op.cantidad_entrada, op.precio_entrada, media_lote(op.simbolo))
        vs = ventas.get(did, [])
        if op.cantidad_salida > 0:
            _cuadra(v, did, "salida", op.simbolo, vs, op.cantidad_salida, op.precio_salida, media_lote(op.simbolo))
        elif any(f.ts_ms <= hasta_ms - PASADA_MS for f in vs):
            # Una salida de la ultima pasada puede no estar apuntada aun: la conciliacion la ve en la siguiente.
            v.fallas.append(f"{did}: OKX vendio y el bot la sigue teniendo abierta")

    # 6. Los saldos se mueven solo por nuestros fills.
    delta: dict[str, float] = defaultdict(float)
    for f in okx.fills:
        signo = 1 if f.lado == "buy" else -1
        delta[_base(f.simbolo)] += signo * f.cantidad
        delta["USDC"] += -signo * f.cantidad * f.precio - f.comision_usdc
    for moneda in sorted(set(okx.saldos_inicio) | set(okx.saldos_fin) | set(delta)):
        real = okx.saldos_fin.get(moneda, 0.0) - okx.saldos_inicio.get(moneda, 0.0)
        if moneda == "USDC":
            tolerancia = TOLERANCIA_USDC
        else:
            tolerancia = max((media_lote(s) for s in permitidos if _base(s) == moneda), default=0.0)
        if abs(real - delta[moneda]) > tolerancia + 1e-12:
            v.fallas.append(f"saldo de {moneda}: cambio {real:+.8g} en OKX y nuestros fills explican "
                            f"{delta[moneda]:+.8g}")

    # 7. La conciliacion corrio y no apunto descuadres.
    pasadas = sorted(bot.pasadas, key=lambda p: p.ts_ms)
    if not pasadas:
        v.fallas.append("la conciliacion no ha corrido nunca")
        return v
    for anterior, siguiente in zip(pasadas, pasadas[1:], strict=False):
        if siguiente.ts_ms - anterior.ts_ms > MAX_HUECO_PASADAS_MS:
            v.fallas.append(f"sin conciliar {(siguiente.ts_ms - anterior.ts_ms) // 60_000} min "
                            f"desde {_hora(anterior.ts_ms)}")
    if hasta_ms - pasadas[-1].ts_ms > MAX_HUECO_PASADAS_MS:
        v.fallas.append(f"sin conciliar desde {_hora(pasadas[-1].ts_ms)}")
    for p in pasadas:
        for d in p.descuadres:
            v.fallas.append(f"descuadre de la conciliacion a las {_hora(p.ts_ms)}: {d}")
    v.medidas["pasadas"] = len(pasadas)
    v.medidas["operaciones completas"] = v.completas
    v.cubierto_ms = pasadas[-1].ts_ms - pasadas[0].ts_ms
    return v


def _cuadra(v: Veredicto, did: str, que: str, simbolo: str, fs: list[Fill], cantidad: float,
            precio: float | None, tolerancia: float) -> None:
    total = sum(f.cantidad for f in fs)
    if abs(total - cantidad) > tolerancia:
        v.fallas.append(f"{did}: {que} de {total:g} en OKX y {cantidad:g} en el bot")
        return
    if total <= 0:
        return
    medio = sum(f.cantidad * f.precio for f in fs) / total
    if precio is None or abs(medio - precio) > TOLERANCIA_PRECIO * medio:
        v.fallas.append(f"{did}: precio de {que} {medio:.8g} en OKX y {precio} en el bot")
