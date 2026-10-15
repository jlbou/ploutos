# Diseno: la API del panel (fase 5)

Estado: **DECIDIDO por el propietario el 25/09/2026: 1a, 2a, 3b y 4a** (seccion 7). No hay codigo.
Foto entera por WebSocket; pagina propia sin compilar; todos los controles **sin PIN** (Tailscale
como unica barrera; cerrar todo, con doble confirmacion); slider bloqueado en el nivel 3.
PRD seccion 10 (interfaz) y 12 (fase 5: "todos los paneles con datos reales"); informe 5.1-5.3.
La maqueta visual ya existe: `docs/archivo/esbozo-panel-fase-5.html` (artifact privado del propietario).

## 1. Lo que piden el PRD y el informe

- PRD 10: dashboard en tiempo real, **FastAPI + WebSocket + SPA**, solo por Tailscale (decidido el
  25/09). Paneles: barra de estado, slider, diagrama por nodos, "que esta pensando la IA",
  controles de seguridad, posiciones, historico con CSV fiscal, curva comparada, hipotesis y
  aprendido. "La UI es de solo lectura sobre el estado; sus comandos pasan por el motor de riesgo
  y se auditan."
- Informe 5.1: REST para fotos (`/state`, `/trades`...) y un WebSocket que emite **deltas** con
  numero de secuencia a 1-2 Hz; SPA en **React + Vite** con **React Flow** para los nodos y
  **Lightweight Charts** para las curvas.

## 2. Tres cosas del informe que cambiaria (decide el propietario)

**a) Deltas con secuencia -> la foto entera cuando cambia.** El informe copia el patron de un
dashboard de trading de alta frecuencia. Aqui se decide cada 4 h y, en la fase 4, el equity se lee
cada 15 s. La foto entera del estado ocupa unos pocos KB. Mandarla completa cada vez que cambia
(mirando cada 2 s) da la misma sensacion de "en vivo" y quita de raiz el problema que el informe
resuelve con secuencias: con fotos enteras **no se puede desincronizar**, porque cada mensaje es
el estado completo. Menos codigo, menos fallos, el mismo resultado en pantalla.

**b) React + Vite + React Flow -> HTML y JavaScript propios, sin compilar.** React obliga a tener
Node y npm, un paso de compilacion y cientos de paquetes de terceros en el portatil (y su
mantenimiento). La maqueta ya esta hecha en HTML y JavaScript sin nada mas, y cubre todos los
paneles. El diagrama del sistema son ~12 nodos fijos: un SVG propio basta; React Flow sirve para
diagramas que el usuario edita, no es el caso. Para las curvas, **Lightweight Charts** si (un solo
fichero de JavaScript, open source), **guardado en el repo**, no desde un CDN: el panel no depende de
Internet ni avisa a nadie de cuando se abre.

**c) El estado de cada nodo -> deducido de las bases, no de un diccionario en memoria.** El informe
propone que cada componente actualice un `node_status` en memoria. Aqui cada parte es un servicio
distinto (ingesta, dos carteras, noticias, Telegram): compartir memoria obligaria a montar un canal
entre procesos. En cambio, todos escriben ya en su base cuando trabajan (la ultima vela, la ultima
lectura, la ultima vuelta). El panel mira **que tan fresco** es lo ultimo de cada uno: verde si
toca, ambar si va tarde, rojo si lleva demasiado sin nada. Es lo mismo que mide Healthchecks, visto
desde dentro, y no hay nada nuevo que pueda fallar. Lo que se pierde: las aristas animadas "cuando
pasa un mensaje" (no hay mensajes que ver pasar).

## 3. La propuesta

### Un servicio aparte, `ploutos-panel`, que solo LEE

- Abre todas las bases en `mode=ro`: la principal (velas, spread), las dos carteras, noticias y
  control. **No importa `ai/`, no habla con el exchange ni con Claude.** Si el panel se cae o se
  cuelga, el bot no se entera.
- **Escucha solo en la IP de Tailscale** del VPS (decision del 25/09). El cortafuegos no cambia.
- Coste: ~70-90 MB (FastAPI + uvicorn). El VPS tiene 2 GB y 1 GB de swap tras la fase 3.

### Lo que expone

