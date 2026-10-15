# Cierre de la fase 4: ejecucion en el demo de OKX

**Estado: CERRADA el 10/10/2026** (el propietario: "Et dono el OK amb les teves recomanacions"). El juez dio CUMPLIDO a las
10:19 UTC. Preparado el 06/10/2026, puesto al dia el 07/10. La operacion completa YA esta
(dos, el 07/10: camino a); falta solo la semana, hasta el **10/10 10:16 UTC**. La seccion 6 se rellena el dia del
cierre con la salida de los comandos, tal cual, sin resumir.

**Al 07/10 17:40 UTC** (`check_exec.py`): 4,3 dias, 1.218 pasadas, sin descuadres, **2 operaciones completas**
("sin descuadres, pero solo 4.3 dias de 7"). El demo, sin posiciones y con 49,13 $.

La convencion (CLAUDE.md): al terminar una fase, parar, ensenyar que hay, como se prueba y si se cumple el criterio.
La fase 7 (dinero real) NO depende solo de esto: tambien pide una estrategia que no pierda en la reserva
(decision del 25/09) y el veredicto de la fase 6.

---

## 0. Cuando se cierra

Las tres cosas a la vez:

1. **7 dias de conciliacion** desde la foto del 03/10 10:16:28 UTC: como pronto el **10/10 a las 10:16 UTC**.
2. **Al menos una operacion completa en el demo** (decision del propietario del 03/10): compra, OCO y cierre. Si no la hay a
   los 7 dias, la semana se alarga sola hasta que la haya (`execution/juez.py`, `MIN_COMPLETAS`).
3. **Ningun descuadre** en toda la ventana (`check_exec.py` sin FALLA cada noche).

El juez de cada noche dice cuando se cumple (codigo 0). Hasta entonces da codigo 2 ("todo en orden, aun no").

### De donde puede salir la operacion completa

El demo copia la cartera de la IA en papel (decision 1), solo en los pares que tiene el demo (BTC, ETH, SOL y DOGE;
NEAR, por su comision, y XRP, AVAX y TRX, sin par, se quedan en papel). Hoy la cartera de la IA esta llena (AVAX, ETH y
SOL) y el demo tiene las dos que puede tener (ETH y SOL, adoptadas el 03/10). Caminos, del mas corto al mas largo:

| Camino | Que pasa | Cuenta como completa |
|---|---|---|
| a | El precio toca el stop o el objetivo de ETH o SOL: salta la OCO del demo | si (la OCO que salta es el cierre) |
| b | La cartera de papel cierra ETH o SOL por una noticia critica o "cerrar todo" | si (el demo vende a mercado con su id de salida) |
| c | Se cierra AVAX en papel (solo papel): queda un hueco, la IA abre otra en un par del demo, el demo la copia, se llena y despues se cierra | si, pero tarda mas: hace falta la entrada Y el cierre |

Lo que NO cuenta: una entrada copiada que caduca sin llenarse (no hay posicion ni OCO).

**Paso el camino a, el 07/10:** salto la OCO de las dos adoptadas, por el stop.

| | Abierta (adopcion) | Cerrada | Entrada | Salida | Resultado |
|---|---|---|---|---|---|
| ETH | 03/10 14:28 | 07/10 02:01 | 2.683,28 | 2.620,0 | -0,456 $ |
| SOL | 03/10 14:28 | 07/10 13:40 | 119,574 | 115,5 | -0,413 $ |

**SOL, el demo y el papel se separan por un centimo:** el stop del demo esta en 115,5 (el tick del demo es 10 veces
mas grueso y el stop se redondea al lado seguro, hacia arriba) y el del papel en 115,489. El minimo real de la vela de
las 12:00 fue **115,50**: el demo cerro y la cartera de la IA sigue con SOL. No es un fallo (es el hallazgo 4 haciendo
lo que debe) y el juez lo da por bueno: el demo cierra por su OCO, no por la del papel. Consecuencia: desde ahi el demo
no espeja la cartera de la IA en SOL; el juez lo sabe porque cruza lo que OKX hizo, no lo que el papel cree.

