"""Estrategia de tendencia: variantes F (rotacion semanal) y H (BTC + ETH con el filtro de BTC). El bot no se toca.

    python tendencia.py validar               # ANTES de mirar F o H: tiene que dar comprar y mantener exacto
    python tendencia.py medir F|H|K|L > F.json
    python tendencia.py juzgar F.json H.json

Segunda tanda (`docs/archivo/diseno-tendencia-2.md`, aprobada por el propietario el 10/10 antes de medir): K (BTC y ETH, cada una con
su tendencia en 4 plazos, cada dia) y L (la rotacion de F con los 4 plazos), sobre la exploracion ampliada
(`--base var/estudios/exploracion-ampliada.db`). Los 4 plazos: cierre diario sobre su media de 20, 50, 100 y 200
dias; **una media sin dias suficientes cuenta como cumplida** (como H, que sin 200 dias de BTC no filtra).

Criterio y detalles aprobados por el propietario el 09/10 ANTES de medir: `docs/archivo/diseno-tendencia.md` (la condicion 5, con la
familia de tendencia, N = 6: `umbral.json`). Datos: la exploracion USDT (`var/estudios/exploracion.db`), del lunes
14/12/2020 (el primero con el ATR diario calentado) al 30/06/2024. La reserva, sin bajar.

Simulador semanal propio (la estrategia no es de setups de 4 h), vela de 4 h a vela de 4 h:
- rebalanceo los lunes a las 00:00 UTC con los datos del domingo (cierre diario = el de la vela de las 20:00); compra y
  venta a la apertura de esa vela, taker (0,20 %); el equity, como la regla 6 (con la comision de salida estimada);
- stop a 3 ATR diarios (14) bajo la entrada y objetivo a +100 % (regla 13); si una vela toca el stop, se vende al
  stop o a la apertura si abre por debajo; esa moneda no vuelve hasta el lunes siguiente;
- reglas: 4 (posiciones), 7 (suelo enclavado), 8 (preventiva, >= 26 $ con todos los stops), 9 (escalones), 10 (perdida
  del dia >= 3 $: ese dia no se compra; la compra pasa al dia siguiente), 12 nueva (5 % del equity hasta el stop por
  posicion), 15 (exposicion 90 % y correlacion como el bot: no entra si correlaciona > 0,8 con 2 o mas de las que hay;
  sin medir = correlacionada), 16 (spread de hoy, que nunca ata: todos < 0,10 %). Las 11 y 14 no atan semanalmente.
- sin 200 dias de BTC (hasta mayo de 2021), H no filtra (como la idea 2 de la primera ronda).
"""

from __future__ import annotations

import bisect
import json
import math
import sqlite3
import statistics
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from features.context import compute as correlaciones  # noqa: E402
from features.indicators import atr  # noqa: E402

AQUI = Path(__file__).resolve().parent
BASE = REPO / "var" / "estudios" / "exploracion.db"
DIA, VELA = 86_400_000, 4 * 3600_000
# Lunes 14/12/2020: el primero con el ATR diario ya calentado (los datos empiezan el 01/11; Wilder pide 42 dias). Todo
# (F, H y comprar y mantener) empieza aqui, para comparar el mismo periodo.
INICIO = int(datetime(2020, 12, 14, tzinfo=UTC).timestamp() * 1000)
FIN = None                                  # sin limite: hasta la ultima vela de la base
# Para la reserva y el anyo USDC (`docs/archivo/diseno-tendencia.md` 00): otra base y otras fechas, la estrategia igual.
if "--base" in sys.argv:
    BASE = Path(sys.argv[sys.argv.index("--base") + 1]).resolve()
if "--desde" in sys.argv:
    INICIO = int(datetime.fromisoformat(sys.argv[sys.argv.index("--desde") + 1]).replace(tzinfo=UTC).timestamp() * 1000)
if "--hasta" in sys.argv:
    FIN = int(datetime.fromisoformat(sys.argv[sys.argv.index("--hasta") + 1]).replace(tzinfo=UTC).timestamp() * 1000)
