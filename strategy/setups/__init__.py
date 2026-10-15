"""Los tres setups del informe seccion 1.3[5].

Importar este paquete registra los tres. El registro vive en `base.py` y se
llena con el decorador `@setup(...)`, asi que si algun dia se anyade un cuarto
setup basta con crear el fichero e importarlo AQUI: olvidarse de esta linea es
la unica forma de que un setup exista y no se use nunca.
"""

from strategy.setups import mean_reversion, pullback_trend, range_breakout  # noqa: F401
from strategy.setups.base import (
    SetupContext,
    SetupSignal,
    all_setups,
    build_signal,
    regimes_for,
    setup,
    setup_names,
)

__all__ = [
    "SetupContext",
    "SetupSignal",
    "all_setups",
    "build_signal",
    "regimes_for",
    "setup",
    "setup_names",
]
