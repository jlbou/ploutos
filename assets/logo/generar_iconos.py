"""Genera las iconas de prueba a partir de UN solo dibujo: el del logo (assets/logo/ploutos-signo.svg).

El dibujo se copia tal cual (mismo texto) y solo se le pone delante un translate+scale calculado con la
caja medida en Chrome (getBBox + medio trazo): x 22..78, y 25..76.5 con trazo 3 (centro 50, 50.75).
"""
import math
import re
import sys
from pathlib import Path

RAIZ = Path(sys.argv[1])          # el repositorio
OUT = Path(sys.argv[2])           # carpeta de salida
OUT.mkdir(parents=True, exist_ok=True)

FONDO, TINTA = "#1F5E7A", "#F3F6F5"
signo = (RAIZ / "assets/logo/ploutos-signo.svg").read_text(encoding="utf-8")
DIBUJO = re.search(r"</title>(.*)</svg>", signo, re.S).group(1)
assert DIBUJO.count("currentColor") == 2

CAJA = {3.0: (22, 25, 78, 76.5), 5.5: (22, 25, 78, 77.75)}


def colocar(escala, trazo=3.0):
    x0, y0, x1, y1 = CAJA[trazo]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    tx, ty = 50 - escala * cx, 50 - escala * cy
    d = DIBUJO.replace("currentColor", TINTA)
    if trazo != 3.0:
        d = d.replace('stroke-width="3.0"', f'stroke-width="{trazo}"')
    return f'<g transform="translate({tx:.4g} {ty:.4g}) scale({escala:g})">{d}</g>'


def svg(fondo, cuerpo, px):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="{px}" height="{px}" '
            f'role="img" aria-label="Ploutos"><title>Ploutos</title>{fondo}{cuerpo}</svg>')


REDONDO = f'<rect width="100" height="100" rx="22" fill="{FONDO}"/>'
LLENO = f'<rect width="100" height="100" fill="{FONDO}"/>'

# El maskable: la zona segura de Android es un circulo de radio 40 (80 % del lado). La esquina mas lejana
# de la caja tiene que caer dentro: semidiagonal * escala <= 40.
semi = math.hypot((78 - 22) / 2, (76.5 - 25) / 2)
ESC_MASK = 1.0
assert semi * ESC_MASK <= 40, semi * ESC_MASK

ICONOS = {
    # nombre: (svg, px)
    "favicon-a.svg": (svg(REDONDO, colocar(1.25), 32), 32),               # A: el dibujo exacto
    "favicon-b.svg": (svg(REDONDO, colocar(1.25, 5.5), 32), 32),          # B: mechas de 5,5 (como el de hoy)
    "apple-touch-icon.svg": (svg(LLENO, colocar(1.15), 180), 180),        # iOS redondea las esquinas el solo
    "icono-any.svg": (svg(REDONDO, colocar(1.25), 512), 512),             # manifest, "any"
    "icono-maskable.svg": (svg(LLENO, colocar(ESC_MASK), 512), 512),      # manifest, "maskable"
}
for nombre, (texto, _) in ICONOS.items():
    (OUT / nombre).write_text(texto, encoding="utf-8", newline="\n")
    # El dibujo dentro es EXACTAMENTE el del logo (menos el color y, en B, el grosor de las mechas).
    dentro = re.search(r'scale\([^)]*\)">(.*)</g></svg>', texto, re.S).group(1)
    esperado = DIBUJO.replace("currentColor", TINTA)
    if nombre == "favicon-b.svg":
        esperado = esperado.replace('stroke-width="3.0"', 'stroke-width="5.5"')
    assert dentro == esperado, nombre
print("ok; semidiagonal del maskable:", round(semi * ESC_MASK, 2), "de 40")
