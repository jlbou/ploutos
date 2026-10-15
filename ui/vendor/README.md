# Librerias de terceros del panel

Guardadas en el repositorio a proposito (decision del propietario del 25/09/2026): el panel no pide nada a
Internet. Descargadas con el permiso expreso del propietario (26/09/2026).

| Fichero | Que es | Version | Origen | SHA-256 (base64) | Licencia |
|---|---|---|---|---|---|
| `lightweight-charts.standalone.production.js` | Lightweight Charts, de TradingView: la curva comparada | 5.2.1 | paquete npm `lightweight-charts`, via cdn.jsdelivr.net | `4hzFyqAibvML2FScULnvkmYV8qTua05IY1NHelX1mM8=` (coincide con el publicado) | Apache-2.0 (cabecera del propio fichero) |

**Letras (27/09/2026, permiso expreso del propietario):** las de la maqueta, en `fonts/`, del paquete npm `@fontsource`
5.2.5 via cdn.jsdelivr.net, solo el subconjunto latino (tildes, enye y cedilla incluidas). Licencia SIL OFL 1.1
(se pueden redistribuir con el programa). 7 ficheros, 147 KB:

| Fichero | Letra | SHA-256 (base64) |
|---|---|---|
| `barlow-semi-condensed-latin-600-normal.woff2` | Barlow Semi Condensed 600 (etiquetas) | `V62jRdxnewthTZ8553X+3eLS7EnylmBlTLulKxtaIiA=` |
| `barlow-semi-condensed-latin-700-normal.woff2` | Barlow Semi Condensed 700 (titulos) | `KrcdErJOWt4CgAcddJ/ewWhMJW05eiWPeBdvLU9bUk8=` |
| `ibm-plex-sans-latin-400-normal.woff2` | IBM Plex Sans 400 (texto) | `O2RpkdMAVak6TsxJlxPUNHlTp0qUfsq0NatyBwy9qw4=` |
| `ibm-plex-sans-latin-500-normal.woff2` | IBM Plex Sans 500 | `Bxczb7Mfzc3kuN6zZ1u0oPf21ISGSvzWdRrCmXWWIgM=` |
| `ibm-plex-sans-latin-600-normal.woff2` | IBM Plex Sans 600 | `iWCFHWkcBU7TjiWb3PGmGQ0Ve0ID7VuzLGMqhj+47C8=` |
| `ibm-plex-mono-latin-400-normal.woff2` | IBM Plex Mono 400 (cifras) | `PFpFH57CejVLDCvMpjbG7BemUSgaq/KfhCfiEKHTHoU=` |
| `ibm-plex-mono-latin-500-normal.woff2` | IBM Plex Mono 500 | `dWAm/3Lrdv2XGsS3UEzsVe72IQnSaEwsrY2jIXC4Czc=` |

`tests/unit/test_api_foto.py` comprueba la huella: si alguien cambia el fichero, el test se pone en rojo.
Para actualizarla: bajar la version nueva, comprobar su huella contra la publicada y cambiar la de aqui y la del test.
