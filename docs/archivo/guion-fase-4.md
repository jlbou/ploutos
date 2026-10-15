# Guion de la fase 4: del OK del propietario a "1 semana sin descuadres" en el demo

Preparado el 28/09/2026 a peticion del propietario. **Estado: GUION; nada empieza sin el OK del propietario a la fase 4 (02/10).**
El disenyo y sus seis decisiones: `docs/archivo/diseno-fase-4.md`. Las trampas de OKX y ccxt: `docs/preparacion-fase-4.md`.

A diferencia del de la fase 3, esto no es solo desplegar: la fase 4 esta a medias. En la rama `fase-4-piezas-puras`
estan las piezas PURAS (ids, guardia, precios, conciliacion, equity, salud/DEGRADED, peticiones, plan y el nucleo del
juez), con tests y sin enchufar. Falta lo que habla con OKX y el servicio. Por eso el guion tiene dos partes:
**construir (en el portatil y el demo)** y **desplegar y medir (en el VPS)**.

**Nada de dinero real:** solo la cuenta demo de OKX (regla del proyecto hasta la fase 7). La clave `ploutos-demo` ya
esta en el `.env` del VPS (verificada el 28/09 al poner la comision en USDC), sin retirada y solo con la IPv4 del VPS.

## 0. Condiciones para empezar

- [ ] Fase 3 CERRADA el 02/10 (`cierre-fase-3.md`, los cuatro criterios) y **OK del propietario a la fase 4**.
- [ ] Decidida la sombra (`propuesta-candidatos-sombra.md`): si es la B, va ANTES que esto (toca el servicio de la IA,
      que el demo va a copiar).
- [ ] Recordatorio: la cartera que copia el demo es la de la IA (decision 1); la de papel sigue midiendo la fase 6.

## PARTE 1: construir

### 1. La parada de mantenimiento (VPS, 30-40 min)

`docs/archivo/parada-mantenimiento-fase-4.md`: ccxt 4.5.84 (ya probado) y los paquetes de Ubuntu que no son de seguridad.
Va primero para que todo lo de despues se pruebe con la version que se quedara.

### 2. Comprobar la cuenta demo (VPS, sin ordenes) — HECHO el 02/10

`scripts/comprobar_cuenta_demo.py`: clave read_only + trade (sin retirada), `feeType = 1`, comisiones Lv1 iguales a las
configuradas (0,10 / 0,20 %). El saldo NO es de 50 $: decidido el saldo virtual (pieza c0).


```bash
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/fijar_comision_usdc.py'   # SIN --aplicar
```
Tiene que decir `feeType = 1` (por si OKX reinicio el demo). Y leer el saldo del demo y las comisiones de la cuenta
(`GET /api/v5/account/trade-fee`, `takerUSDC`/`makerUSDC`): si son MAS CARAS que las de `settings.yaml`, no se opera
(decision del 23/09) y se avisa al propietario.

### 3. Las 9 pruebas del demo (manual, con importes minimos) — HECHAS el 02/10

Resultados en `preparacion-fase-4.md` 11: OCO cash, adjuntos, ids, `feeType` y `tradeQuoteCcy` funcionan; el objetivo NO puede ser limit (taker); NEAR paga el doble en el demo; y el hueco del parcial. Las tres cosas que cambian algo, decididas por el propietario el 02/10 (`diseno-fase-4.md`).


La lista de `preparacion-fase-4.md` seccion 8, con los 5 pares del demo (BTC, ETH, SOL, DOGE, NEAR). **Van ANTES de
escribir la proteccion**, porque deciden como se escribe:
- OCO adjunta a la entrada o aparte (pruebas 3 y 4, el llenado a medias);
- si el objetivo puede ser maker (`tpOrdKind = limit`, prueba 7): si no, **corregir el modelo de costes antes** (el
  objetivo seria taker, 0,10 puntos mas caro);
- la prueba 6 cambia: con `feeType = 1` (ya puesto), comprobar que se recibe la cantidad EXACTA de la orden;
- la prueba 9 (01/10) dice si la OCO acepta `tradeQuoteCcy` y que se paga en USDC en el libro unificado.

Cada prueba se apunta en `preparacion-fase-4.md` con lo que contesto OKX, tal cual. Es la unica parte en que se
envian ordenes a mano: todas con la guardia (`execution/guardia.py`) delante.

### 4. Las piezas que faltan (portatil, en la rama; tests primero)

