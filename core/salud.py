"""CLOSE_ONLY_DEGRADED: cuando se entra y, sobre todo, cuando se sale (PRD seccion 5).

PURO: recibe las senyales de una pasada (datos obsoletos, resultado de la ultima peticion al
exchange, desfase del reloj) y el estado anterior, y devuelve el estado nuevo y el cambio de
modo, si hay. Quien pida las senyales y aplique el cambio (`ModeMachine`) es otra pieza.

PRD 5: DEGRADED se activa con "datos obsoletos, errores repetidos del exchange, desfase del
reloj" y sale "automatica tras X min con el sistema sano". La asimetria es la clave:

- **Se entra al momento**, con cualquiera de las tres causas. Solo cierra: entrar de mas cuesta
  una oportunidad; no entrar puede costar operar con precios de hace un rato.
- **Se sale solo tras X minutos SEGUIDOS sin ninguna causa.** Sin esa espera, una conexion que
  va y viene haria entrar y salir en cada pasada. Una recaida vuelve a empezar la cuenta.

HALLAZGO (25/09/2026): la ingesta desplegada (`scripts/run_ingest.py`) ya usa DEGRADED por datos
obsoletos, pero SALE EN CUANTO se recuperan, sin la espera del PRD. Se corrige en la fase 4 con
esta pieza (el codigo del VPS estaba congelado por la medicion de 72 h).

LOS NUMEROS (`Umbrales`), DECIDIDOS por el propietario el 26/09/2026 al repasar la fase 4 (el PRD dice "X min"
sin fijarlo). Los tres van hacia el lado prudente (solo cierre).
- 3 errores SEGUIDOS del exchange: uno suelto es ruido de red; tres seguidos, un problema.
- 2 s de desfase de reloj: el MISMO limite que ya usa la ingesta (`data.clock_skew_max_seconds`),
  en vez de los 5 s que se propusieron (habria dos numeros para lo mismo). Medido en el VPS del 23 al
  26/09: entre -0,10 y -0,41 s en 864 lecturas; OKX rechaza con ~30 s. Un test ata los dos numeros.
- 10 min sano para salir: dos pasadas de la conciliacion (cada 5 min) sin nada raro.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Umbrales:
    errores_seguidos: int = 3
    desfase_reloj_ms: int = 2_000
    sano_para_salir_ms: int = 10 * 60_000


# Los propuestos (sin medir): se repasan con el propietario antes de la fase 4.
UMBRALES = Umbrales()


@dataclass(frozen=True, slots=True)
class Senyales:
    """Lo observado en UNA pasada. `None` = no se sabe (no se pidio nada)."""

    ahora_ms: int
    datos_obsoletos: bool = False             # p. ej. StalenessMonitor.exchange_is_degraded()
    error_exchange: bool | None = None        # la ultima peticion: True fallo, False bien
    desfase_reloj_ms: int | None = None       # hora local - hora del servidor de OKX


@dataclass(frozen=True, slots=True)
class Salud:
    """El estado entre pasadas. Inmutable: cada pasada da uno nuevo."""

    degradado: bool = False
    errores_seguidos: int = 0
    sano_desde_ms: int | None = None          # desde cuando no hay ninguna causa (si degradado)
    causas: tuple[str, ...] = ()


ENTRAR = "entrar"
SALIR = "salir"


def causas(s: Senyales, errores_seguidos: int, u: Umbrales) -> tuple[str, ...]:
    out = []
    if s.datos_obsoletos:
        out.append("datos obsoletos")
    if errores_seguidos >= u.errores_seguidos:
        out.append(f"{errores_seguidos} errores seguidos del exchange")
    if s.desfase_reloj_ms is not None and abs(s.desfase_reloj_ms) > u.desfase_reloj_ms:
        out.append(f"reloj desfasado {s.desfase_reloj_ms / 1000:+.1f} s")
    return tuple(out)


def evaluar(anterior: Salud, s: Senyales, u: Umbrales = UMBRALES) -> tuple[Salud, str | None, str]:
    """(estado nuevo, ENTRAR | SALIR | None, motivo)."""
    errores = anterior.errores_seguidos
    if s.error_exchange is True:
        errores += 1
    elif s.error_exchange is False:
        errores = 0
    ahora = causas(s, errores, u)

    if not anterior.degradado:
        if ahora:
            return Salud(True, errores, None, ahora), ENTRAR, "; ".join(ahora)
        return replace(anterior, errores_seguidos=errores, causas=()), None, ""

    if ahora:   # sigue mal, o ha recaido: la cuenta para salir vuelve a cero
        return Salud(True, errores, None, ahora), None, "; ".join(ahora)
    desde = anterior.sano_desde_ms if anterior.sano_desde_ms is not None else s.ahora_ms
    if s.ahora_ms - desde >= u.sano_para_salir_ms:
        minutos = (s.ahora_ms - desde) / 60_000
        return Salud(False, errores, None, ()), SALIR, f"{minutos:.0f} min sin ninguna causa"
    return Salud(True, errores, desde, ()), None, "esperando a estar sano el tiempo suficiente"
