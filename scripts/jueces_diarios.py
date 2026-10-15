"""Los jueces, una vez al dia, y un Telegram SOLO si algo va mal (decision del propietario del 26/09/2026).

Pasa los jueces que corren en el VPS: el papel de las dos carteras, la fase 3, la fase 6 (y su M1 en
sombra, desde el 02/10), las noticias, los comandos y (desde el 01/10) los bloqueos silenciosos. Cada juez sale con 0 (cumplido), 1 (FALLA) o 2 (coherente, pero aun no). Un 2 no es
un problema: es lo normal durante la semana de la fase 3. Se avisa si alguno da 1, o si no se pudo
ejecutar (otro codigo, o se colgo): un juez que no corre no juzga nada.

Si todo va bien, no manda nada (un aviso diario que dice "todo bien" deja de leerse).

    .venv/bin/python scripts/jueces_diarios.py            # lo lanza ploutos-jueces.timer
    .venv/bin/python scripts/jueces_diarios.py --seco     # dice lo que mandaria, sin mandarlo
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.secrets import Secrets  # noqa: E402
from notify.messages import cabecera, esc  # noqa: E402
from notify.telegram import send_message  # noqa: E402

TIMEOUT_S = 600
MAX_LINEAS = 6

# 15/10/2026 (el propietario, inventario, decision 1 b): las dos carteras de la fase 6 y el demo, RETIRADOS; sus siete jueces
# (papel del baseline y de la IA, fase 3, fase 6 y su sombra, bloqueos silenciosos y el demo) ya no se pasan.
# Siguen en el repositorio por si hay que juzgar una copia (`docs/cierre-fase-6.md`).
JUECES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("noticias", ("scripts/check_news.py",)),
    ("comandos de Telegram", ("scripts/check_control.py",)),
    # 10/10: el papel de L hacia adelante (12/10/2026-11/01/2027); un estudio, no decide nada del bot.
    ("papel de L", ("scripts/check_papel_l.py",)),
    # 11/10: el embudo de noticias para L, en sombra (y la regla 18 con el analista).
    ("embudo de noticias", ("scripts/check_embudo.py",)),
    # 16/10: el recolector de libros de ordenes del paso 2 (V5), hasta el 30/10/2026.
    ("libros de ordenes (V5)", ("scripts/check_libros.py",)),
)

log = logging.getLogger("ploutos.jueces")


@dataclass(frozen=True, slots=True)
class Veredicto:
    nombre: str
    codigo: int | None         # None: no se pudo ejecutar (se colgo o no arranco)
    salida: str

    @property
    def mal(self) -> bool:
        return self.codigo not in (0, 2)


def ejecutar(args: Sequence[str]) -> tuple[int | None, str]:
    try:
        r = subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True,
                           timeout=TIMEOUT_S)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, f"no termino en {TIMEOUT_S} s"
    except OSError as exc:
        return None, f"no arranco: {exc}"


def juzgar(correr: Callable[[Sequence[str]], tuple[int | None, str]] = ejecutar) -> list[Veredicto]:
    return [Veredicto(nombre, *correr(args)) for nombre, args in JUECES]


def _lineas_utiles(v: Veredicto) -> list[str]:
    """Las lineas que dicen QUE falla: las de FALLA y sus ejemplos, o el final si se colgo."""
    lineas = v.salida.splitlines()
    if v.codigo == 1:
        utiles = [l.strip() for l in lineas if "FALLA" in l or l.strip().startswith("- ")]
    else:
        utiles = [l.strip() for l in lineas if l.strip()][-MAX_LINEAS:]
    return utiles[:MAX_LINEAS]


def mensaje(veredictos: Sequence[Veredicto]) -> str | None:
    """El aviso, o None si todo va bien. Nunca nombra a Claude (decision del propietario del 25/09)."""
    malos = [v for v in veredictos if v.mal]
    if not malos:
        return None
    bloques = [cabecera("🚨", "Revision diaria: algo no cuadra",
                        f"{len(malos)} de {len(veredictos)} jueces")]
    for v in malos:
        que = "FALLA" if v.codigo == 1 else f"no se pudo ejecutar (codigo {v.codigo})"
        detalle = "\n".join(_lineas_utiles(v)).replace("Claude", "la IA")
        bloques.append(f"\n<b>{esc(v.nombre)}</b>: {esc(que)}\n<pre>{esc(detalle)}</pre>")
    bloques.append("\nEl resto, bien. Detalle: <code>scripts/jueces_diarios.py --seco</code> en el VPS.")
    return "\n".join(bloques)


def main() -> int:
    ap = argparse.ArgumentParser(description="Los jueces, una vez al dia")
    ap.add_argument("--seco", action="store_true", help="ensenya el aviso sin mandarlo")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    veredictos = juzgar()
    for v in veredictos:
        log.info("%s: codigo %s", v.nombre, v.codigo)
    texto = mensaje(veredictos)
    if texto is None:
        log.info("todo en orden: no se manda nada")
        return 0
    if args.seco:
        print(texto)
        return 1
    secretos = Secrets()
    envio = send_message(secretos.valor("telegram_bot_token"), secretos.telegram_chat_id, texto)
    log.info("aviso: %s", envio.detalle)
    # Sale con 1 aunque el aviso llegue: systemd lo marca como fallido y queda a la vista.
    return 1


if __name__ == "__main__":
    sys.exit(main())