CAPITAL, SUELO, COLCHON = 50.0, 25.0, 1.0
TAKER = 0.002
STOP_ATR, OBJETIVO = 3.0, 2.0              # stop a 3 ATR diarios; objetivo a +100 %
RIESGO_POS = 0.05                          # regla 12 nueva
EXPOSICION = 0.90                          # regla 15
CORR, MAX_CORR = 0.8, 2                    # regla 15
PERDIDA_DIA = 3.0                          # regla 10
ESCALONES = ((45.0, 0.5, None), (40.0, 0.5, 2), (35.0, 0.5, 1))   # regla 9: (por debajo de, tamanyo, posiciones)
DIAS_RENDIMIENTO = 28
PLAZOS = (20, 50, 100, 200)                # K y L
PESO_K = 0.45                              # K: 45 % por moneda con 4 de 4; la mitad con 2 o 3; fuera con 0 o 1
VETO_K = 7 * 86_400_000                    # K: tras un stop, la moneda no vuelve en 7 dias
DIA_ROTACION = 0                           # el lunes (weekday 0)
BTC_MIN = 2                                # L: BTC sobre al menos 2 de sus 4 medias
# La robustez de L (`robustez-l.md`, 10/10): solo informacion; sin estas opciones, L tal cual.
if "--dia-rotacion" in sys.argv:
    DIA_ROTACION = int(sys.argv[sys.argv.index("--dia-rotacion") + 1])
if "--plazos" in sys.argv:
    PLAZOS = tuple(int(x) for x in sys.argv[sys.argv.index("--plazos") + 1].split(","))
if "--btc-min" in sys.argv:
    BTC_MIN = int(sys.argv[sys.argv.index("--btc-min") + 1])
SPREAD_MAX = 0.10


# --- datos -----------------------------------------------------------------------------------------------------------

def cargar():
    con = sqlite3.connect(f"file:{BASE}?mode=ro", uri=True)
    simbolos = [s for (s,) in con.execute("SELECT DISTINCT symbol FROM candles ORDER BY symbol")]
    velas = {s: con.execute("SELECT ts_open_ms, open, high, low, close FROM candles WHERE symbol=? AND timeframe='4h' "
                            "ORDER BY ts_open_ms", (s,)).fetchall() for s in simbolos}
    horas = {}
    for s in simbolos:
        filas = con.execute("SELECT ts_open_ms, close FROM candles WHERE symbol=? AND timeframe='1h' ORDER BY ts_open_ms",
                            (s,)).fetchall()
        horas[s] = pd.Series([c for _t, c in filas], index=[t for t, _c in filas], dtype="float64")
    minimo = {s: float(m or 0) for s, m in con.execute("SELECT symbol, min_amount FROM instruments")}
    spread = {s: float(p) for s, p in con.execute("SELECT symbol, spread_pct FROM book_metrics")}
    con.close()
    return simbolos, velas, horas, minimo, spread


def diarias(filas):
    """dia (ts 00:00) -> (open, high, low, close), solo dias completos (con la vela de las 20:00)."""
    por_dia: dict[int, list] = {}
    for t, o, h, lo, c in filas:
        por_dia.setdefault(t - t % DIA, []).append((t, o, h, lo, c))
    out = {}
    for d, vs in sorted(por_dia.items()):
        if any(t % DIA == 20 * 3600_000 for t, *_ in vs):
            vs.sort()
            out[d] = (vs[0][1], max(v[2] for v in vs), min(v[3] for v in vs), vs[-1][4])
    return out