## 1. Los criterios, y como se comprueba cada uno

| # | Criterio | Juez o prueba | Que es FALLA |
|---|---|---|---|
| 1 | 1 semana sin descuadres (PRD 12) | `check_exec.py` | una diferencia que la conciliacion no explica en la misma pasada, o una posicion sin OCO mas de una pasada (decision 5); un hueco de mas de 15 min entre pasadas |
| 2 | Al menos una operacion completa (el propietario, 03/10) | `check_exec.py` (`operaciones completas`) | no es FALLA: sin ella la semana no se da por buena |
| 3 | Los tests de caos (PRD 12) | `docs/archivo/caos-fase-4.md` | cualquiera que deje un descuadre |
| 4 | La huella del camino de decision intacta | `check_fase6.py` | un tramo nuevo: el ejecutor copia, no decide |
| 5 | Los demas jueces de la noche sin FALLA | `jueces_diarios.py` | cualquiera |

**El juez es independiente del ejecutor:** solo comparte con el `execution/ids.py` (de un `clOrdId` a su
`decision_id`). Lee lo que el ejecutor apunto Y lo que contesto OKX, y lo cruza con la cartera de papel. Tiene tests
cruzados (una vida normal sin FALLA; una compra hecha a mano sale como FALLA).

### Los tests de caos (estado al 06/10)

| # | Caos | Estado |
|---|---|---|
| 1 | Matar el proceso con una ENTRADA viva | **espera** a que la IA mande una entrada nueva a un par del demo. Desde el 07/10 es mas probable: la cartera de la IA tiene un hueco (AVAX y SOL) y el demo esta vacio |
| 2 | Matar el proceso con una POSICION abierta | **hecho el 03/10**: cuadra, sin descuadre |
| 3 | Sin red | **hecho el 03/10**: DEGRADED a los 52 s, sale a los 10 min, cuadra |
| 4 | Errores repetidos del exchange | cubierto por el 3 |
| 5 | Cancelar a mano una OCO | **hecho el 03/10** (el propietario): rehecha en la pasada siguiente, cuadra |
| 6 | Llenado parcial y caducidad | cuando pase (no se puede forzar en el demo) |
| 7 | Reloj desfasado | no en el demo (afectaria a la ingesta y a la fase 6); cubierto por tests |
| 8 | Reinicio del servicio o del VPS | **hecho el 06/10** (a proposito, `systemctl restart`): en marcha en 6 s, la primera pasada cuadra, equity identico. **Y otra vez solo el 07/10 06:07 UTC**: las actualizaciones automaticas instalaron `libfreetype6` (y `sg3-utils`) y `needrestart` reinicio systemd y todos los servicios (lo previsto en `propuesta-actualizaciones.md`, entre dos cierres de vela); el ejecutor volvio en 9 s y siguio cuadrando |
| 9 | Cuota de la IA / JSON invalido | cubierto en la fase 3 |

**Propuesta para el cierre:** si la semana se cumple sin que hayan pasado el 1 o el 6, cerrar igual y
dejarlos apuntados como "no vistos en el demo, cubiertos por los tests del ejecutor contra el OKX simulado". Esperar a
que pasen solos podria no acabar nunca (el 6, en el demo, no pasa: su libro se repone al momento). Decide el propietario.

```bash
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_exec.py'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_exec.py --status'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_fase6.py'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/jueces_diarios.py --seco'
# Reinicios: NRestarts no cuenta los de needrestart; mirar CUANDO arranco.
ssh ploutos 'systemctl show ploutos-exec -p ActiveEnterTimestamp -p NRestarts -p MemoryPeak -p MemoryMax'
```

## 2. Que hay (desplegado desde el 03/10)

- `ploutos-exec`: el ejecutor. Una vuelta cada 15 s y una conciliacion entera cada 5 min, con su base
  (`var/ploutos-exec.db`). Es el UNICO servicio con las claves de OKX. No arranca con una clave real, con permiso de
  retirada ni sin `feeType 1`.
