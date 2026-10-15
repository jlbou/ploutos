"""Contrato y parser del analista (`ai/contract.py`, `ai/parser.py`).

Lo que se protege: que nada de lo que diga Claude pueda convertirse en algo que
el contrato no permite. Una salida invalida es "no hacer nada", nunca una
excepcion y nunca una orden.
"""

from __future__ import annotations

import json

import pytest

from ai.contract import SCHEMA_JSON, SCHEMA_PATH, AnalystOutput, Decision, DecisionType
from ai.parser import INVALID_KIND, parse

CANDIDATOS = {"d-20260922T1600-trx-pb", "d-20260922T1600-eth-bo"}
POSICIONES = {"d-20260921T0800-sol-pb"}


def decision(**kw):
    base = {"type": "open", "ref": "d-20260922T1600-trx-pb", "confidence": 0.6,
            "size_multiplier": 0.8, "reasons": ["pullback con ADX alto"]}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


def salida(*decisiones, market_read="tendencia alcista"):
    return {"decisions": list(decisiones), "market_read": market_read}


# --------------------------------------------------------------------------
# El esquema del CLI y el modelo del parser dicen lo mismo
# --------------------------------------------------------------------------

ESQUEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
ITEM = ESQUEMA["properties"]["decisions"]["items"]


def test_los_tipos_coinciden():
    assert set(ITEM["properties"]["type"]["enum"]) == {t.value for t in DecisionType}


def test_el_multiplicador_solo_reduce_en_los_dos_sitios():
    esquema = ITEM["properties"]["size_multiplier"]
    assert (esquema["minimum"], esquema["maximum"]) == (0.5, 1.0)
    campo = Decision.model_fields["size_multiplier"].metadata
    limites = {type(m).__name__: m for m in campo}
    assert limites["Ge"].ge == 0.5 and limites["Le"].le == 1.0


def test_los_obligatorios_coinciden():
    obligatorios_modelo = {n for n, f in Decision.model_fields.items() if f.is_required()}
    assert set(ITEM["required"]) == obligatorios_modelo
    assert set(ESQUEMA["required"]) == {
        n for n, f in AnalystOutput.model_fields.items() if f.is_required()
    }


def test_ninguno_admite_campos_de_mas():
    assert ESQUEMA["additionalProperties"] is False and ITEM["additionalProperties"] is False
    assert Decision.model_config["extra"] == "forbid"
    assert AnalystOutput.model_config["extra"] == "forbid"


def test_el_esquema_que_recibe_el_cli_es_json_en_una_linea():
    """`--json-schema` lo quiere EN LINEA, no una ruta (verificado el 22/09/2026)."""
    assert "\n" not in SCHEMA_JSON
    assert json.loads(SCHEMA_JSON) == ESQUEMA


# --------------------------------------------------------------------------
# Lo que vale
# --------------------------------------------------------------------------


def test_una_salida_correcta():
    r = parse(salida(decision(), decision(type="skip", ref="d-20260922T1600-eth-bo",
                                          size_multiplier=None)), CANDIDATOS)
    assert r.ok
    assert [(o.cid, o.size_multiplier) for o in r.opens] == [("d-20260922T1600-trx-pb", 0.8)]
    assert r.skips == ("d-20260922T1600-eth-bo",)


def test_la_respuesta_real_del_22_09_se_entiende():
    """La que devolvio Claude en la verificacion de claude -p."""
    real = {"decisions": [{"type": "open", "ref": "d-20260922T1600-trx-pb",
                           "confidence": 0.62, "size_multiplier": 1.0,
                           "reasons": ["R:R 5,03", "ADX 46,8"]}],
            "market_read": "TRX en tendencia"}
    assert parse(real, CANDIDATOS).ok


def test_sin_multiplicador_un_open_no_reduce():
    r = parse(salida(decision(size_multiplier=None)), CANDIDATOS)
    assert r.ok and r.opens[0].size_multiplier == 1.0


def test_un_candidato_no_mencionado_es_skip():
    r = parse(salida(decision()), CANDIDATOS)
    assert r.ok and r.skips == ("d-20260922T1600-eth-bo",)
    assert "sin mencionar" in r.reason


def test_ninguna_decision_es_no_abrir_nada():
    r = parse(salida(), CANDIDATOS)
    assert r.ok and r.opens == () and set(r.skips) == CANDIDATOS