class Mercado:
    def __init__(self):
        self.simbolos, self.velas, self.horas, self.minimo, self.spread = cargar()
        self.dias = {s: diarias(f) for s, f in self.velas.items()}
        self.atr = {}
        for s, d in self.dias.items():
            df = pd.DataFrame(list(d.values()), index=list(d.keys()), columns=["open", "high", "low", "close"])
            self.atr[s] = dict(zip(df.index, atr(df["high"], df["low"], df["close"], 14), strict=True))
        self.barras = {s: {t: (o, h, lo, c) for t, o, h, lo, c in f} for s, f in self.velas.items()}
        self.tiempos = sorted({t for f in self.velas.values() for t, *_ in f
                               if t >= INICIO and (FIN is None or t < FIN)})
        self.serie = {s: (list(d.keys()), [x[3] for x in d.values()]) for s, d in self.dias.items()}

    def medias(self, s, dia):
        """(cuantas de las 4 se cumplen, distancia media sobre las medias calculables) con los cierres hasta `dia`."""
        dias, cierres = self.serie[s]
        i = bisect.bisect_right(dias, dia)
        if i == 0 or dias[i - 1] != dia:
            return None
        c = cierres[i - 1]
        cumple, dist = 0, []
        for n in PLAZOS:
            if i < n:
                cumple += 1                                     # sin dias suficientes: cuenta como cumplida
                continue
            media = sum(cierres[i - n:i]) / n
            cumple += c > media
            dist.append(c / media - 1)
        return cumple, (sum(dist) / len(dist) if dist else 0.0)

    def cierre_dia(self, s, d):
        x = self.dias[s].get(d)
        return None if x is None else x[3]

    def rendimiento(self, s, domingo):
        a, b = self.cierre_dia(s, domingo), self.cierre_dia(s, domingo - DIAS_RENDIMIENTO * DIA)
        return None if a is None or b is None else a / b - 1

    def btc_bajista(self, domingo):
        cierres = [c for d, (_o, _h, _l, c) in self.dias["BTC/USDC"].items() if d <= domingo][-200:]
        if len(cierres) < 200:
            return None
        return cierres[-1] < sum(cierres) / 200

    def correlacionadas(self, s, otras, lunes):
        if not otras:
            return 0
        ventana = {x: self.horas[x][self.horas[x].index < lunes].tail(200) for x in [s, *otras]}
        m = correlaciones(ventana)
        n = 0
        for o in otras:
            clave = tuple(sorted((s, o)))
            if clave not in m.values or m.values[clave] > CORR:     # sin medir = correlacionada (el propietario, 22/09)
                n += 1
        return n


# --- el simulador ------------------------------------------------------------------------------------------------

