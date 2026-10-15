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
    min_orden: float = 5.0             # euros
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
    impuestos: dict[int, float] = field(default_factory=dict)
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
    bajo_suelo, enclavado = 0, False
    suelo = None if p.suelo_pct is None else p.suelo_pct * p.capital
    r = Resultado()

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
                if a is None or a <= 0:
                    nocional = 0.0
                elif riesgo is not None:
                    nocional = min(nocional, riesgo * e_ref / (p.stop_atr * a / aperturas[m]))
            objetivo[m] = (f, nocional)

        # Primero las ventas.
        for m, (f, nocional) in objetivo.items():
            actual = qty[m] * aperturas[m]
            if nocional < actual - p.min_orden or (f == 0.0 and qty[m] > 0):
                vende = qty[m] if f == 0.0 else (actual - nocional) / aperturas[m]
                vender(m, vende, aperturas[m] * (1 - p.deslizamiento), i, "venta")
            ultima_fraccion[m] = f if nocional <= actual + p.min_orden else ultima_fraccion[m]

        # Despues las compras.
        abiertas = sum(1 for m in monedas if qty[m] > 0)
        for m, (f, nocional) in sorted(objetivo.items(), key=lambda x: -x[1][1]):
            actual = qty[m] * aperturas[m]
            if enclavado or nocional <= actual + p.min_orden:
                ultima_fraccion[m] = f if not enclavado else ultima_fraccion[m]
                continue
            if qty[m] == 0 and abiertas >= max_pos:
                continue
            expuesto = sum(qty[x] * aperturas[x] for x in monedas)
            compra = min(nocional - actual, p.exposicion * e_ref - expuesto, efectivo / (1 + p.comision))
            if compra <= p.min_orden:
                continue
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
            cuota, pendientes = imp.anual(datetime.fromtimestamp(t[i], UTC).year, ganancia_anyo, pendientes)
            efectivo -= cuota
            r.impuestos[datetime.fromtimestamp(t[i], UTC).year] = cuota
            ganancia_anyo = 0.0
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