| Ruta | Que devuelve | Panel | Fuente |
|---|---|---|---|
| `GET /api/foto` | El estado entero: por cartera (baseline, IA) equity, P&L del dia, drawdown, distancia al suelo, operaciones hoy, posiciones con su stop/objetivo/P&L en R, pendientes, modo y modos activos; pausa y parada; flags de noticias; llamadas a la IA hoy/40; frescura de cada servicio; limites duros (solo lectura); dias hasta que caduca el token | barra de estado, posiciones, controles, sistema | `paper_*`, `ai_calls`, `news_*`, `control_*`, `candles` |
| `WS /ws` | La misma foto, cada vez que cambia (se mira cada 2 s) | todos los de arriba | - |
| `GET /api/curva?desde=` | Equity de las dos carteras y "comprar y esperar BTC" | curva comparada | `paper_equity`, `candles` |
| `GET /api/operaciones?cartera=&desde=` | Cerradas, con comisiones, R, duracion, setup, motivo | historico | `paper_trades` |
| `GET /api/operaciones.csv` | Lo mismo en CSV (en papel no es fiscal; en la fase 7, si) | historico | `paper_trades` |
| `GET /api/decisiones?simbolo=&limite=` | Linea temporal de la IA: candidatos, eleccion y justificacion (etiquetada como "lo que escribe la IA", no su razonamiento), veredicto del motor, orden | que esta pensando la IA | `ai_calls`, `ai_decisions`, `paper_decisions` |
| `GET /api/monedas` | Por cada una de las 8, donde se quedo en la ultima vela ("descartada por spread", "candidato", "vetada por correlacion", "posicion abierta"...) | sistema, vista por moneda | `paper_decisions` |
| `POST /api/comandos` | Los controles (seccion 4) | controles | escribe en `control_comandos` |
| `GET /` | La pagina (ficheros estaticos) | - | `ui/` |

Las hipotesis y lo aprendido (fase 8) salen vacios con el texto "fase 8" hasta que exista el bucle
de aprendizaje.

### Frescura y errores

- Cada panel ensenya "actualizado hace X s" y, si el WebSocket cae, un banner rojo y los datos en
  gris (informe 5.1: una UI con datos viejos que parecen actuales es peor que no tenerla).
- Si una base no se puede leer, esa parte de la foto va marcada "sin datos", no con ceros.

## 4. Los controles

Los comandos del panel entran en **la misma base y la misma tabla** que los de Telegram
(`control_comandos`, origen `panel`), asi que las carteras siguen teniendo UNA sola fuente de pausa
y parada, y los dos jueces (`check_paper`, `check_control`) los cubren sin cambios de fondo. La base
de control pasa a tener dos escritores (el servicio de Telegram y el panel): con la poca frecuencia
de los comandos y el `busy_timeout` de SQLite no es un problema, pero se dice.

**Decidido (3b):** pausar, quitar la pausa, parar, levantar la parada y cerrar todo (este con doble
confirmacion), **sin PIN**: Tailscale es la unica barrera. El reset del suelo, solo en el VPS.
Consecuencia asumida: con el movil desbloqueado se puede reabrir el bot. Hace falta: una migracion
de la base de control (origen `panel`) y ensenyar a `check_control.py` que desde el panel si se
puede levantar la parada.

Propuesta (decision 3): pausar, quitar la pausa, parar, **levantar la parada** (la decision del
25/09 ya lo dejo al VPS o al panel) y **cerrar todo** con doble confirmacion. El reset del suelo
de capital (regla 7), solo en el VPS. Levantar la parada y cerrar todo piden ademas un **PIN** que
el propietario pone en `.env`: Tailscale ya limita el panel a sus aparatos, pero un movil desbloqueado en
manos de otro no deberia poder reabrir el bot.

## 5. El slider (decision 4)

El PRD lo pone en el panel, con efecto desde el dia siguiente y sin tocar las reglas duras. Pero
**cambiar el nivel cambia la estrategia** (riesgo por operacion, setups permitidos): si se toca
durante la muestra de la fase 6, esa muestra se parte en tramos (decision 1 del protocolo). Y el
anyo medido dice que la estrategia pierde: subir el nivel antes de revisarla es arriesgar mas en
algo que pierde.

## 6. La dependencia nueva

**FastAPI + uvicorn** (y `websockets`, que uvicorn usa para el WebSocket). Justificacion: el PRD
los nombra; FastAPI valida con `pydantic`, que ya usamos; uvicorn es el servidor que recomienda.
Descartados: el `http.server` de Python (no tiene WebSocket) y Streamlit (el informe ya lo
descarta: re-ejecuta el script entero y no sirve para empujar datos). Se fijan las versiones.

## 6b. Estado (26/09)