class Cartera:
    def __init__(self, mercado: Mercado, variante: str, validar: dict | None = None):
        self.m, self.variante, self.validar = mercado, variante, validar
        self.caja = CAPITAL
        self.pos: dict[str, dict] = {}
        self.vetadas: set[str] = set()
        self.pendientes: list[str] = []
        self.enclavado = False
        self.bajo_suelo = 0
        self.inicio_dia = CAPITAL
        self.bloqueo_dia = False
        self.ops: list[dict] = []
        self.comisiones = 0.0
        self.curva: list[tuple[int, float]] = []
        self.invertido_velas = 0
        # Solo informacion (el propietario, 15/10, revision 6): la caida con el equity al cierre de CADA vela de 4 h. El criterio
        # sigue con los cierres diarios (`curva`), como se fijo antes de medir.
        self.pico_velas, self.caida_velas = CAPITAL, 0.0

    def equity(self, precios):
        return self.caja + sum(p["qty"] * precios[s] * (1 - TAKER) for s, p in self.pos.items())

    def vender(self, s, precio, t, motivo):
        p = self.pos.pop(s)
        bruto = p["qty"] * precio
        fee = bruto * TAKER
        self.caja += bruto - fee
        self.comisiones += fee
        self.ops.append({"simbolo": s, "entrada_ms": p["t"], "salida_ms": t, "entrada": p["entrada"], "salida": precio,
                         "neto": bruto - fee - p["coste"], "motivo": motivo})

    def comprar(self, s, nocional, precio, t, stop):
        fee = nocional * TAKER
        self.caja -= nocional + fee
        self.comisiones += fee
        self.pos[s] = {"qty": nocional / precio, "entrada": precio, "stop": stop, "objetivo": precio * OBJETIVO,
                       "t": t, "coste": nocional + fee}

    def limites(self, e):
        tam, maxpos = 1.0, (2 if self.variante in ("H", "K") else 3)
        for umbral, mult, pos in ESCALONES:
            if e < umbral:
                tam = mult
                if pos is not None:
                    maxpos = min(maxpos, pos)
        return tam, maxpos

    def elegir(self, domingo, lunes):
        if self.validar:
            return list(self.validar)
        if self.variante == "H":
            return [] if self.m.btc_bajista(domingo) is True else ["BTC/USDC", "ETH/USDC"]
        if self.variante == "L":
            btc = self.m.medias("BTC/USDC", domingo)
            if btc is None or btc[0] < BTC_MIN:
                return []
            pueden = {}
            for s in self.m.simbolos:
                x = self.m.medias(s, domingo)
                if x is not None and x[0] == len(PLAZOS):
                    pueden[s] = x[1]
            _tam, maxpos = self.limites(self.ultimo_equity)
            # Las que ya se tienen y siguen pudiendo se mantienen; el resto de huecos, las mas por encima.
            elegidas = sorted((s for s in self.pos if s in pueden), key=lambda s: -pueden[s])[:maxpos]
            for s in sorted(pueden, key=lambda s: -pueden[s]):
                if len(elegidas) >= maxpos:
                    break
                if s in elegidas or self.m.correlacionadas(s, elegidas, lunes) >= MAX_CORR:
                    continue
                elegidas.append(s)
            return elegidas
        r = {s: self.m.rendimiento(s, domingo) for s in self.m.simbolos}
        positivas = sorted((s for s, v in r.items() if v is not None and v > 0), key=lambda s: -r[s])
        _tam, maxpos = self.limites(self.ultimo_equity)
        elegidas: list[str] = []
        for s in positivas:
            if len(elegidas) >= maxpos:
                break
            if self.m.correlacionadas(s, elegidas, lunes) >= MAX_CORR:
                continue
            elegidas.append(s)
        return elegidas

    def intentar_compras(self, t, precios, domingo):
        if self.enclavado or self.bloqueo_dia:
            return
        e = self.equity(precios)
        tam, maxpos = self.limites(e)
        for s in list(self.pendientes):
            if s in self.pos or s in self.vetadas:
                self.pendientes.remove(s)
                continue
            if self.validar is None:
                if len(self.pos) >= maxpos or self.m.spread.get(s, 0) > SPREAD_MAX:
                    continue
                if self.m.correlacionadas(s, list(self.pos), t) >= MAX_CORR:
                    self.pendientes.remove(s)
                    continue
            precio = precios[s]
            a = self.m.atr[s].get(domingo)
            if a is None or a != a:
                self.pendientes.remove(s)
                continue
            stop = precio - STOP_ATR * a
            if stop <= 0:
                self.pendientes.remove(s)
                continue
            if self.validar is not None:
                nocional = self.validar[s] * CAPITAL / (1 + TAKER)
            else:
                peso = 0.45 if self.variante == "H" else 0.30
                expuesto = sum(p["qty"] * precios[x] for x, p in self.pos.items())
                nocional = min(peso * e * tam, RIESGO_POS * e / ((precio - stop) / precio), EXPOSICION * e - expuesto,
                               self.caja / (1 + TAKER))
                if nocional < self.m.minimo.get(s, 0) * precio or nocional <= 0:
                    self.pendientes.remove(s)
                    continue
                # Regla 8: con todas (y la nueva) cerradas en su stop, >= 25 + 1 $.
                perdida = sum(p["qty"] * (precios[x] - p["stop"]) for x, p in self.pos.items())
                perdida += nocional / precio * (precio - stop) + nocional * TAKER * 2
                if e - perdida < SUELO + COLCHON:
                    self.pendientes.remove(s)
                    continue
            self.comprar(s, nocional, precio, t, stop if self.validar is None else 0.0)
            self.pendientes.remove(s)

    def nivel_k(self, s, ayer):
        if self.validar is not None:
            return 1.0
        x = self.m.medias(s, ayer)
        if x is None:
            return None                                         # sin cierre de ayer: no se toca
        return 1.0 if x[0] == 4 else 0.5 if x[0] >= 2 else 0.0

    def vender_parte(self, s, frac, precio, t, motivo):
        p = self.pos[s]
        if frac >= 1:
            self.vender(s, precio, t, motivo)
            return
        qty = p["qty"] * frac
        bruto = qty * precio
        fee = bruto * TAKER
        self.caja += bruto - fee
        self.comisiones += fee
        coste = p["coste"] * frac
        self.ops.append({"simbolo": s, "entrada_ms": p["t"], "salida_ms": t, "entrada": p["entrada"], "salida": precio,
                         "neto": bruto - fee - coste, "motivo": motivo})
        p["qty"] -= qty
        p["coste"] -= coste

    def rebalanceo_k(self, t, precios):
        """K, cada dia a las 00:00 con el cierre de ayer: 45 % con 4 de 4, la mitad con 2 o 3, fuera con 0 o 1."""
        ayer = t - DIA
        objetivos = {}
        for s in ("BTC/USDC", "ETH/USDC"):
            n = self.nivel_k(s, ayer)
            if n is not None and precios.get(s, 0) > 0:
                objetivos[s] = 0.0 if self.veto_k.get(s, 0) > t else n
        # Primero las ventas (bajar de nivel).
        for s, n in objetivos.items():
            if s in self.pos and n < self.pos[s]["nivel"]:
                frac = 1.0 if n == 0 else 1 - n / self.pos[s]["nivel"]
                if frac < 1 and self.pos[s]["qty"] * frac < self.m.minimo.get(s, 0):
                    continue                                    # por debajo del minimo por orden: no se hace
                self.vender_parte(s, frac, precios[s], t, "tendencia")
                if s in self.pos:
                    self.pos[s]["nivel"] = n
        # Despues las compras (subir de nivel).
        if self.enclavado or self.bloqueo_dia:
            return
        e = self.equity(precios)
        tam, maxpos = self.limites(e)
        for s, n in objetivos.items():
            actual = self.pos[s]["nivel"] if s in self.pos else 0.0
            if n <= actual:
                continue
            precio = precios[s]
            if self.validar is not None:
                self.comprar(s, self.validar[s] * CAPITAL / (1 + TAKER), precio, t, 0.0)
                self.pos[s]["nivel"] = n
                continue
            if s not in self.pos and len(self.pos) >= maxpos:
                continue
            if self.m.spread.get(s, 0) > SPREAD_MAX:
                continue
            if s not in self.pos and self.m.correlacionadas(s, list(self.pos), t) >= MAX_CORR:
                continue
            a = self.m.atr[s].get(ayer)
            if a is None or a != a or precio - STOP_ATR * a <= 0:
                continue
            stop = max(precio - STOP_ATR * a, self.pos[s]["stop"] if s in self.pos else 0.0)
            valor = self.pos[s]["qty"] * precio if s in self.pos else 0.0
            expuesto = sum(p["qty"] * precios[x] for x, p in self.pos.items())
            total = min(n * PESO_K * e * tam, RIESGO_POS * e / ((precio - stop) / precio))
            nocional = min(total - valor, EXPOSICION * e - expuesto, self.caja / (1 + TAKER))
            if nocional < self.m.minimo.get(s, 0) * precio or nocional <= 0:
                continue                                        # por debajo del minimo por orden: no se hace
            # Regla 8: con todas (y la nueva) cerradas en su stop, >= 25 + 1 $.
            perdida = sum(p["qty"] * (precios[x] - (stop if x == s else p["stop"])) for x, p in self.pos.items())
            perdida += nocional / precio * (precio - stop) + nocional * TAKER * 2
            if e - perdida < SUELO + COLCHON:
                continue
            if s in self.pos:
                p = self.pos[s]
                fee = nocional * TAKER
                self.caja -= nocional + fee
                self.comisiones += fee
                q = nocional / precio
                p["entrada"] = (p["entrada"] * p["qty"] + precio * q) / (p["qty"] + q)
                p["qty"] += q
                p["coste"] += nocional + fee
                p["stop"] = stop
                p["objetivo"] = p["entrada"] * OBJETIVO
            else:
                self.comprar(s, nocional, precio, t, stop)
            self.pos[s]["nivel"] = n

    def correr(self):
        m = self.m
        self.veto_k: dict[str, int] = {}
        self.ultimo_equity = CAPITAL
        domingo = None
        for t in m.tiempos:
            barras = {s: m.barras[s].get(t) for s in m.simbolos}
            aperturas = {s: b[0] for s, b in barras.items() if b}
            # Las que no tienen vela a esa hora (NEAR antes de diciembre de 2020) no se tocan.
            precios_ap = {s: aperturas.get(s, self.pos[s]["entrada"] if s in self.pos else 0) for s in m.simbolos}
            if t % DIA == 0:
                self.inicio_dia = self.equity(precios_ap)
                self.bloqueo_dia = False
                lunes = datetime.fromtimestamp(t / 1000, UTC).weekday() == DIA_ROTACION
                if self.variante == "K":
                    self.rebalanceo_k(t, precios_ap)
                elif lunes:
                    domingo = t - DIA
                    self.vetadas = set()
                    elegidas = self.elegir(domingo, t)
                    for s in [x for x in self.pos if x not in elegidas]:
                        self.vender(s, precios_ap[s], t, "rotacion")
                    self.pendientes = [s for s in elegidas if s not in self.pos and s in aperturas]
                if self.pendientes and domingo is not None:
                    self.intentar_compras(t, precios_ap, domingo)
            # Stop y objetivo en cada vela (el stop gana los empates y sufre el hueco).
            if self.validar is None:
                for s in list(self.pos):
                    b = barras.get(s)
                    if not b:
                        continue
                    o, h, lo, _c = b
                    p = self.pos[s]
                    if lo <= p["stop"]:
                        self.vender(s, min(p["stop"], o), t, "stop")
                        self.vetadas.add(s)
                        self.veto_k[s] = t + VETO_K
                    elif h >= p["objetivo"]:
                        self.vender(s, p["objetivo"], t, "objetivo")
                        self.vetadas.add(s)
            cierres = {s: (barras[s][3] if barras.get(s) else precios_ap[s]) for s in m.simbolos}
            e = self.equity(cierres)
            self.ultimo_equity = e
            self.pico_velas = max(self.pico_velas, e)
            self.caida_velas = max(self.caida_velas, 1 - e / self.pico_velas)
            self.bajo_suelo = self.bajo_suelo + 1 if e <= SUELO else 0
            if self.bajo_suelo >= 2:
                self.enclavado = True                                   # regla 7
            if e - self.inicio_dia <= -PERDIDA_DIA:
                self.bloqueo_dia = True                                 # regla 10
            if self.pos:
                self.invertido_velas += 1
            if t % DIA == 20 * 3600_000:
                self.curva.append((t - t % DIA, e))
        return self


