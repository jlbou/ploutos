"""El "Sharpe por suerte" de la condicion 5 de `docs/archivo/diseno-tendencia.md`, calculado ANTES de medir F y H.

    python dsr_umbral.py > umbral.json

Bailey y Lopez de Prado (2014), "The Deflated Sharpe Ratio": con N pruebas y la varianza V de sus Sharpes, el maximo
que se espera por pura suerte es
    SR0 = sqrt(V) * ((1 - g) * Z(1 - 1/N) + g * Z(1 - 1/(N e))),   g = 0,5772 (Euler-Mascheroni)
Todo en Sharpe DIARIO (rendimiento medio del dia / su desviacion). V sale de las variantes ya medidas en Ploutos cuya
lista de operaciones se guardo: su curva diaria se rehace sumando el R de las operaciones que cierran cada dia (0 los
dias sin cierres), del 02/12/2020 al 30/06/2024. N = 27 (aprobado por el propietario el 09/10): incluye las 8 del time-stop del
25/09 y las ideas de la primera ronda cuyo fichero no guardo las operaciones: cuentan en N, no entran en V.
"""
import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

ESTUDIOS = Path(__file__).resolve().parents[1]
N = 27
GAMMA = 0.5772156649
INICIO, FIN = date(2020, 12, 2), date(2024, 6, 30)

# (nombre, fichero, como leer las operaciones). Con el objetivo taker cuando se midio asi.
VARIANTES = [
    ("idea 1", "revision-estrategia/ideas/idea1.json", "dia_r"),
    ("idea 2", "segunda-ronda/resultados/idea2-taker.json", "dia_r"),
    ("idea 3", "revision-estrategia/ideas/idea3.json", "dia_r"),
    ("idea 4 pb 1,5", "revision-estrategia/ideas/idea4-pb15.json", "dia_r"),
    ("idea 4 pb 2,5", "revision-estrategia/ideas/idea4-pb25.json", "dia_r"),
    ("idea 4 rb 1,5", "revision-estrategia/ideas/idea4-rb15.json", "dia_r"),
    ("idea 4 rb 2,5", "revision-estrategia/ideas/idea4-rb25.json", "dia_r"),
    ("idea 5", "revision-estrategia/ideas/idea5.json", "dia_r"),
    ("2 + 3", "revision-estrategia/ideas/idea2+3.json", "dia_r"),
    ("H1 (1 h)", "operaciones-cortas/h1.json", "dia_r"),
    ("H2 (1 h)", "operaciones-cortas/h2.json", "dia_r"),
    ("C siempre", "segunda-ronda/resultados/C-siempre-taker.json", "dia_r"),
    ("C sin avance", "segunda-ronda/resultados/C-sin-avance-taker.json", "dia_r"),
    ("D", "segunda-ronda/resultados/D-taker.json", "dia_r"),
    ("2 + D", "segunda-ronda/resultados/2+D-taker.json", "dia_r"),
    ("espejo (largos + cortos)", ("revision-estrategia/largos-con-btc-operaciones.json",
                                  "revision-estrategia/cortos-operaciones.json"), "ops"),
    ("A' (largos + cortos)", "segunda-ronda/resultados/a-idea2+A.json", "ops"),
]


def cargar(ruta):
    return json.loads((ESTUDIOS / ruta).read_text(encoding="utf-8-sig"))


def por_dia(nombre, ruta, forma):
    suma: dict[date, float] = {}
    if forma == "dia_r":
        for d, r in cargar(ruta)["operaciones"]:
            suma[date.fromisoformat(d)] = suma.get(date.fromisoformat(d), 0.0) + r
    else:
        rutas = ruta if isinstance(ruta, tuple) else (ruta,)
        for rt in rutas:
            for o in cargar(rt):
                d = date(1970, 1, 1) + timedelta(milliseconds=o["cerrada_ms"])
                suma[d] = suma.get(d, 0.0) + o.get("r_con_financiacion", o["r"])
    dias = [INICIO + timedelta(days=i) for i in range((FIN - INICIO).days + 1)]
    return [suma.get(d, 0.0) for d in dias]


def z(p):
    return statistics.NormalDist().inv_cdf(p)


def sr0_de(v, n):
    return math.sqrt(v) * ((1 - GAMMA) * z(1 - 1 / n) + GAMMA * z(1 - 1 / (n * math.e)))


# DECISION DEL PROPIETARIO (09/10, antes de medir F y H): contar solo la FAMILIA de tendencia ("estar dentro cuando BTC sube"):
# idea 2, 2 + 3, 2 + D, A' (largos de la idea 2 + cortos) y ahora F y H -> N = 6. V, de las 4 ya medidas.
FAMILIA = ("idea 2", "2 + 3", "2 + D", "A' (largos + cortos)")
N_FAMILIA = 6


sharpes, sin_operaciones = {}, []
for nombre, ruta, forma in VARIANTES:
    if forma == "dia_r" and "operaciones" not in cargar(ruta):
        sin_operaciones.append(nombre)              # la primera ronda solo guardo las de algunas ideas
        continue
    serie = por_dia(nombre, ruta, forma)
    sd = statistics.pstdev(serie)
    sharpes[nombre] = statistics.fmean(serie) / sd if sd > 0 else 0.0

v = statistics.variance(sharpes.values())
sr0 = sr0_de(v, N)
v_fam = statistics.variance(sharpes[k] for k in FAMILIA)
sr0_fam = sr0_de(v_fam, N_FAMILIA)
print(json.dumps({
    "DECIDIDO": {"N": N_FAMILIA, "familia": list(FAMILIA) + ["F", "H"], "V_sharpe_diario": v_fam,
                 "SR0_diario": sr0_fam, "SR0_anual": sr0_fam * math.sqrt(365),
                 "nota": "el propietario, 09/10, antes de medir: solo la familia de tendencia (opcion b)"},
    "descartado_N27": {"N": N, "variantes_en_V": len(sharpes), "sin_operaciones_guardadas": sin_operaciones,
                       "V_sharpe_diario": v, "SR0_diario": sr0, "SR0_anual": sr0 * math.sqrt(365)},
    "sharpes_diarios": {k: round(s, 5) for k, s in sharpes.items()},
    "sharpes_anuales": {k: round(s * math.sqrt(365), 3) for k, s in sharpes.items()},
}, ensure_ascii=False, indent=1))
