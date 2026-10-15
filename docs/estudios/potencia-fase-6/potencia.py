"""Cuanto tiene que aportar la IA para que la fase 6 lo VEA (01/10/2026, para la decision de la sombra del 02/10).

La pregunta: con el ritmo de candidatos que hay (y con la sombra), que diferencia entre la IA y el baseline
podria declarar el juez de la fase 6 como APORTA o PERJUDICA, y con que probabilidad.

Como: se simulan fases 6 enteras con las MISMAS reglas que el juez (`portfolio/comparacion.py`): la M1 por
vela, el intervalo del 90 % remuestreando dias enteros (`bootstrap_por_dias`) y el veredicto (`veredicto`,
APORTA solo con 30 discrepancias o mas). Cada dia trae Poisson(ritmo) velas con candidatos; cada vela discrepa
con probabilidad p; una vela que discrepa vale delta + ruido normal de desviacion sigma (R); la que no, 0.

Los numeros de entrada (todos medidos, salvo delta, que es lo que se busca):
- sigma: 1,97 R es la desviacion de UNA operacion (diseno-aprendizaje, anyo de historia). Si en la vela que
  discrepa la IA salta lo que abre el baseline (o al reves), la diferencia es una operacion: 1,97. Si cada una
  abre una distinta, son dos: ~2,8. Se prueban las dos.
- ritmo: velas con candidatos al dia. 0,41 en el anyo USDC, 0,52 en vivo (3 en 5,8 dias). La sombra anyade
  0,51 (anyo) a 1,00 (exploracion) al dia, y se juzga APARTE (protocolo, decision 5).
- p: en vivo, 1 de 3 velas discrepa; en la prueba en seco, la eleccion marginal cambiaba 1 de cada 3.
- delta: lo que aporta la IA por vela que discrepa, en R. Como referencia: el baseline pierde -0,38 R por
  operacion; una IA que solo supiera saltarse las malas ganaria del orden de +0,4 R en cada salto.

    python potencia.py > resultado.json
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from portfolio.comparacion import (  # noqa: E402
    APORTA, DIA_MS, MIN_DISCREPANCIAS, PERJUDICA, bootstrap_por_dias, veredicto,
)

SIMULACIONES = 400
REMUESTREOS = 1000
DIAS = (21, 56)
RITMOS = {"sin sombra (en vivo)": 0.52, "sombra sola, baja": 0.51,
          "sombra sola, alta": 1.00, "juntas, si se sumaran": 1.52}
PS = (1 / 3, 1 / 2)
SIGMAS = (1.97, 2.8)
DELTAS = (-1.5, -1.0, -0.5, 0.0, 0.25, 0.5, 1.0, 1.5)


def poisson(rng: random.Random, lam: float) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def una_fase(rng: random.Random, dias: int, ritmo: float, p: float, sigma: float, delta: float) -> tuple[str, int]:
    valores, disc = [], 0
    for d in range(dias):
        for _ in range(poisson(rng, ritmo)):
            if rng.random() < p:
                disc += 1
                valores.append((d * DIA_MS, rng.gauss(delta, sigma)))
            else:
                valores.append((d * DIA_MS, 0.0))
    iv = bootstrap_por_dias(valores, remuestreos=REMUESTREOS, semilla=rng.randrange(10**9))
    return veredicto(iv, disc), disc


def main() -> int:
    rng = random.Random(6)
    filas = []
    for nombre, ritmo in RITMOS.items():
        for dias in DIAS:
            for p in PS:
                for sigma in SIGMAS:
                    for delta in DELTAS:
                        res = [una_fase(rng, dias, ritmo, p, sigma, delta) for _ in range(SIMULACIONES)]
                        filas.append({
                            "ritmo": nombre, "velas_al_dia": ritmo, "dias": dias, "p": round(p, 3), "sigma": sigma,
                            "delta": delta,
                            "discrepancias_media": round(sum(d for _v, d in res) / len(res), 1),
                            "con_30_o_mas": round(sum(d >= MIN_DISCREPANCIAS for _v, d in res) / len(res), 3),
                            "aporta": round(sum(v == APORTA for v, _d in res) / len(res), 3),
                            "perjudica": round(sum(v == PERJUDICA for v, _d in res) / len(res), 3),
                        })
    print(json.dumps({"simulaciones_por_casilla": SIMULACIONES, "remuestreos": REMUESTREOS, "filas": filas},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