- **Saldo virtual de 50 $** (decision del 02/10): foto del saldo al arrancar y deltas desde entonces.
- **El motor de riesgo entero** antes de cada entrada copiada, con el estado del demo (decision del 02/10).
- **Stop y objetivo adjuntos a la entrada** (regla 13); entrada a medias -> se cancela el resto y OKX crea la OCO por
  lo llenado; OCO que falta -> se rehace en la pasada siguiente, al tick hacia el lado seguro.
- **Salidas que no son stop ni objetivo** (noticia, "cerrar todo"): cancela la OCO y vende a mercado con su id.
- **OCO rechazada con el precio ya pasado** (`51279`): vende a mercado (decision A del 03/10).
- DEGRADED con `core/salud.py` (3 errores seguidos, 2 s de reloj, 10 min sano para salir), tambien en la ingesta.
- Avisos de Telegram (modo, cierre con $ y R, parada y vuelta, descuadre, clave rechazada por OKX), latido a
  Healthchecks (8a comprobacion, 5 + 15 min), el juez cada noche (el noveno), la base en las copias.
- En el panel: "Demo de OKX", con el estado de la OCO de cada posicion.

## 3. Lo que se encontro por el camino

Lo de antes de desplegar esta en `docs/preparacion-fase-4.md` (11: las 9 pruebas; 12: el demo frente al mercado real;
13: la prueba 10) y en `docs/archivo/diseno-fase-4.md`. En resumen:

1. **El objetivo no puede ser limit en spot** (`51094`): sale a mercado, taker. El papel lo cobra maker: se corrige
   tras el veredicto de la fase 6 (decision del 02/10).
2. **NEAR paga el doble en el demo** (grupo de comision 13): solo en papel. La comprobacion es par por par.
3. **La OCO adjunta no nace hasta que la entrada se llena entera** o se cancela el resto: por eso se cancela el resto
   en el momento (decision del 02/10).
4. **El demo tiene ticks 10 veces mas gruesos** que el mercado real y su ultimo precio casi no se mueve. Los precios
   de las ordenes se reajustan al tick del demo.
5. **`51279`**: OKX rechaza una OCO si el precio ya paso el objetivo. Visto en la prueba 10; decidido vender a mercado.
6. **Revision del ejecutor (03/10), tres fallos arreglados:** doble venta si la OCO ya habia saltado, foto nueva con
   ordenes vivas en OKX y una entrada llenada por debajo de su stop.
7. **OCO rehecha redondeada al mas cercano** (test de caos 5: el objetivo 134,1 volvio como 134; un stop podria haber
   bajado): arreglado, ahora va al tick hacia el lado seguro.
8. **06/10, en el registro: un arranque cayo por `429` de OKX** (03/10 14:26:53, `account/trade-fee`, codigo `50011`),
   en medio de los reinicios de la adopcion de ETH y SOL. systemd lo relanzo a los 10 s y arranco bien; ningun efecto
   en la conciliacion. **Causa probable:** dos procesos con la misma clave pidiendo las comisiones a la vez (el limite de
   OKX es por clave; el freno de ccxt, por proceso). **Con un solo proceso no pasa:** ccxt espera 440 ms entre esas
   peticiones (coste 4 x 110 ms, comprobado en ccxt 4.5.84), unas 4,5 cada 2 s; con las 8 monedas de la fase 7 el
   arranque tardaria ~3,5 s en lugar de caer. No hace falta cambiar nada; si se quiere, un reintento en el arranque.
9. **La semana podia pasar sin una sola orden** (la cartera de la IA llena antes de la foto): de ahi la operacion
   completa obligatoria y la adopcion de ETH y SOL (decisiones A y B del 03/10).

10. **07/10: tres `50026` del demo** ("System error. Try again later", 08:52, 09:22 y 09:24 UTC), sueltos: ninguno llego
    a los 3 seguidos de DEGRADED y la pasada siguiente leyo bien. Es el demo de OKX, no el ejecutor.
11. **El tick grueso del demo puede separarlo del papel** (SOL, 07/10, seccion 0): el stop redondeado al lado seguro
    salta antes. En la cuenta real el tick es el fino y el stop sera el mismo que el del papel.

