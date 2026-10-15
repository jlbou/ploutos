"""La configuracion invalida impide arrancar (PRD seccion 4).

Cada test de aqui es una forma de romper el bot que NO puede pasar
desapercibida. Si alguno se pone en verde despues de relajar una regla,
el test no protege nada.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.config import (
    HARD_MAX_POSITIONS,
    HARD_MAX_TRADES_PER_DAY,
    ConfigError,
    load_settings,
)


def load(write_settings, data: dict[str, Any]):
    return load_settings(write_settings(data))


# --- el caso bueno ---


def test_la_configuracion_real_del_proyecto_es_valida(settings):
    assert len(settings.whitelist) == 8
    assert settings.risk.max_positions == HARD_MAX_POSITIONS
    assert settings.risk.max_trades_per_day == HARD_MAX_TRADES_PER_DAY


def test_fichero_inexistente(tmp_path):
    with pytest.raises(ConfigError, match="no existe"):
        load_settings(tmp_path / "no_existe.yaml")


def test_yaml_corrupto(tmp_path):
    path = tmp_path / "roto.yaml"
    path.write_text("esto: [no cierra", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML invalido"):
        load_settings(path)


# --- regla 3: whitelist ---


def test_regla3_par_fuera_de_usdc_no_arranca(write_settings, settings_dict):
    settings_dict["whitelist"][0] = "BTC/USDT"
    with pytest.raises(ConfigError, match="regla 3"):
        load(write_settings, settings_dict)


def test_regla3_par_contra_btc_no_arranca(write_settings, settings_dict):
    """El informe admitia X/BTC; el PRD no. Manda el PRD."""
    settings_dict["whitelist"][0] = "ETH/BTC"
    with pytest.raises(ConfigError, match="regla 3"):
        load(write_settings, settings_dict)


def test_regla3_mas_de_ocho_monedas_no_arranca(write_settings, settings_dict):
    settings_dict["whitelist"].append("LTC/USDC")
    with pytest.raises(ConfigError, match="exactamente 8"):
        load(write_settings, settings_dict)


def test_regla3_menos_de_ocho_monedas_no_arranca(write_settings, settings_dict):
    settings_dict["whitelist"].pop()
    with pytest.raises(ConfigError, match="exactamente 8"):
        load(write_settings, settings_dict)


def test_regla3_duplicados_no_arrancan(write_settings, settings_dict):
    settings_dict["whitelist"][1] = settings_dict["whitelist"][0]
    with pytest.raises(ConfigError, match="duplicados"):
        load(write_settings, settings_dict)


def test_regla3_quote_distinta_de_usdc_no_arranca(write_settings, settings_dict):
    settings_dict["exchange"]["quote"] = "EUR"
    with pytest.raises(ConfigError, match="regla 3"):
        load(write_settings, settings_dict)


def test_is_whitelisted(settings):
    assert settings.is_whitelisted("BTC/USDC")
    assert not settings.is_whitelisted("ADA/USDC")
    assert not settings.is_whitelisted("BTC/USDT")


# --- regla 2: exchange ---


def test_regla2_otro_exchange_no_arranca(write_settings, settings_dict):
    settings_dict["exchange"]["id"] = "binance"
    with pytest.raises(ConfigError, match="regla 2"):
        load(write_settings, settings_dict)


# --- regla 4: posiciones ---


def test_regla4_cuatro_posiciones_no_arranca(write_settings, settings_dict):
    settings_dict["risk"]["max_positions"] = 4
    with pytest.raises(ConfigError, match="regla 4"):
        load(write_settings, settings_dict)


def test_regla4_dos_posiciones_por_simbolo_no_arranca(write_settings, settings_dict):
    """Permitir 2 por simbolo es promediar a la baja por la puerta de atras."""
    settings_dict["risk"]["max_positions_per_symbol"] = 2
    with pytest.raises(ConfigError, match="regla 4"):
        load(write_settings, settings_dict)


def test_regla4_menos_de_tres_posiciones_si_arranca(write_settings, settings_dict):
    """Mas conservador siempre se permite."""
    settings_dict["risk"]["max_positions"] = 2
    settings_dict["risk"]["max_correlated_positions"] = 2
    assert load(write_settings, settings_dict).risk.max_positions == 2


# --- reglas 5 y 7: capital y suelo ---


def test_regla5_suelo_por_debajo_de_25_no_arranca(write_settings, settings_dict):
    settings_dict["capital"]["floor_usd"] = 10.0
    with pytest.raises(ConfigError, match="regla 5/7"):
        load(write_settings, settings_dict)


def test_regla5_suelo_mas_alto_si_arranca(write_settings, settings_dict):
    settings_dict["capital"]["floor_usd"] = 30.0
    assert load(write_settings, settings_dict).capital.floor_usd == 30.0


def test_regla5_suelo_por_encima_del_capital_no_arranca(write_settings, settings_dict):
    settings_dict["capital"]["floor_usd"] = 60.0
    with pytest.raises(ConfigError, match="menor que el capital inicial"):
        load(write_settings, settings_dict)


def test_regla5_capital_mayor_de_50_no_arranca(write_settings, settings_dict):
    settings_dict["capital"]["initial_capital_usd"] = 500.0
    with pytest.raises(ConfigError, match="regla 5"):
        load(write_settings, settings_dict)


# --- regla 6: equity cada 15 s ---


def test_regla6_equity_mas_lento_de_15s_no_arranca(write_settings, settings_dict):
    settings_dict["data"]["equity_interval_seconds"] = 60
    with pytest.raises(ConfigError, match="regla 6"):
        load(write_settings, settings_dict)


def test_regla6_equity_mas_rapido_si_arranca(write_settings, settings_dict):
    settings_dict["data"]["equity_interval_seconds"] = 5
    assert load(write_settings, settings_dict).data.equity_interval_seconds == 5


# --- regla 9: escalones de drawdown ---


def test_regla9_escalones_desordenados_no_arrancan(write_settings, settings_dict):
    settings_dict["drawdown_tiers"].reverse()
    with pytest.raises(ConfigError, match="regla 9"):
        load(write_settings, settings_dict)


def test_regla9_escalon_por_debajo_del_suelo_no_arranca(write_settings, settings_dict):
    settings_dict["drawdown_tiers"].append(
        {"equity_below_usd": 20.0, "max_positions": 1}
    )
    with pytest.raises(ConfigError, match="regla 9"):
        load(write_settings, settings_dict)


def test_regla9_escalon_que_relaja_posiciones_no_arranca(write_settings, settings_dict):
    settings_dict["drawdown_tiers"] = [
        {"equity_below_usd": 45.0, "risk_multiplier": 0.5, "max_positions": 1},
        {"equity_below_usd": 40.0, "risk_multiplier": 0.5, "max_positions": 3},
    ]
    with pytest.raises(ConfigError, match="RELAJA"):
        load(write_settings, settings_dict)


def test_regla9_escalon_que_relaja_el_riesgo_no_arranca(write_settings, settings_dict):
    settings_dict["drawdown_tiers"] = [
        {"equity_below_usd": 45.0, "risk_multiplier": 0.5},
        {"equity_below_usd": 40.0, "risk_multiplier": 1.0},
    ]
    with pytest.raises(ConfigError, match="RELAJA"):
        load(write_settings, settings_dict)


@pytest.mark.parametrize(
    "equity,expected_positions,expected_multiplier",
    [
        (50.0, 3, 1.0),
        (45.0, 3, 1.0),    # el escalon es "por debajo de", 45 exacto no entra
        (44.99, 3, 0.5),
        (40.0, 3, 0.5),
        (39.99, 2, 0.5),
        (35.0, 2, 0.5),
        (34.99, 1, 0.5),
        (26.0, 1, 0.5),
    ],
)
def test_regla9_limites_por_escalon(
    settings, equity, expected_positions, expected_multiplier
):
    positions, multiplier = settings.limits_for_equity(equity)
    assert positions == expected_positions
    assert multiplier == expected_multiplier


# --- regla 10: limite diario ---


def test_regla10_limite_diario_mayor_de_3_no_arranca(write_settings, settings_dict):
    settings_dict["risk"]["daily_loss_limit_usd"] = 10.0
    with pytest.raises(ConfigError, match="regla 10"):
        load(write_settings, settings_dict)


# --- regla 11: operaciones al dia ---


def test_regla11_siete_operaciones_no_arranca(write_settings, settings_dict):
    """El informe daba 7-8 en los niveles agresivos del slider. El PRD, 6."""
    settings_dict["risk"]["max_trades_per_day"] = 7
    with pytest.raises(ConfigError, match="regla 11"):
        load(write_settings, settings_dict)


# --- regla 12: riesgo por operacion ---


def test_regla12_riesgo_por_encima_de_1_5_no_arranca(write_settings, settings_dict):
    settings_dict["risk"]["risk_per_trade_max_pct"] = 5.0
    with pytest.raises(ConfigError, match="regla 12"):
        load(write_settings, settings_dict)


def test_regla12_riesgo_por_debajo_de_0_5_no_arranca(write_settings, settings_dict):
    settings_dict["risk"]["risk_per_trade_min_pct"] = 0.1
    with pytest.raises(ConfigError, match="regla 12"):
        load(write_settings, settings_dict)


def test_regla12_riesgo_fuera_del_rango_del_slider_no_arranca(
    write_settings, settings_dict
):
    settings_dict["risk"]["risk_per_trade_pct"] = 1.4
    settings_dict["risk"]["risk_per_trade_max_pct"] = 1.2
    with pytest.raises(ConfigError, match="regla 12"):
        load(write_settings, settings_dict)


# --- regla 15: exposicion ---


def test_regla15_exposicion_mayor_de_90_no_arranca(write_settings, settings_dict):
    settings_dict["risk"]["max_exposure_pct"] = 100.0
    with pytest.raises(ConfigError, match="regla 15"):
        load(write_settings, settings_dict)


def test_incoherencia_posiciones_no_caben_en_la_exposicion(
    write_settings, settings_dict
):
    """3 x 20 $ = 60 $ no cabe en el 90 % de 50 $ = 45 $."""
    settings_dict["risk"]["target_notional_usd"] = 20.0
    with pytest.raises(ConfigError, match="incoherencia"):
        load(write_settings, settings_dict)


def test_tres_posiciones_al_nocional_objetivo_caben_justas(settings):
    """3 x 15 $ = 45 $ = 90 % de 50 $. Los numeros del PRD cuadran exactos."""
    planned = settings.risk.max_positions * settings.risk.target_notional_usd
    limit = settings.capital.initial_capital_usd * settings.risk.max_exposure_pct / 100
    assert planned == pytest.approx(limit)


# --- regla 16: spread y coste ---


def test_regla16_spread_de_entrada_mayor_de_0_10_no_arranca(
    write_settings, settings_dict
):
    settings_dict["risk"]["max_entry_spread_pct"] = 0.5
    with pytest.raises(ConfigError, match="regla 16"):
        load(write_settings, settings_dict)


def test_regla16_ratio_objetivo_coste_menor_de_3_no_arranca(
    write_settings, settings_dict
):
    settings_dict["risk"]["min_target_cost_ratio"] = 1.5
    with pytest.raises(ConfigError, match="regla 16"):
        load(write_settings, settings_dict)


# --- regla 18: presupuesto de Claude ---


def test_regla18_mas_de_40_llamadas_al_dia_no_arranca(write_settings, settings_dict):
    settings_dict["claude"]["max_calls_per_day"] = 1000
    with pytest.raises(ConfigError, match="regla 18"):
        load(write_settings, settings_dict)


def test_regla18_mas_de_8_por_ventana_no_arranca(write_settings, settings_dict):
    settings_dict["claude"]["max_calls_per_5h_window"] = 20
    with pytest.raises(ConfigError, match="regla 18"):
        load(write_settings, settings_dict)


def test_regla18_ventana_mayor_que_el_diario_no_arranca(write_settings, settings_dict):
    settings_dict["claude"]["max_calls_per_day"] = 5
    settings_dict["claude"]["max_calls_per_5h_window"] = 8
    with pytest.raises(ConfigError, match="regla 18"):
        load(write_settings, settings_dict)


# --- coherencia de datos ---


def test_timeframe_de_features_sin_ingerir_no_arranca(write_settings, settings_dict):
    settings_dict["data"]["feature_timeframes"] = ["5m", "1d"]
    with pytest.raises(ConfigError, match="no se ingieren"):
        load(write_settings, settings_dict)


def test_primary_timeframe_fuera_de_features_no_arranca(write_settings, settings_dict):
    settings_dict["data"]["primary_timeframe"] = "1m"
    with pytest.raises(ConfigError, match="primary_timeframe"):
        load(write_settings, settings_dict)


def test_timeframes_duplicados_no_arrancan(write_settings, settings_dict):
    settings_dict["data"]["timeframes"] = ["1m", "1m", "5m", "15m", "1h", "4h"]
    with pytest.raises(ConfigError, match="duplicados"):
        load(write_settings, settings_dict)


def test_campo_desconocido_no_arranca(write_settings, settings_dict):
    """Un typo en el YAML no puede pasar en silencio."""
    settings_dict["risk"]["max_postions"] = 99
    with pytest.raises(ConfigError):
        load(write_settings, settings_dict)


# --- inmutabilidad ---


def test_la_configuracion_es_inmutable(settings):
    """La IA no puede modificar los limites ni aunque llegue al objeto."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        settings.risk.max_positions = 99