# --- metricas y criterio ----------------------------------------------------------------------------------------------

def metricas(curva):
    valores = [CAPITAL] + [e for _d, e in curva]
    r = [valores[i] / valores[i - 1] - 1 for i in range(1, len(valores))]
    sd = statistics.pstdev(r)
    sr = statistics.fmean(r) / sd if sd > 0 else 0.0
    pico, caida = valores[0], 0.0
    for v in valores:
        pico = max(pico, v)
        caida = max(caida, 1 - v / pico)
    n = len(r)
    mu = statistics.fmean(r)
    g3 = sum((x - mu) ** 3 for x in r) / n / sd ** 3 if sd > 0 else 0.0
    g4 = sum((x - mu) ** 4 for x in r) / n / sd ** 4 if sd > 0 else 3.0
    fin_anyo = {}
    for d, e in curva:
        fin_anyo[datetime.fromtimestamp(d / 1000, UTC).year] = e
    anyos, previo = {}, CAPITAL
    for a in sorted(fin_anyo):
        anyos[a] = fin_anyo[a] / previo - 1
        previo = fin_anyo[a]
    return {"final": valores[-1], "rendimiento": valores[-1] / CAPITAL - 1, "caida_max": caida,
            "sharpe_diario": sr, "sharpe_anual": sr * math.sqrt(365), "T": n, "asimetria": g3, "curtosis": g4,
            "por_anyo": anyos}