**Recursos (06/10 09:30 UTC, 3 dias de servicio):** el ejecutor ocupa 104 MB de 300 MB (`MemoryMax`), 0 reinicios
desde el 03/10 16:01, 839 pasadas y todas cuadran. **07/10 17:40 UTC:** pico de 103 MB desde el reinicio de las 06:07,
1.218 pasadas, todas cuadran.

## 4. Lo que queda despues del cierre

- Borrar la rama `fase-4-piezas-puras` (todo esta en `main` desde el 03/10).
- ccxt 4.5.85 (aplazada hasta despues de la semana): con los tests y las peticiones a OKX comparadas.
- Actualizar CLAUDE.md ("Estado ahora") y la memoria.
- El ejecutor **sigue corriendo** despues del cierre: el demo es el ensayo de la fase 7 y no cuesta nada. Si el propietario
  prefiere pararlo, avisar antes (Healthchecks salta a los ~20 min).

## 5. Decisiones para el propietario el dia del cierre

1. Cerrar la fase 4 con lo que diga el juez.
2. Los tests de caos que no hayan pasado solos (1 y 6): cerrar con ellos apuntados (recomendado) o esperar.
3. Seguir con el ejecutor en marcha (recomendado) o pararlo.

## 6. Resultados

Rellenado el **10/10/2026 a las 10:20 UTC**, con la salida de los comandos tal cual, en el VPS.

### `check_exec.py`

```
Ejecutor del demo: 7.0 dias de conciliacion desde la foto
  enviadas en papel: 0
  mandadas al demo: 0
  adoptadas: 2
  salidas a mercado: 0
  salidas por precio pasado: 0
  pasadas: 1981
  operaciones completas: 2

RESULTADO: CUMPLIDO (una semana sin descuadres).
codigo: 0
```

`run_exec.py --status`:

```
foto: 03/10 10:16:28, capital 50.0 $
modos: NORMAL
equity: 49.13 $ (fiable) a las 10/10 10:19:10
cerradas hoy: 0, +0.00 $
ultima conciliacion: 10/10 10:18:24, cuadra
```

### `check_fase6.py` (la huella)

```
Fase 6, IA contra baseline. Tramo f063d80147a9 desde 25/09/2026 12:00 UTC
  Datos
    OK    journal completo y coherente con la salida guardada
    OK    mismos candidatos en las dos carteras (4 comparados)
  Muestra
    velas en que la IA y el baseline discrepan: 5 de 30
    calendario: minimo 16/10/2026, tope 20/11/2026
VEREDICTO: todavia no (faltan 6 dias y 25 discrepancias). Los datos estan bien.
```

### Jueces de la noche (`jueces_diarios.py --seco`, 10:19 UTC)

```
papel del baseline: codigo 0
papel de la IA: codigo 0
fase 3 (el analista en sombra): codigo 0
fase 6 (IA contra baseline): codigo 2
fase 6 en sombra (otra medicion): codigo 2
noticias: codigo 0
comandos de Telegram: codigo 0
bloqueos silenciosos: codigo 0
ejecucion en el demo: codigo 0
papel de L: codigo 2
todo en orden: no se manda nada
```

### Veredicto

**El juez da CUMPLIDO** (criterios 1 y 2: 7,0 dias, 1.981 pasadas, todas cuadran, 2 operaciones completas). Caos: 2,
3, 5 y 8 hechos; 1 y 6 pendientes de que pasen solos (`docs/archivo/caos-fase-4.md`). La huella de la fase 6, intacta.
**Decision del propietario (10/10), las tres recomendadas:** (1) la fase 4 se CIERRA con el veredicto del juez; (2) los caos 1
y 6 quedan apuntados como pendientes (se haran cuando pasen solos); (3) el ejecutor del demo SIGUE en marcha (ensayo
de la fase 7). Hecho despues: la rama `fase-4-piezas-puras` borrada (local, remota y su copia de trabajo; 0 commits
fuera de `main`). ccxt 4.5.85, instalada el 10/10 a las 10:46 UTC (`docs/archivo/parada-mantenimiento-fase-4.md` 11).