**Hecha la parte de LECTURA, en el portatil, sin desplegar** (con el OK del propietario del 26/09, como las
piezas puras de las fases 3 y 4): `api/foto.py` (la foto entera, con el estado de cada servicio deducido
de lo fresco de su base) y `api/app.py` (`GET /api/foto` y `WS /ws` con la foto entera cuando cambia).
FastAPI 0.141.1, uvicorn 0.54.0 y websockets 17.1 fijados en el extra `panel` del `pyproject.toml`; en el
VPS no estan. 10 tests; el test de arquitectura prohibe a `api/` importar `ai/` y `execution/`. Probado de
verdad con uvicorn en el portatil sobre copias reales.

**La pagina (26/09), tambien sin desplegar:** `ui/index.html` y `ui/panel.js`, con el disenyo de la maqueta
(colores, modo oscuro) pero sin fuentes ni scripts de Internet; todo el texto como texto, nunca como HTML.
Ensenya las dos carteras (equity, hoy, caida, distancia al suelo, operaciones, posiciones, llamadas a la IA,
modo), la pausa y la parada, las posiciones valoradas, las pendientes, el estado de cada servicio, las
noticias, los limites y el slider bloqueado. Si el WebSocket cae: banner rojo y todo en gris. Probada en el
navegador con copias de las cinco bases del VPS de esa manyana, en escritorio y en movil (375 px, sin
desplazamiento lateral; la cabecera deja de ser fija en pantallas estrechas). Faltan: la curva (hace falta
bajar Lightweight Charts: con permiso del propietario), los controles (con la migracion de la base de control para el
origen `panel`), Tailscale y el despliegue.

**DESPLEGADO el 26/09/2026 (solo lectura)**, a peticion del propietario: Tailscale en el VPS (repositorio oficial
firmado, 1.102.4, `tailscale up --hostname=ploutos` autorizado por el propietario desde su cuenta; clave hasta el
25/03/2027), FastAPI/uvicorn/websockets fijados en el entorno del VPS y el servicio `ploutos-panel`
(`scripts/run_panel.py`: escucha SOLO en la IP de Tailscale; si no la hay, no arranca). Cortafuegos: el 8765
solo en `tailscale0`. Comprobado: responde por Tailscale; ni en 127.0.0.1 ni en la IP publica. Direccion:
`http://ploutos.example.ts.net:8765`.

**COMPLETO como la maqueta el 26/09/2026** (a peticion del propietario, en cuatro piezas, cada una con tests y desplegada):
1. "Que esta pensando la IA" (por vela: su lectura, cada candidato con sus numeros, lo que decidio, confianza,
   motivos, riesgos y el veredicto del motor) y las operaciones cerradas con su CSV (`api/historial.py`).
2. La vista por moneda (donde se quedo cada una en la ultima vela y por que) y el slider con sus 5 niveles,
   bloqueado en el 3.
3. La curva comparada (IA, baseline y comprar BTC y esperar) con Lightweight Charts 5.2.1 guardado en
   `ui/vendor/` (bajado con permiso del propietario; su huella la comprueba un test).
4. Los controles (`api/mando.py`): pausar, quitar la pausa, parar, levantar la parada (con motivo) y cerrar
   todo (dos confirmaciones; vende todo al cierre de la vela y deja el bot en pausa). Solo desde el propio
   panel: cabecera `X-Ploutos-Panel` y `Origin` del panel (otra web no puede pulsarlos). Entran en
   `control_comandos` con origen `panel` (migracion 002) y los jueces los cubren.
"Hipotesis y aprendido": el hueco, hasta la fase 8. Sin PIN, como decidio el propietario: Tailscale es la barrera.

## 7. Decisiones para el propietario

**1. Como se actualiza.**
- a) **WebSocket con la foto entera cuando cambia** (recomendado).
- b) Deltas con numero de secuencia, como el informe.
- c) Sin WebSocket: el navegador pregunta cada 10 s (se aparta del PRD).

**2. Con que se hace la pagina.**
- a) **HTML y JavaScript propios, sin compilar**, con Lightweight Charts guardado en el repo (recomendado).
- b) React + Vite + React Flow, como el informe.

**3. Que controles tiene el panel.**
- a) **Pausar, quitar la pausa, parar, levantar la parada y cerrar todo**; los dos ultimos con PIN y
  cerrar todo con doble confirmacion; el suelo, solo en el VPS (recomendado).
- b) Lo mismo sin PIN (Tailscale como unica barrera).
- c) Panel de solo lectura: los controles, en Telegram y el VPS.

**4. El slider.**
- a) **Se ve, pero bloqueado en el nivel 3 hasta cerrar la fase 6 y revisar la estrategia** (recomendado).
- b) Activo desde la fase 5, con efecto al dia siguiente.