def test_las_decisiones_sobre_posiciones_no_se_ejecutan():
    """Decision D del propietario: solo cuentan open y skip."""
    r = parse(salida(decision(),
                     decision(type="close", ref="d-20260921T0800-sol-pb",
                              size_multiplier=None)), CANDIDATOS, POSICIONES)
    assert r.ok
    assert [d.type for d in r.not_executed] == [DecisionType.CLOSE]
    assert len(r.opens) == 1


# --------------------------------------------------------------------------
# Lo que NO vale: siempre la respuesta entera, siempre "no hacer nada"
# --------------------------------------------------------------------------


def _invalida(r):
    assert not r.ok
    assert r.kind == INVALID_KIND
    assert r.opens == ()
    assert set(r.skips) == CANDIDATOS, "invalida = ningun candidato se abre"


def test_cid_inventado_descarta_la_respuesta_entera():
    """El caso que el esquema NO impide: cid es solo un string."""
    r = parse(salida(decision(), decision(ref="d-inventado")), CANDIDATOS)
    _invalida(r)
    assert "inventado" in r.reason


def test_position_id_inventado_tambien():
    r = parse(salida(decision(type="hold", ref="p-99",
                              size_multiplier=None)), CANDIDATOS, POSICIONES)
    _invalida(r)


@pytest.mark.parametrize("mult", [0.49, 1.01, 2.0, 0.0, -1.0])
def test_la_ia_no_puede_aumentar_ni_anular_el_tamanyo(mult):
    _invalida(parse(salida(decision(size_multiplier=mult)), CANDIDATOS))


@pytest.mark.parametrize("roto", [
    None, "texto", [], {"decisions": []},                          # falta market_read
    salida(decision(type="modify_limits")),                        # no existe
    salida(decision(extra="campo de mas")),
    salida(decision(confidence=1.5)),
    salida(decision(reasons=["x" * 201])),
    salida(decision(reasons=["r"] * 6)),
    salida(market_read="x" * 301),
    salida(decision(type="open", ref=None)),                        # open sin ref
    salida(decision(ref="d-20260921T0800-sol-pb")),                 # open sobre una POSICION
    salida(decision(type="hold", ref="d-20260922T1600-trx-pb")),    # hold sobre un CANDIDATO
])
def test_lo_que_no_cumple_el_contrato_no_hace_nada(roto):
    _invalida(parse(roto, CANDIDATOS, POSICIONES))


def test_abrir_y_saltar_el_mismo_candidato_es_contradictorio():
    r = parse(salida(decision(), decision(type="skip")), CANDIDATOS)
    _invalida(r)
    assert "repetida" in r.reason


def test_el_parser_nunca_lanza():
    """Pase lo que pase, devuelve un resultado."""
    for cosa in (object(), 42, float("nan"), {"decisions": "no"}, {"decisions": [None]}):
        assert parse(cosa, CANDIDATOS).ok is False


def test_la_respuesta_real_que_fallo_en_la_prueba_en_seco():
    """22/09/2026: con `cid` y `position_id` opcionales, Claude rellenaba los dos
    con el mismo valor. Ese formato ya no existe (campo de mas = invalida), y lo
    mismo con `ref` es valido."""
    vieja = {"cid": "d-20260922T1600-trx-pb", "position_id": "d-20260922T1600-trx-pb",
             "type": "open", "confidence": 0.6, "reasons": ["ADX 26,6"]}
    assert not parse(salida(vieja), CANDIDATOS).ok
    nueva = {"ref": "d-20260922T1600-trx-pb", "type": "open", "confidence": 0.6,
             "reasons": ["ADX 26,6"]}
    assert parse(salida(nueva), CANDIDATOS).ok


def test_dos_decisiones_sobre_la_misma_posicion_son_contradictorias():
    """hold y close a la vez: la respuesta entera no vale. Antes solo se miraban
    los candidatos, y el journal (clave llamada+ref) habria reventado al guardar."""
    r = parse(salida(decision(type="hold", ref="d-20260921T0800-sol-pb", size_multiplier=None),
                     decision(type="close", ref="d-20260921T0800-sol-pb", size_multiplier=None)),
              CANDIDATOS, POSICIONES)
    _invalida(r)
    assert "repetida" in r.reason
