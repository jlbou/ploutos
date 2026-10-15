# `claude -p` verificado contra el binario real

Movido de CLAUDE.md el 22/09/2026, **sin cambiar una palabra**: flags, token, coste por llamada, esquema, latencia.
Lo que sigue vigente como regla, decision o aviso esta resumido en CLAUDE.md;
aqui queda el como y el por que, con los numeros.

---

## `claude -p` VERIFICADO contra el binario real (22/09/2026)

`scripts/verify_claude_cli.py`. Sin `--call` no gasta cuota; con `--call` hace UNA
llamada (de las 40 de la regla 18).

### El token del `.env` estaba ROTO, y no se habia notado

**Tiene un espacio en mitad de la cadena**, metido al pegarlo: la terminal lo corto
en dos lineas y el salto se convirtio en espacio.

No se habia visto porque **en el portatil el CLI usa las credenciales de la sesion
iniciada y nunca llega a mirar el token del `.env`**. En el VPS no hay sesion: alli
el token es lo unico que hay, y la fase 3 habria fallado en su primera llamada.

Leccion: comprobar que un secreto "esta puesto" no basta; hay que mirar que tenga
forma de secreto. `verify_claude_cli.py` ahora lo hace (sin imprimir el valor).

**Regenerado por el propietario el 22/09/2026.** `verify_claude_cli.py` da el formato por bueno.
Ojo: el script se lanza con `.venv/Scripts/python.exe`; con `py -3.12` falla al
importar `pydantic` y parece un problema del token sin serlo.

**Verificado que VALE, no solo que tiene forma** (22/09/2026). Para que el CLI no
usara la sesion del portatil se lanzo con un entorno limpio: sin ninguna variable
`CLAUDE*`/`ANTHROPIC*` y con `CLAUDE_CONFIG_DIR`, `HOME` y `USERPROFILE` apuntando a
un directorio vacio. Primero un CONTROL sin token, que tenia que fallar y fallo
(`Not logged in`): sin ese control, un "funciona" no demostraria nada. Despues,
con solo `CLAUDE_CODE_OAUTH_TOKEN`: respuesta correcta. Es lo mas parecido al VPS
que se puede hacer desde aqui.

**Hallazgo de paso:** una sesion de Claude Code lanzada desde la app de escritorio
hereda variables del host, entre ellas `ANTHROPIC_BASE_URL`. Las mediciones de
coste de arriba se hicieron con ese entorno heredado, no con uno limpio como el
del VPS. **Vuelto a medir en entorno limpio: el heredado DOBLABA el coste** (ver
"El coste por llamada" mas abajo). `verify_claude_cli.py --sin-sesion` hace esta
prueba entera, control incluido, y es la que hay que repetir en el VPS.

### Flags: el informe tenia razon, el error fue mio

`--json-schema` recibe el esquema **en linea**, no una ruta de fichero. El informe
(linea 183) ya lo hace bien con `"$(cat schema.json)"`; el que lo leyo mal fui yo.
Pasarle una ruta da `JSON Parse error`, que no ayuda nada.

Confirmado tambien: `--max-turns` y `--append-system-prompt-file` **siguen sin
existir**. Y aparece uno nuevo util para la regla 18: **`--max-budget-usd`**, un
tope de gasto por llamada.

Hace falta `< /dev/null`: si no, el CLI espera 3 s por si le llega algo por stdin.

### Las herramientas estaban encendidas, y salian caras

Por defecto `claude -p` llega con Bash, WebFetch y las demas, **incluso lanzandolo
desde un directorio vacio**. Se notaba: `num_turns: 3` y `stop_reason: "tool_use"`
para una pregunta que solo pide elegir entre candidatos.

Medido, misma pregunta, con y sin herramientas:

| | con herramientas | restringido |
|---|---|---|
| turnos | 3 | 2 |
| tokens de salida | 2.348 | 829 |
| duracion | 26,1 s | **7,9 s** |
| coste equivalente | 0,235 $ | 0,155 $ |

(Las dos columnas en el entorno heredado: la comparacion entre ellas vale, los
valores absolutos no. Ver la correccion mas abajo.)

Flags recomendados, y estan en el script: `--restricted --disable-slash-commands
--strict-mcp-config --setting-sources '' --no-session-persistence`.
No es solo coste: un analista que puede ejecutar Bash es un analista que puede
hacer cosas, y el PRD seccion 6 dice que la IA no hace, opina.

### El coste por llamada, y por que el numero grande es el que vale

**CORREGIDO el 22/09/2026.** Las primeras mediciones se hicieron desde una sesion
lanzada por la app de escritorio, que hereda variables del host, y cargaban casi
el DOBLE de contexto. Repetido con el mismo prompt, el mismo esquema y los mismos
flags pero en entorno limpio (`--sin-sesion`, lo que habra en el VPS):

| | entorno heredado | **entorno limpio** |
|---|---|---|
| contexto (cache creada) | ~29.000-36.000 | **16.919** |
| coste equivalente, cache fria | 0,155 $ | **0,0745 $** |
| latencia | 7,9 s | 9,1 s |

Una sola muestra en limpio, pero el coste lo domina un contexto fijo, asi que no
deberia variar mucho. **El numero bueno es 0,0745 $.** La cache caliente se midio
solo en el entorno heredado (0,030 $) y no se ha repetido: no hace falta, porque
no es nuestro caso.

La segunda llamada seguida cuesta cinco veces menos porque reutiliza la cache.
**Pero nuestras llamadas van separadas por HORAS** (velas de 4 h), y las ventanas
de cache se miden en minutos. O sea que **el caso real es siempre la cache fria**.