# --- comisiones (decision del propietario del 23/09/2026) ---


def test_comisiones_de_la_cuenta_no_las_de_ccxt(settings):
    """Cuenta solo spot de la UE, nivel Regular, desde el 25/09/2026."""
    assert settings.exchange.fees.maker_pct == 0.10
    assert settings.exchange.fees.taker_pct == 0.20


def test_comision_con_errata_no_arranca(write_settings, settings_dict):
    settings_dict["exchange"]["fees"]["taker_pct"] = 20      # 20 % en vez de 0,20 %
    with pytest.raises(ConfigError):
        load(write_settings, settings_dict)


def test_comision_cero_no_arranca(write_settings, settings_dict):
    settings_dict["exchange"]["fees"]["maker_pct"] = 0
    with pytest.raises(ConfigError):
        load(write_settings, settings_dict)


def test_taker_por_debajo_del_maker_no_arranca(write_settings, settings_dict):
    settings_dict["exchange"]["fees"]["taker_pct"] = 0.05
    with pytest.raises(ConfigError, match="taker"):
        load(write_settings, settings_dict)


def test_apply_pone_las_comisiones_de_settings_en_las_filas(settings):
    filas = [{"symbol": "BTC/USDC", "maker_fee": 0.001, "taker_fee": 0.0015, "lot_size": 1e-8}]
    [fila] = settings.exchange.fees.apply(filas)
    assert (fila["maker_fee"], fila["taker_fee"]) == (0.001, 0.002)
    assert fila["lot_size"] == 1e-8, "el resto de la fila no se toca"
    assert filas[0]["taker_fee"] == 0.0015, "no modifica la original"
