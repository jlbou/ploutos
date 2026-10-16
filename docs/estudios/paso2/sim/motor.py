"""El motor del simulador del paso 2: lo que hace cada dia esta en `MOTOR.md` (del PRD v3 y del plan, secciones 8 y
11). Codigo de estudio; las reglas, con su numero del PRD."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sim import impuestos as imp

Serie = Mapping[str, Sequence[float]]


@dataclass(frozen=True)
class Parametros:
    capital: float = 10_000.0          # capital de referencia (decision 2: el techo de disenyo)
    suelo_pct: float | None = 0.50     # regla 5/7
    tope_moneda: float = 0.45          # regla 15: 90 % entre las dos
    riesgo: float | None = 0.05        # regla 12, techo por posicion
    exposicion: float = 0.90           # regla 15
    colchon_pct: float | None = 0.02   # regla 8 (None: sin regla 8)
    escalones: bool = True             # regla 9
    stops: bool = True                 # regla 13
    stop_atr: float = 3.0
    comision: float = 0.002            # taker real de BTC-EUR y ETH-EUR (V2)
    deslizamiento: float = 0.0001      # por lado, hasta V5
    min_orden: float = 5.0             # euros, si la moneda no tiene minimo de OKX conocido
    # C6 (16/10, comprobado con la cuenta real): el minimo por orden de OKX, en cantidad de la moneda.
    min_cantidad: Mapping[str, float] = field(default_factory=lambda: {"BTC": 0.0001, "ETH": 0.001})
    impuestos: bool = True
    reentrada: str = "senyal"          # C1: "senyal" (apagarse y encenderse) o "domingo" (H3)

    @classmethod
    def validacion(cls) -> Parametros:
        """Sin topes, sin stops, sin suelo, sin impuestos: comprar y mantener tiene que dar BTC mantenido."""
        return cls(suelo_pct=None, tope_moneda=1.0, riesgo=None, exposicion=1.0, colchon_pct=None, escalones=False,
                   stops=False, impuestos=False)


@dataclass
class Resultado:
    dias: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    operaciones: list[dict] = field(default_factory=list)
    impuestos: dict[int, float] = field(default_factory=dict)   # la cuota de cada anyo (lo que se debe)
    pagos: list[tuple[int, float]] = field(default_factory=list)  # (dia, importe) en que se paga
    invertido: list[float] = field(default_factory=list)     # fraccion del equity invertida al cierre
    enclavado: bool = False


def _es(t: int, dia_semana: int) -> bool:
    return datetime.fromtimestamp(t, UTC).weekday() == dia_semana


def _fin_de_anyo(t: int) -> bool:
    d = datetime.fromtimestamp(t, UTC)
    return d.month == 12 and d.day == 31


def simular(series: Mapping[str, Serie], fracciones: Mapping[str, Sequence[float]],
            atr: Mapping[str, Sequence[float | None]], desde: int, hasta: int, p: Parametros,
            efectivo_inicial: float | None = None) -> Resultado:
    """Simula los dias desde..hasta (indices, incluidos; la primera orden usa la senyal de desde-1). Todas las series
    tienen las mismas fechas. Solo devuelve resultados de esa ventana (la guardia de la prueba limpia)."""
    monedas = list(series)
    t = series[monedas[0]]["t"]
    efectivo = p.capital if efectivo_inicial is None else efectivo_inicial
    qty = dict.fromkeys(monedas, 0.0)
    stop = dict.fromkeys(monedas, 0.0)
    ultima_fraccion = dict.fromkeys(monedas, 0.0)
    bloqueada = dict.fromkeys(monedas, False)
    lotes = {m: imp.Lotes() for m in monedas}
    ganancia_anyo, pendientes = 0.0, []
    deuda: dict[int, float] = {}          # cuotas por pagar: se pagan el 30/06 del anyo siguiente (decision del 16/10)
    bajo_suelo, enclavado = 0, False
    suelo = None if p.suelo_pct is None else p.suelo_pct * p.capital
    r = Resultado()

    def minimo(m: str, precio: float) -> float:
        """El minimo por orden en euros: el de OKX (cantidad x precio), y nunca menos de `min_orden`."""
        return max(p.min_orden, p.min_cantidad.get(m, 0.0) * precio)

    def valor(precios: Mapping[str, float]) -> float:
        return efectivo + sum(qty[m] * precios[m] * (1 - p.comision) for m in monedas)

    def vender(m: str, cantidad: float, precio: float, dia: int, tipo: str) -> None:
        nonlocal efectivo, ganancia_anyo
        bruto = cantidad * precio
        efectivo += bruto * (1 - p.comision)
        ganancia_anyo += lotes[m].vender(cantidad, bruto * (1 - p.comision))
        qty[m] -= cantidad
        if qty[m] < 1e-12:
            qty[m] = 0.0
        r.operaciones.append({"dia": dia, "moneda": m, "tipo": tipo, "precio": precio, "nocional": bruto})

    equity_cierre = efectivo + sum(qty[m] * series[m]["c"][desde - 1] for m in monedas)
    for i in range(desde, hasta + 1):
        aperturas = {m: series[m]["o"][i] for m in monedas}
        e_ref = equity_cierre                                            # C5: el del cierre de i-1

        # El impuesto del anyo anterior, el 30/06 a la apertura (decision del 16/10, opcion a); si no hay efectivo, se
        # vende lo justo de cada posicion, a la apertura y con comision.
        hoy = datetime.fromtimestamp(t[i], UTC)
        if (hoy.month, hoy.day) == (6, 30) and deuda.get(hoy.year - 1, 0.0) > 0:
            debe = deuda.pop(hoy.year - 1)
            falta = debe - efectivo
            invertido = sum(qty[m] * aperturas[m] * (1 - p.deslizamiento) * (1 - p.comision) for m in monedas)
            if falta > 0 and invertido > 0:
                parte = min(1.0, falta / invertido)
                for m in monedas:
                    if qty[m] > 0:
                        vender(m, qty[m] * parte, aperturas[m] * (1 - p.deslizamiento), i, "impuesto")
            efectivo -= debe
            r.pagos.append((i, debe))
        caida = 1 - e_ref / p.capital
        # Regla 9, tal como se aprobo (decision 7): -10 % la mitad; -20 % maximo 1 posicion; -30 % las dos cosas.
        mitad = p.escalones and (0.10 <= caida < 0.20 or caida >= 0.30)
        max_pos = 1 if p.escalones and caida >= 0.20 else len(monedas)
        tope = p.tope_moneda / 2 if mitad else p.tope_moneda
        riesgo = None if p.riesgo is None else (p.riesgo / 2 if mitad else p.riesgo)

        # C1: la vuelta tras un stop.
        for m in monedas:
            if bloqueada[m]:
                if p.reentrada == "senyal" and fracciones[m][i - 1] == 0.0:
                    bloqueada[m] = False
                elif p.reentrada == "domingo" and _es(t[i - 1], 6):
                    bloqueada[m] = False

        # Objetivos: solo si cambia la fraccion (C6).
        objetivo = {}
        for m in monedas:
            f = 0.0 if bloqueada[m] else fracciones[m][i - 1]
            if f == ultima_fraccion[m]:
                continue
            nocional = f * tope * e_ref
            a = atr[m][i - 1]
            if f > 0 and p.stops:
                if qty[m] > 0:
                    # Revision final del 16/10: una posicion que crece mide su riesgo con el stop que TIENE (fijo desde
                    # la entrada). Si ya va por encima del tope, no se anyade; tampoco se vende por eso.
                    actual = qty[m] * aperturas[m]
                    if riesgo is not None and aperturas[m] > stop[m]:
                        tope_riesgo = riesgo * e_ref / ((aperturas[m] - stop[m]) / aperturas[m])
                        nocional = min(nocional, max(actual, tope_riesgo))
                elif a is None or a <= 0:
                    nocional = 0.0
                elif riesgo is not None:
                    nocional = min(nocional, riesgo * e_ref / (p.stop_atr * a / aperturas[m]))
            objetivo[m] = (f, nocional)

        # Primero las ventas: SOLO si la fraccion baja (revision final del 16/10: una compra que se reintenta nunca
        # acaba en venta, y el riesgo de una posicion que ya tiene no obliga a vender).
        for m, (f, nocional) in objetivo.items():
            if f >= ultima_fraccion[m]:
                continue
            actual = qty[m] * aperturas[m]
            if qty[m] > 0 and (f == 0.0 or nocional < actual - minimo(m, aperturas[m])):
                vende = qty[m] if f == 0.0 else (actual - nocional) / aperturas[m]
                vender(m, vende, aperturas[m] * (1 - p.deslizamiento), i, "venta")
            ultima_fraccion[m] = f

        # Despues las compras: solo si la fraccion sube.
        abiertas = sum(1 for m in monedas if qty[m] > 0)
        for m, (f, nocional) in sorted(objetivo.items(), key=lambda x: -x[1][1]):
            if f <= ultima_fraccion[m]:
                continue
            actual = qty[m] * aperturas[m]
            if enclavado:
                continue
            if nocional <= actual + minimo(m, aperturas[m]):
                ultima_fraccion[m] = f
                continue
            if qty[m] == 0 and abiertas >= max_pos:
                continue
            expuesto = sum(qty[x] * aperturas[x] for x in monedas)
            por_efectivo = efectivo / (1 + p.comision)
            compra = min(nocional - actual, p.exposicion * e_ref - expuesto, por_efectivo)
            if compra <= minimo(m, aperturas[m]):
                continue
            # Recortada solo por el efectivo (las comisiones no dejan llegar al 100 %): no hay mas que comprar.
            completa = compra >= nocional - actual - minimo(m, aperturas[m]) or compra >= por_efectivo - 1e-9
            precio = aperturas[m] * (1 + p.deslizamiento)
            nuevo_stop = stop[m] if qty[m] > 0 else (precio - p.stop_atr * atr[m][i - 1] if p.stops else 0.0)
            if p.colchon_pct is not None and suelo is not None:                  # regla 8
                q_desp = {x: qty[x] + (compra / precio if x == m else 0.0) for x in monedas}
                st = {x: (nuevo_stop if x == m else stop[x]) for x in monedas}
                perdida = sum(q_desp[x] * (aperturas[x] - st[x]) + q_desp[x] * st[x] * p.comision for x in monedas)
                if valor(aperturas) - compra * p.comision - perdida < suelo + p.colchon_pct * p.capital:
                    continue
            efectivo -= compra * (1 + p.comision)
            qty[m] += compra / precio
            lotes[m].comprar(compra / precio, compra * (1 + p.comision))
            stop[m] = nuevo_stop
            abiertas += 1 if actual == 0 else 0
            # Revision final del 16/10: si la compra se quedo corta (exposicion, efectivo), se reintenta (aclaracion 2).
            if completa:
                ultima_fraccion[m] = f
            r.operaciones.append({"dia": i, "moneda": m, "tipo": "compra", "precio": precio, "nocional": compra})

        # Durante el dia: los stops (C3).
        if p.stops:
            for m in monedas:
                if qty[m] > 0 and series[m]["l"][i] <= stop[m]:
                    vender(m, qty[m], min(stop[m], aperturas[m]) * (1 - p.deslizamiento), i, "stop")
                    bloqueada[m], ultima_fraccion[m] = True, 0.0

        # Al cierre.
        cierres = {m: series[m]["c"][i] for m in monedas}
        if p.impuestos and (_fin_de_anyo(t[i]) or i == hasta):
            if i == hasta:          # el ultimo dia: lo abierto paga como si se vendiera (igual que BTC mantenido, C8)
                for m in monedas:
                    if qty[m] > 0:
                        ganancia_anyo += lotes[m].vender(qty[m], qty[m] * cierres[m] * (1 - p.comision))
            anyo = datetime.fromtimestamp(t[i], UTC).year
            cuota, pendientes = imp.anual(anyo, ganancia_anyo, pendientes)
            r.impuestos[anyo] = cuota
            deuda[anyo] = deuda.get(anyo, 0.0) + cuota
            ganancia_anyo = 0.0
            if i == hasta:                       # el ultimo dia se paga todo lo pendiente (igual que BTC mantenido)
                total = sum(deuda.values())
                if total > 0:
                    efectivo -= total
                    r.pagos.append((i, total))
                deuda.clear()
        equity_cierre = valor(cierres)
        if suelo is not None:
            bajo_suelo = bajo_suelo + 1 if equity_cierre <= suelo else 0
            if bajo_suelo >= 2:
                enclavado = True
        r.dias.append(t[i])
        r.equity.append(equity_cierre)
        r.invertido.append(sum(qty[m] * cierres[m] for m in monedas) / equity_cierre if equity_cierre > 0 else 0.0)
    r.enclavado = enclavado
    return r


def mantener(s: Serie, desde: int, hasta: int, p: Parametros, efectivo: float | None = None) -> list[float]:
    """BTC (o la moneda que sea) mantenido: compra a la apertura de `desde` con comision y deslizamiento, valora cada
    cierre con la comision de salida; con impuestos, paga al final la ganancia (C8)."""
    caja = p.capital if efectivo is None else efectivo
    compra = caja / (1 + p.comision)
    q = compra / (s["o"][desde] * (1 + p.deslizamiento))
    out = [q * s["c"][i] * (1 - p.comision) for i in range(desde, hasta + 1)]
    if p.impuestos:
        out[-1] -= imp.cuota(out[-1] - caja)
    return out
