"""El liston del paso 2, tal como se congelo (plan, seccion 4; decisiones del 15/10) y la guardia de la prueba limpia.
`m` y `btc` son las metricas de un tramo: `anual`, `caida` y `tipos[tipo]["anual"]`, en euros y netas."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

PUNTOS_PROTEGE = 0.05
CAIDA_RELATIVA = 2 / 3
CAIDA_MAXIMA = 0.35
LATERAL_MINIMO = -0.10


def liston(m: dict, btc: dict) -> dict:
    """Pasa de UNA de dos maneras: gana (anual >= BTC y caida <= la de BTC) o protege (anual >= BTC - 5 puntos y caida
    <= 2/3 de la de BTC)."""
    gana = m["anual"] >= btc["anual"] and m["caida"] <= btc["caida"]
    protege = m["anual"] >= btc["anual"] - PUNTOS_PROTEGE and m["caida"] <= CAIDA_RELATIVA * btc["caida"]
    return {"pasa": gana or protege, "gana": gana, "protege": protege}


def tipos(m: dict, btc: dict) -> dict:
    """Con el rendimiento TOTAL de los dias de cada tipo, sin anualizar (decision del 16/10, opcion a: pocos dias no se
    inflan): en bajista, mejor que BTC en esos dias; en alcista, al menos la mitad que BTC (si BTC perdio, no peor que
    el); en lateral, no pierde mas de un 10 % repartido por los dias que hubo (-10 % x dias / 365)."""
    t, b = m["tipos"], btc["tipos"]
    bajista = t["bajista"]["total"] > b["bajista"]["total"]
    ref = b["alcista"]["total"]
    alcista = t["alcista"]["total"] >= (0.5 * ref if ref > 0 else ref)
    lateral = t["lateral"]["total"] >= LATERAL_MINIMO * t["lateral"]["dias"] / 365
    return {"pasa": bajista and alcista and lateral, "bajista": bajista, "alcista": alcista, "lateral": lateral}


def caida(m: dict) -> dict:
    return {"pasa": m["caida"] <= CAIDA_MAXIMA}


def abrir_prueba_limpia(candidata: str | None, cerrojo: Path) -> None:
    """Los datos no vistos se usan UNA vez: sin candidata elegida en la exploracion, o si ya se abrio, no se deja."""
    if not candidata:
        raise PermissionError("sin candidata de la exploracion no se mira la prueba limpia")
    if cerrojo.exists():
        raise PermissionError(f"la prueba limpia ya se abrio ({cerrojo.read_text(encoding='utf-8')}): una sola vez")
    cerrojo.write_text(json.dumps({"candidata": candidata, "abierta": datetime.now(UTC).isoformat()}), encoding="utf-8")
