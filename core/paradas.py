"""Paradas conocidas del servidor: huecos que un juez no cuenta como fallo, pero SI muestra.

Los jueces de noticias y de comandos de Telegram miran toda la historia del servicio: un hueco
de lecturas ocurrido una vez daria FALLA cada noche para siempre, y esa alarma fija taparia
una incidencia nueva. Aqui se apuntan, a mano y con su motivo, las paradas que no fueron un
fallo del servicio (un reinicio del servidor que impuso el proveedor, por ejemplo).

Reglas (a proposito estrictas):

- Un hueco solo se justifica si cabe ENTERO dentro de una parada: el principio y el final.
  Un hueco que empieza dentro de la parada y acaba despues sigue siendo un FALLA.
- Se apunta la parada con ventana ajustada (unos minutos de margen), nunca "ese dia".
- El juez no la oculta: la imprime como "justificado" con su motivo.
- Una parada solo se anyade con una decision del propietario y su motivo; nunca para callar
  un fallo que no se ha entendido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Parada:
    desde_ms: int
    hasta_ms: int
    motivo: str

    def cubre(self, a_ms: int, b_ms: int) -> bool:
        return self.desde_ms <= a_ms and b_ms <= self.hasta_ms


def _ms(anyo: int, mes: int, dia: int, hora: int, minuto: int) -> int:
    return int(datetime(anyo, mes, dia, hora, minuto, tzinfo=UTC).timestamp() * 1000)


PARADAS_CONOCIDAS: tuple[Parada, ...] = (
    # 19/10/2026: reinicio de seguridad (actualizacion del nucleo) que impuso el proveedor del
    # servidor. Parado de las 08:43 a las 09:14 UTC; todo volvio solo y las velas se rellenaron.
    Parada(
        desde_ms=_ms(2026, 10, 19, 8, 40),
        hasta_ms=_ms(2026, 10, 19, 9, 16),
        motivo="reinicio de seguridad del servidor impuesto por el proveedor (19/10/2026)",
    ),
)


def justificada(a_ms: int, b_ms: int, paradas: tuple[Parada, ...] | None = None) -> Parada | None:
    """La parada conocida que explica por completo un hueco entre `a_ms` y `b_ms`, si la hay."""
    for parada in PARADAS_CONOCIDAS if paradas is None else paradas:
        if parada.cubre(a_ms, b_ms):
            return parada
    return None