def mantener(m: Mercado, pesos: dict[str, float]):
    """Comprar a la apertura del primer lunes (taker) y mantener; el equity con la comision de salida estimada."""
    b0 = {s: m.barras[s][m.tiempos[0]][0] for s in pesos}
    qty = {s: w * CAPITAL / (1 + TAKER) / b0[s] for s, w in pesos.items()}
    caja = CAPITAL - sum(w * CAPITAL for w in pesos.values())
    curva = []
    for t in m.tiempos:
        if t % DIA == 20 * 3600_000:
            curva.append((t - t % DIA, caja + sum(q * m.barras[s][t][3] * (1 - TAKER) for s, q in qty.items())))
    return curva


def caida_velas_mantener(m: Mercado, pesos: dict[str, float]) -> float:
    """Como `mantener`, pero la caida con el cierre de CADA vela de 4 h (solo informacion)."""
    b0 = {s: m.barras[s][m.tiempos[0]][0] for s in pesos}
    qty = {s: w * CAPITAL / (1 + TAKER) / b0[s] for s, w in pesos.items()}
    caja = CAPITAL - sum(w * CAPITAL for w in pesos.values())
    pico, caida = CAPITAL, 0.0
    for t in m.tiempos:
        e = caja + sum(q * m.barras[s][t][3] * (1 - TAKER) for s, q in qty.items())
        pico = max(pico, e)
        caida = max(caida, 1 - e / pico)
    return caida


