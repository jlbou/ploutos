# Logo de Ploutos

La Π de Ploutos (Πλοῦτος, el dios griego de la riqueza) con dos velas de grafico colgando de
su barra: la de la derecha, mas arriba (un precio que sube). Azul petroleo `#1F5E7A` sobre
`#F3F6F5`, los del panel. Elegido por el propietario el 25/09/2026 (concepto B).

| Fichero | Para que |
|---|---|
| `ploutos.svg`, `ploutos-512.png` | web y README: el circulo |
| `ploutos-perfil.svg`, `ploutos-perfil-512.png` | foto de perfil de Telegram y GitHub: cuadrado lleno; ellos lo recortan en circulo y el signo cabe |
| `ploutos-signo.svg` | solo el signo, del color del texto (`currentColor`): sobre cualquier fondo |
| `favicon.svg`, `favicon-32.png` | pestanya del navegador (16-32 px): el mismo dibujo con las mechas de 5,5 en vez de 3, para que se lean (el propietario, 17/10) |
| `apple-touch-icon.svg`, `favicon-180.png` | pantalla de inicio del iPhone: cuadrado lleno (iOS redondea las esquinas), dibujo exacto |
| `icono-any.svg`, `icono-maskable.svg` | el manifest de Android (192 y 512 px): la "any" con esquinas redondeadas y la "maskable" a sangre, con el dibujo dentro de la zona segura (semidiagonal 38,04 de 40) |
| `social-preview-1280x640.png` (de `social-preview.html`) | GitHub, *Settings -> Social preview*: lo que se ve al compartir el enlace del repositorio |

Las iconas (17/10) salen de `generar_iconos.py`: copian TAL CUAL el dibujo de `ploutos-signo.svg` y lo centran con su caja
medida en el navegador (getBBox + medio trazo: x 22-78, y 25-76,5), no a ojo; el script comprueba que el dibujo de dentro es
el del logo. Los PNG salen de los SVG con Chrome sin ventana (sin dependencias nuevas). Si se cambia un SVG,
regenerarlos. En lo que ve el propietario no se nombra a Claude (decision del 25/09): se dice "la IA".