Con 40 llamadas/dia (regla 18) a 0,0745 $: **~3 $/dia, unos 89 $/mes equivalentes,
sobre un capital de 50 $** (la primera cifra, 186 $/mes, salia del entorno heredado).

Eso NO es dinero que el propietario pague: con la suscripcion (`CLAUDE_CODE_OAUTH_TOKEN`) es
una tarifa plana y el numero solo mide consumo de cuota. Pero conviene tenerlo
delante: el informe seccion 2.1 estima que un bot excelente sacaria 1-2,50 $/mes
con 50 $. **Con facturacion por uso, el analisis costaria del orden de cuarenta a
noventa veces lo que el bot puede ganar.** El proyecto se sostiene porque la cuota es plana y porque el PRD
dice que la rentabilidad es secundaria; con API de pago no se sostendria.

El grueso del coste es fijo: ~17.000 tokens de contexto propio de Claude Code por
llamada en entorno limpio, independientemente de lo corto que sea nuestro prompt.

### Lo que el esquema SI fuerza y lo que NO

Se le pidio a proposito que se saltara el contrato (`size_multiplier: 2.0` y un
`cid` inventado). No lo hizo: devolvio solo el `cid` real con multiplicador 1.

Pero hay que separar dos cosas:

- **El esquema SI impide** un `size_multiplier` fuera de [0,5; 1,0]: esta en el
  JSON Schema como `minimum`/`maximum`.
- **El esquema NO impide un `cid` inventado**, porque `cid` es solo un string. Que
  no lo inventara fue el modelo portandose bien, no una garantia.

O sea que la regla del informe seccion 1.5 ("si la IA inventa un cid, se descarta
la decision entera") **hay que implementarla en el parser**. No se puede delegar en
el esquema.

Detalle util: la salida ya parseada viene en la clave **`structured_output`** del
sobre de `--output-format json`. Mejor que parsear `result`.

### Latencia

9-26 s segun los flags. El `timeout_seconds: 90` de `settings.yaml` da margen, pero
no tanto como parecia: con varios candidatos el prompt crece.

### En el VPS NO hay nada de esto instalado

Ni `claude` ni `node`. **La fase 3 necesita instalar el CLI en el servidor**, y
eso no estaba escrito en ningun sitio. El `.env` del servidor solo tiene las claves
de OKX (permisos 600, correcto): habra que anyadirle el token.

### Como se instala en el VPS (23/09/2026, verificado en la documentacion oficial)

`deploy/install-claude.sh`, escrito y SIN ejecutar todavia (pieza 11).

- **No hace falta Node.js.** La del portatil, la verificada, es la instalacion
  NATIVA (`~/.local/share/claude/versions/<version>` es el binario). Node solo lo
  pide la de npm, y desde la 2.1.198 pide Node 22.
- **Version fija:** `install.sh` acepta la version (`bash -s 2.1.266`). La
  verificada vive en `ai.invoke.VERIFIED_VERSION` y un test comprueba que el
  instalador pone esa.
- **La nativa se actualiza SOLA** en segundo plano. En el portatil paso: hay
  `2.1.246`, `2.1.247` y `2.1.266` en `versions/`. Un CLI que cambia por su cuenta
  invalida lo verificado, asi que el bot lo lanza con `DISABLE_UPDATES=1` y
  `DISABLE_AUTOUPDATER=1` **en el entorno** (con `--setting-sources ''` no se lee
  ningun `settings.json`), y `/usr/local/bin/claude` apunta al binario de esa
  version, no al lanzador que las actualizaciones mueven.
- **Integridad:** cada version publica un `manifest.json` con el sha256 de cada
  plataforma, firmado con la clave de Anthropic (huella
  `31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE`). Comprobado desde el portatil para la
  2.1.266: firma valida (`VALIDSIG`), estructura `platforms.linux-x64.checksum`, y
  el `claude.exe` del portatil **coincide** con el sha256 firmado de `win32-x64`.
  El binario de Linux pesa 216 MB (el disco del VPS tiene 53 GB libres).

### La memoria del VPS no llega a lo que pide Claude Code

La documentacion pide **4 GB de RAM**. El VPS tiene **2 GB y sin swap** (medido el
23/09/2026: 1.967 MB, 1.107 MB disponibles con la ingesta, el papel y la medicion del
spread en marcha, ~560 MB entre los tres). Sin swap, si una llamada pide mas de lo
que queda, el kernel mata un proceso, y puede ser la ingesta. Decision del propietario, antes
de enchufar la IA al bucle.

**Medido en el portatil (23/09/2026, 2 llamadas reales del analista, 4 y 3
candidatos, `dry_run_analyst.py`, siguiendo los procesos hijos cada 200 ms):**

| | llamada 1 | llamada 2 |
|---|---|---|
| `claude.exe`, pico de memoria residente | 382 MB | 409 MB |
| `claude.exe`, memoria privada maxima | 364 MB | 500 MB |
| el Python que la lanza | 161 MB | 160 MB |
| duracion | 32 s | 34 s |

Es el binario de Windows; el de Linux es el mismo programa, pero la cifra del VPS
hay que medirla alli (`install-claude.sh` deja el comando). **Cuenta para el VPS:**
~1.280 MB libres cuando acabe la medicion del spread; un bucle de papel de la IA
(~170 MB) y una llamada (~500 MB) dejan **~600 MB de margen y sin swap**. Cabe, pero
sin colchon. Propuestas en `docs/archivo/diseno-pieza-9.md`.