def dsr(met, sr0):
    sr, t = met["sharpe_diario"], met["T"]
    den = math.sqrt(max(1e-12, 1 - met["asimetria"] * sr + (met["curtosis"] - 1) / 4 * sr * sr))
    return statistics.NormalDist().cdf((sr - sr0) * math.sqrt(t - 1) / den)


def main() -> int:
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    if orden == "validar":
        m = Mercado()
        ok = True
        for variante, pesos in (("H", {"BTC/USDC": 0.90}), ("H", {"BTC/USDC": 0.45, "ETH/USDC": 0.45}),
                                ("K", {"BTC/USDC": 0.45, "ETH/USDC": 0.45})):
            sim = Cartera(m, variante, validar=pesos).correr().curva
            ref = mantener(m, pesos)
            dif = max(abs(a[1] - b[1]) for a, b in zip(sim, ref, strict=True))
            igual = len(sim) == len(ref) and dif < 1e-9
            ok &= igual
            print(f"{variante} {pesos}: {len(sim)} dias, diferencia maxima {dif:.2e} -> {'IGUAL' if igual else 'DISTINTO'}")
        print("VALIDACION:", "PASA, se puede medir F y H" if ok else "NO PASA: no se mide nada")
        return 0 if ok else 1
    if orden == "medir":
        variante = sys.argv[2]
        assert variante in ("F", "H", "K", "L")
        m = Mercado()
        c = Cartera(m, variante).correr()
        met = metricas(c.curva)
        btc = metricas(mantener(m, {"BTC/USDC": 1.0}))
        btc_eth = metricas(mantener(m, {"BTC/USDC": 0.5, "ETH/USDC": 0.5}))
        met["caida_max_velas"] = c.caida_velas                  # solo informacion: no entra en ningun criterio
        btc["caida_max_velas"] = caida_velas_mantener(m, {"BTC/USDC": 1.0})
        print(json.dumps({"variante": variante, "metricas": met, "btc": btc, "btc_eth": btc_eth,
                          "operaciones": len(c.ops), "comisiones": c.comisiones,
                          "tiempo_invertido": c.invertido_velas / len(m.tiempos),
                          "por_motivo": {k: sum(1 for o in c.ops if o["motivo"] == k)
                                         for k in ("rotacion", "tendencia", "stop", "objetivo")},
                          "ops": c.ops, "curva": c.curva,
                          # Las posiciones abiertas al final (el papel de L las avisa; no cambia ninguna metrica).
                          "abiertas": {s: {k: p[k] for k in ("t", "entrada", "qty", "coste", "stop", "objetivo")}
                                       for s, p in c.pos.items()}}, default=str))
        return 0
    if orden == "juzgar-fuera":
        # Reserva: rendimiento > 0; anyo USDC: >= 0 ("no perder"). Las dos: caida <= 2/3 de la de BTC mantenido.
        x = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        estricto = sys.argv[3] == "reserva"
        met, btc = x["metricas"], x["btc"]
        gana = met["rendimiento"] > 0 if estricto else met["rendimiento"] >= 0
        cae = met["caida_max"] <= 2 / 3 * btc["caida_max"]
        print(f"{sys.argv[3]}: F 50 $ -> {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), caida max "
              f"{100 * met['caida_max']:.1f} %, Sharpe {met['sharpe_anual']:.2f}, {x['operaciones']} operaciones "
              f"({x['por_motivo']}), invertido el {100 * x['tiempo_invertido']:.0f} % del tiempo")
        print(f"    BTC mantenido: 50 $ -> {btc['final']:.2f} $ ({100 * btc['rendimiento']:+.1f} %), caida max "
              f"{100 * btc['caida_max']:.1f} % (2/3 = {200 / 3 * btc['caida_max']:.1f} %), Sharpe "
              f"{btc['sharpe_anual']:.2f}; BTC + ETH {100 * x['btc_eth']['rendimiento']:+.1f} %")
        print(f"    {'si' if gana else 'NO'}  {'gana dinero (> 0)' if estricto else 'no pierde (>= 0)'}")
        print(f"    {'si' if cae else 'NO'}  caida <= 2/3 de la de BTC")
        print(f"VEREDICTO {sys.argv[3]}: {'PASA' if gana and cae else 'NO PASA'}")
        return 0
    if orden == "juzgar":
        sr0 = json.loads((AQUI / "umbral.json").read_text(encoding="utf-8"))["DECIDIDO"]["SR0_diario"]
        resultados = []
        for ruta in sys.argv[2:]:
            x = json.loads(Path(ruta).read_text(encoding="utf-8"))
            met, btc = x["metricas"], x["btc"]
            perd_btc_2022 = -btc["por_anyo"].get("2022", 0.0)
            perd_2022 = -met["por_anyo"].get("2022", 0.0)
            d = dsr(met, sr0)
            cond = {
                "1. gana dinero": met["rendimiento"] > 0,
                "2. caida <= 2/3 de la de BTC": met["caida_max"] <= 2 / 3 * btc["caida_max"],
                "3. Sharpe >= el de BTC": met["sharpe_anual"] >= btc["sharpe_anual"],
                "4. en 2022 pierde <= 1/3 de BTC": perd_2022 <= perd_btc_2022 / 3,
                "5. Sharpe deflactado >= 0,95": d >= 0.95,
            }
            pasa = all(cond.values())
            resultados.append((x["variante"], pasa, d))
            print(f"\n=== {x['variante']}: 50 $ -> {met['final']:.2f} $ ({100 * met['rendimiento']:+.1f} %), caida max "
                  f"{100 * met['caida_max']:.1f} %, Sharpe {met['sharpe_anual']:.2f}, {x['operaciones']} operaciones "
                  f"({x['por_motivo']}), comisiones {x['comisiones']:.2f} $, invertido el "
                  f"{100 * x['tiempo_invertido']:.0f} % del tiempo")
            print(f"    BTC mantenido: 50 $ -> {btc['final']:.2f} $ ({100 * btc['rendimiento']:+.1f} %), caida max "
                  f"{100 * btc['caida_max']:.1f} %, Sharpe {btc['sharpe_anual']:.2f}; BTC + ETH: "
                  f"{100 * x['btc_eth']['rendimiento']:+.1f} %, caida {100 * x['btc_eth']['caida_max']:.1f} %, "
                  f"Sharpe {x['btc_eth']['sharpe_anual']:.2f}")
            print("    por anyo (estrategia / BTC): " + ", ".join(
                f"{a} {100 * v:+.1f} % / {100 * btc['por_anyo'].get(a, 0):+.1f} %" for a, v in met["por_anyo"].items()))
            print(f"    Sharpe deflactado {d:.3f} (Sharpe por suerte {sr0 * math.sqrt(365):.2f} al anyo)")
            for k, v in cond.items():
                print(f"    {'si' if v else 'NO'}  {k}")
            print(f"    -> {'PASA' if pasa else 'NO PASA'}")
        pasan = [r for r in resultados if r[1]]
        print("\nVEREDICTO:", f"pasa {max(pasan, key=lambda r: r[2])[0]} (la de mayor Sharpe deflactado); la reserva, "
              "una sola vez" if pasan else "NO PASA NINGUNA: no se retocan")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
