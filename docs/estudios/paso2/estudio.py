"""El estudio del paso 2 (docs/plan-estudio-paso-2.md, criterio congelado `criterio-paso2` + aclaracion 1).

    .venv/Scripts/python.exe docs/estudios/paso2/estudio.py validar     # comprar y mantener = BTC mantenido (real)
    .venv/Scripts/python.exe docs/estudios/paso2/estudio.py explorar    # las 5, en 12/2020-09/2026 (necesita V5)
    .venv/Scripts/python.exe docs/estudios/paso2/estudio.py limpia      # la candidata, UNA vez, en 03/2018-11/2020

Las guardias estan en el codigo: `explorar` no corre sin el resultado de V5 (los costes de verdad); `limpia` no corre
sin una candidata elegida en la exploracion, y solo una vez (deja un cerrojo en git).
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from sim import datos, indicadores, juez, metricas, motor, senales  # noqa: E402

REPO = AQUI.parents[2]
DATOS = REPO / "var" / "estudios" / "paso2"
RESULTADOS = AQUI / "resultados"
V5 = RESULTADOS / "v5.json"
CERROJO = RESULTADOS / "prueba-limpia.json"
UMBRAL = REPO / "docs" / "estudios" / "tendencia" / "umbral.json"
EXPLORACION = ("2020-12-01", "2026-09-30")
LIMPIA = ("2018-03-04", "2020-11-30")
INTENTOS_PREVIOS = 35
CONFIGURACIONES = ("H1", "H2", "H3", "H1v", "H2v")


def indice(t: list[int], fecha: str) -> int:
    s = int(datetime.fromisoformat(fecha).replace(tzinfo=UTC).timestamp())
    return t.index(s)


def fracciones(s: dict, config: str) -> dict[str, list[float]]:
    out = {}
    for m, x in s.items():
        base = {"H1": lambda: senales.h1(x["c"]), "H2": lambda: senales.h2(x["h"], x["l"], x["c"]),
                "H3": lambda: senales.h3(x["t"], x["c"])}[config.rstrip("v")]()
        out[m] = senales.capa_volatilidad(base, indicadores.volatilidad(x["c"], 30)) if config.endswith("v") else base
    return out


def medir(s: dict, config: str, desde: int, hasta: int, p: motor.Parametros) -> dict:
    atr = {m: indicadores.atr(x["h"], x["l"], x["c"], 14) for m, x in s.items()}
    pc = replace(p, reentrada="domingo" if config.startswith("H3") else "senyal")
    r = motor.simular(s, fracciones(s, config), atr, desde, hasta, pc)
    return resumen(r.equity, s["BTC"]["c"], desde, hasta) | {"operaciones": len(r.operaciones), "impuestos": r.impuestos,
                                                              "invertido_medio": sum(r.invertido) / len(r.invertido)}


def resumen(equity: list[float], cierres_btc: list[float], desde: int, hasta: int) -> dict:
    rend = metricas.rendimientos(equity)
    asim, curt = metricas.momentos(rend)
    tipos = metricas.tipos_de_mercado(cierres_btc)[desde:hasta + 1]
    return {"anual": metricas.anual(equity), "caida": metricas.caida_maxima(equity), "final": equity[-1],
            "sharpe_diario": metricas.sharpe_diario(rend), "asimetria": asim, "curtosis": curt, "n": len(rend),
            "tipos": metricas.por_tipo(equity, tipos), "_rend": rend}


def parametros() -> motor.Parametros:
    v5 = json.loads(V5.read_text(encoding="utf-8"))
    return motor.Parametros(deslizamiento=float(v5["deslizamiento_por_lado"]))


def validar() -> int:
    s = datos.cargar(DATOS)
    d, h = (indice(s["BTC"]["t"], f) for f in EXPLORACION)
    p = motor.Parametros.validacion()
    r = motor.simular(s, {"BTC": [1.0] * len(s["BTC"]["t"]), "ETH": [0.0] * len(s["BTC"]["t"])},
                      {m: [None] * len(s["BTC"]["t"]) for m in s}, d, h, p)
    ref = motor.mantener(s["BTC"], d, h, p)
    dif = max(abs(a - b) for a, b in zip(r.equity, ref, strict=True))
    print(f"validacion en la exploracion ({len(ref)} dias): diferencia maxima {dif:.2e} -> "
          f"{'IGUAL' if dif < 1e-6 else 'DISTINTO: no se mide nada'}")
    return 0 if dif < 1e-6 else 1


def explorar() -> int:
    if not V5.exists():
        print("NO: falta el resultado de V5 (los costes de verdad). Se mide al acabar el recolector (30/10).")
        return 1
    s, p = datos.cargar(DATOS), parametros()
    d, h = (indice(s["BTC"]["t"], f) for f in EXPLORACION)
    btc = resumen(motor.mantener(s["BTC"], d, h, p), s["BTC"]["c"], d, h)
    res = {c: medir(s, c, d, h, p) for c in CONFIGURACIONES}
    previos = json.loads(UMBRAL.read_text(encoding="utf-8"))["sharpes_diarios"].values()
    sharpes = list(previos) + [x["sharpe_diario"] for x in res.values()]
    dispersion = math.sqrt(sum((x - sum(sharpes) / len(sharpes)) ** 2 for x in sharpes) / len(sharpes))
    n_total = INTENTOS_PREVIOS + len(CONFIGURACIONES)
    for x in res.values():
        x["deflactado"] = metricas.deflactado(x["sharpe_diario"], x["n"], n_total, dispersion, x["asimetria"], x["curtosis"])
        x["juez"] = {"liston": juez.liston(x, btc), "tipos": juez.tipos(x, btc), "caida": juez.caida(x)}
        x["cumple"] = all(v["pasa"] for v in x["juez"].values())
    pbo = metricas.pbo([res[c]["_rend"] for c in CONFIGURACIONES])
    cumplen = [c for c in CONFIGURACIONES if res[c]["cumple"]]
    candidata = max(cumplen, key=lambda c: res[c]["deflactado"]) if cumplen and pbo < 0.5 else None
    for x in [*res.values(), btc]:
        x.pop("_rend")
    salida = {"ventana": EXPLORACION, "btc": btc, "configuraciones": res, "intentos": n_total,
              "dispersion_sharpe_diario": dispersion, "pbo": pbo, "candidata": candidata, "deslizamiento": p.deslizamiento}
    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / "exploracion.json").write_text(json.dumps(salida, indent=1, default=str), encoding="utf-8")
    for c in CONFIGURACIONES:
        x = res[c]
        print(f"{c}: anual {100 * x['anual']:+.1f} %, caida {100 * x['caida']:.1f} %, deflactado {x['deflactado']:.3f}, "
              f"cumple {x['cumple']}")
    print(f"BTC mantenido: anual {100 * btc['anual']:+.1f} %, caida {100 * btc['caida']:.1f} %; PBO {pbo:.2f}; "
          f"candidata: {candidata or 'NINGUNA (se para aqui)'}")
    return 0


def limpia() -> int:
    ex = RESULTADOS / "exploracion.json"
    candidata = json.loads(ex.read_text(encoding="utf-8"))["candidata"] if ex.exists() else None
    juez.abrir_prueba_limpia(candidata, CERROJO)          # PermissionError si no toca
    s, p = datos.cargar(DATOS), parametros()
    d, h = (indice(s["BTC"]["t"], f) for f in LIMPIA)
    btc = resumen(motor.mantener(s["BTC"], d, h, p), s["BTC"]["c"], d, h)
    x = medir(s, candidata, d, h, p)
    x["probabilistico"] = metricas.probabilistico(x["sharpe_diario"], x["n"], x["asimetria"], x["curtosis"])
    x["juez"] = {"liston": juez.liston(x, btc), "tipos": juez.tipos(x, btc), "caida": juez.caida(x),
                 "probabilistico": {"pasa": x["probabilistico"] >= 0.95}}
    x["pasa"] = all(v["pasa"] for v in x["juez"].values())
    for y in (x, btc):
        y.pop("_rend")
    (RESULTADOS / "limpia.json").write_text(json.dumps({"ventana": LIMPIA, "candidata": candidata, "btc": btc,
                                                        "resultado": x}, indent=1, default=str), encoding="utf-8")
    print(f"{candidata} en la prueba limpia: {'PASA' if x['pasa'] else 'NO PASA'}")
    return 0 if x["pasa"] else 1


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"validar": validar, "explorar": explorar, "limpia": limpia}.get(orden, lambda: print(__doc__) or 2)())
