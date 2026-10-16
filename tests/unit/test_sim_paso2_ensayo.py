"""Ensayo completo del estudio del paso 2 con datos INVENTADOS (revision final del 16/10, hallazgos 1 y 4): explorar y
limpia de principio a fin, para que la unica vez de verdad no pueda romperse por un error de programacion; y como se
elige la candidata. Ningun dato real."""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"
spec = importlib.util.spec_from_file_location("estudio_paso2", AQUI / "estudio.py")
es = importlib.util.module_from_spec(spec)
sys.modules["estudio_paso2"] = es
spec.loader.exec_module(es)

DIA = 86_400


def _datos(directorio: Path) -> None:
    t0 = int(datetime(2017, 8, 16, tzinfo=UTC).timestamp())
    n = (int(datetime(2026, 10, 14, tzinfo=UTC).timestamp()) - t0) // DIA + 1
    for nombre, p0, semilla in (("bitstamp-btceur.json", 4_000.0, 1), ("bitstamp-etheur.json", 300.0, 2)):
        r, x, velas = random.Random(semilla), p0, []
        for i in range(n):
            o = x
            x *= math.exp(r.gauss(0.0008, 0.035))
            velas.append([t0 + i * DIA, o, max(o, x) * 1.01, min(o, x) * 0.99, x, 100.0])
        (directorio / nombre).write_text(json.dumps(velas), encoding="utf-8")


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    datos, res = tmp_path / "datos", tmp_path / "resultados"
    datos.mkdir()
    res.mkdir()
    _datos(datos)
    (res / "v5.json").write_text(json.dumps({"deslizamiento_por_lado": 0.0002}), encoding="utf-8")
    monkeypatch.setattr(es, "DATOS", datos)
    monkeypatch.setattr(es, "RESULTADOS", res)
    monkeypatch.setattr(es, "V5", res / "v5.json")
    monkeypatch.setattr(es, "CERROJO", res / "prueba-limpia.json")
    return res


def test_ensayo_completo_validar_explorar_y_limpia(entorno):
    assert es.validar() == 0
    assert es.explorar() == 0
    ex = json.loads((entorno / "exploracion.json").read_text(encoding="utf-8"))
    assert set(ex["configuraciones"]) == set(es.CONFIGURACIONES) and ex["intentos"] == 40
    assert 0.0 <= ex["pbo"] <= 1.0 and "_rend" not in ex["btc"]
    for x in ex["configuraciones"].values():
        assert {"anual", "caida", "deflactado", "juez", "cumple", "tipos"} <= set(x)
    # La prueba limpia con una candidata forzada (en el ensayo da igual cual): corre, deja el cerrojo y no repite.
    ex["candidata"] = "H1"
    (entorno / "exploracion.json").write_text(json.dumps(ex), encoding="utf-8")
    es.limpia()
    assert (entorno / "limpia.json").exists() and (entorno / "prueba-limpia.json").exists()
    with pytest.raises(PermissionError, match="una sola vez"):
        es.limpia()


def test_la_candidata_es_la_de_mayor_deflactado_entre_las_que_cumplen():
    res = {c: {"cumple": False, "deflactado": 0.99} for c in es.CONFIGURACIONES}
    res["H2"] = {"cumple": True, "deflactado": 0.60}
    res["H3"] = {"cumple": True, "deflactado": 0.70}
    assert es.elegir(res, pbo=0.30) == "H3"                 # H1 tiene mas deflactado pero no cumple
    assert es.elegir(res, pbo=0.50) is None                 # PBO >= 0,50: ninguna
    assert es.elegir({c: {"cumple": False, "deflactado": 1.0} for c in es.CONFIGURACIONES}, 0.1) is None