| # | Pieza | Que hace |
|---|---|---|
| a | `execution/ordenes.py` | **HECHA el 02/10** (rama): enviar, cancelar y consultar por nuestros ids; la guardia otra vez justo antes de enviar; consultar antes de enviar entradas Y OCO; un error de red al enviar no se reintenta a ciegas. `tradeQuoteCcy: "USDC"` explicito y exigido por la guardia. Verificado en el demo: lo que no existe da `51603` |
| b | Proteccion | **HECHA el 02/10 sin modulo propio** (rama): la entrada lleva el stop y el objetivo ADJUNTOS (`peticiones.entrada`, la guardia lo exige); entrada a medias -> `CANCELAR_RESTO`, lo primero del plan, sin OCO propia (chocaria con la de OKX); objetivo a mercado; la conciliacion y el plan verifican/crean la OCO de cada posicion por la cantidad REAL. Falta ver una OCO que SALTA (prueba 10, abajo) |
| c0 | Saldo virtual (02/10) | **HECHA el 02/10** (rama): `equity.Foto` y `equity.virtual` (50 USDC + deltas); la lectura, la regla 7 y la conciliacion reciben el saldo ya virtualizado. Y `execution/comisiones.py`: los pares operables segun la comision real de cada uno (decision del 02/10) |
| c | `scripts/run_exec.py` | **HECHA el 02/10** (rama): `execution/ejecutor.py` (una vuelta cada 15 s, conciliacion cada 5 min), `espejo.py`, `riesgo.py` (las 19 reglas con el estado del demo), `lectura.py`, `store.py` (base propia) y el servicio, que no arranca con clave real, retirada o sin `feeType 1`. Las 4 decisiones del 02/10. Probado contra un OKX simulado (14 tests de la vida del demo, mutacion 6/6) y UNA vuelta de verdad contra el demo: foto, 50,00 $, la conciliacion cuadra |
| d | DEGRADED enchufado | **HECHA el 02/10** (rama): `core/salud.py` en el ejecutor y en la ingesta (ya no sale al momento; al desplegar, reiniciar la ingesta) |
| e | `scripts/check_exec.py` | **HECHA el 02/10** (rama): el juez, independiente del ejecutor, noveno de cada noche; cruzado con el ejecutor en los tests (sin fallas en una vida normal, ve una compra a mano) y pasado contra el demo de verdad |
| f | Pausa de Telegram | **HECHA el 02/10** (en el ejecutor): fuera de NORMAL, las entradas pendientes se cancelan en la vuelta siguiente (15 s) |

**Prueba 10 (pendiente, en el demo):** una OCO que SALTA. Como vienen `actualSide`/`actualPx` y el llenado de la
pata que salto (`ordenes.oco_ex` los lee sin haberlos visto). Con la semana del demo o con una OCO a proposito cerca
del precio.

Cada pieza: tests, `ruff`, y comprobar que alguien la llama de verdad (la leccion de "escrito y sin enchufar"). No se
toca `risk/`; si hiciera falta, mutacion 16/16 antes de darlo por bueno.

### 5. Juntar la rama en `main`

`fase-4-piezas-puras` en `main` (la rama ya se ha ido actualizando con `main`). Todos los tests en verde en el
portatil y en el VPS. **La huella del camino de la IA no cambia** (`check_fase6.py`): el ejecutor copia decisiones, no
las toma. **Comprobado el 02/10: `f063d80147a9` en la rama y en `main`.**

## PARTE 2: desplegar y medir

### 6. Instalar (VPS)

- El servicio `ploutos-exec` (`MemoryMax`, `OOMScoreAdjust`, `Restart=always`) y su base `var/ploutos-exec.db`.
- **Copias:** la sexta base en `deploy/backup.sh` (y reinstalar `/usr/local/bin/ploutos-backup`), en
  `verify_backups.py` y en `deploy/daily-backup.ps1` (familias).
- **Vigilante:** el propietario crea la 8a comprobacion en Healthchecks y pone la URL en el `.env` del VPS (`HEALTHCHECK_EJECUTOR`, ya
  en `.env.example`); el ejecutor late solo si OKX contesta y no esta degradado.
- **Panel:** el estado de la OCO de cada posicion (lo que falta para cerrar la fase 5).

### 6-7. HECHO el 03/10

Juntada la rama en `main` (`b4e7b65`, 1581 tests en verde en el portatil y en el VPS, huella `f063d80147a9`); copia
reinstalada (`/usr/local/bin/ploutos-backup`, con `ploutos-exec`); ingesta reiniciada a las 09:30 UTC (DEGRADED con
`core/salud.py`; velas de 1 m al dia a los 60 s); `HEALTHCHECK_EJECUTOR` en el `.env` del VPS (14 claves; quitada del
portatil); `ploutos-exec` habilitado y arrancado a las 09:33 UTC: operables BTC, ETH, SOL y DOGE, foto del saldo, equity
50,00 $ fiable y las dos primeras conciliaciones cuadran. Parado a las 09:40 para la prueba 10 (`preparacion-fase-4.md`
13) y vuelto a arrancar a las 10:16 con una foto nueva: **la semana cuenta desde las 10:16:28 UTC del 03/10**. El panel
ensenya el demo desde el mismo dia ('Demo de OKX', con el estado de la OCO de cada posicion).

### 7. Arrancar

En la ventana despues de una vela (como la parada). Arranca, concilia (el demo tiene que estar vacio o conocido),
y espera a la siguiente orden de la cartera de la IA. Solo los 5 pares del demo; XRP, AVAX y TRX siguen en papel.

### 8. Los tests de caos (demo)

**Guion detallado, cuando y quien hace cada uno, y los resultados: `docs/archivo/caos-fase-4.md` (03/10).** La tabla de
`diseno-fase-4.md` seccion 4, uno a uno, con lo que paso apuntado: matar el proceso tras enviar, con una
entrada llenada sin OCO, cortar la red, llenado parcial y caducidad, errores repetidos, reloj desfasado y cancelar a
mano una OCO desde la web del demo.

### 9. La semana

`check_exec.py` cada noche con los demas jueces. **Criterio (PRD 12): 1 semana sin descuadres**, con la definicion de
la decision 5 (una diferencia que la conciliacion no explica en la misma pasada, o una posicion sin OCO mas de 5 min),
**y al menos una operacion completa en el demo** (decision del propietario del 03/10: sin actividad, la semana no prueba nada).

## Calendario orientativo

| Paso | Cuanto |
|---|---|
| 1-3 (parada, cuenta, 9 pruebas) | 1 dia |
| 4-5 (piezas y rama) | 3-5 dias |
| 6-8 (instalar, arrancar, caos) | 1-2 dias |
| 9 (la semana) | 7 dias |

**Del 02/10 al cierre, unas dos semanas y media**: cerca del veredicto de la fase 6 (desde el 16/10), que se mide con
el papel y no depende del demo.
