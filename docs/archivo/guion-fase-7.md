# Guion de la fase 7: del demo al dinero real (50 $)

Preparado el 07/10/2026 a peticion del propietario. **Estado: GUION. Nada de esto empieza sin el OK expreso del propietario**, y antes
tienen que cumplirse las condiciones de la seccion 0. PRD 12: "Dinero real (50 $), agresividad 1-2. Criterio:
revision semanal".

**Lo mas importante, dicho primero:** la condicion que de verdad decide si hay fase 7 no es tecnica. Es la de la
estrategia (decision del propietario del 25/09): **sin una estrategia que no pierda en la reserva, no hay fase 7.** Hoy la
estrategia pierde en el anyo USDC (-0,38 R) y en la exploracion gana +0,12 R con un intervalo que incluye el cero. La
segunda ronda puede no encontrar ninguna que pase; entonces este guion se queda guardado, y eso tambien es un
resultado.

---

## 0. Condiciones para empezar (todas)

| # | Condicion | Donde se mira | Hoy (07/10) |
|---|---|---|---|
| 1 | Fase 4 CERRADA: 7 dias sin descuadres y al menos una operacion completa | `check_exec.py` codigo 0, `docs/archivo/cierre-fase-4.md` | midiendo (0 completas) |
| 2 | Veredicto de la fase 6: decide QUE cartera va a dinero real (IA o baseline) | `check_fase6.py`, `docs/archivo/protocolo-fase-6.md` | desde el 16/10 |
| 3 | El objetivo cobrado taker, aplicado (rama `objetivo-taker`) | `settings.yaml` con la fecha | preparado, sin desplegar |
| 4 | Segunda ronda de estrategia: una que **no pierda en la reserva** (mirada una sola vez) | `docs/archivo/plan-segunda-ronda-estrategia.md` | sin empezar |
| 5 | Si la estrategia cambia: su propio tramo de papel (y de demo) antes del dinero | los jueces de papel y del demo | - |
| 6 | Whitelist decidida (09/10) y aplicada en `settings.yaml` Y en la clave real | `docs/archivo/decision-whitelist-0910.md` | 09/10 |
| 7 | **OK del propietario**, por escrito en el chat, a la fase 7 y a las decisiones de la seccion 1 | este documento | - |

Sobre la 5: el protocolo dice que la fase 7 va "con la IA" o "con el baseline" segun el veredicto, pero el veredicto se
mide con la estrategia de HOY. Si la segunda ronda la cambia, lo honesto es medirla en papel y en el demo un tiempo
antes de ponerle dinero (cuanto, lo decide el propietario: propuesta en la seccion 1).

## 1. Las decisiones del propietario antes de empezar

| # | Decision | Opciones | Propuesta |
|---|---|---|---|
| A | Que cartera espeja la cuenta real | la de la IA o la del baseline | la que diga el veredicto (decision 4 del protocolo: no concluyente -> la IA) |
| B | Nivel del slider (PRD: 1-2) | 1: riesgo 0,50 %, solo pullback, 3 op./dia. 2: 0,75 %, pullback y reversion, 4 op./dia | **1**. Ojo: con el 1, el riesgo es ~0,25 $ y la posicion ~7,5 $: **BTC no llega a su minimo (~8,6 $) y no se operaria**. Con el 2, ~0,37 $ y ~11 $: si. Y la reversion pierde en todos los estudios: el 1 la deja fuera |
| C | Cuanto se ingresa | 50 USDC justos, o 50 + margen | **50 USDC + ~5 USDC de margen**. El saldo virtual cuenta 50 $ aunque haya mas (como en el demo); el margen evita que una comision de mas deje una orden sin saldo |
| D | El demo, despues | pararlo, o dejarlo como ensayo | **dejarlo**: cada cambio se prueba primero en el demo (es gratis) |
| E | Las carteras de papel | seguir con las dos | **seguir**: son el control (la fase 6 sigue midiendo si fue no concluyente) |
| F | Tramo de papel si cambia la estrategia | 1 semana, 2 semanas, el de la fase 3 | **2 semanas en papel + 1 en el demo con al menos una operacion completa** |
| G | Criterio para PARAR la fase 7 (ademas de las reglas duras) | ver seccion 7 | los de la seccion 7 |

## 2. La cuenta real (lo hace el propietario)

1. **Ingresar los USDC.** Comprar USDC con euros en OKX o transferirlos. **Lo hace el propietario, a mano**: el bot no mueve
   dinero, no compra USDC y no puede retirar (regla 19).
2. **La comision en USDC (`feeType = 1`)** en la cuenta real (decision 2 de la fase 4). Hoy
   `scripts/fijar_comision_usdc.py` solo acepta el demo; se adapta (seccion 3) y se lanza con el OK del propietario. Releerlo
   SIN `--aplicar` despues.
3. **Crear la clave REAL** en la web de OKX EEA:
   - permisos: **lectura y trading, NUNCA retirada** (regla 19);
   - lista blanca de IP: **solo la IPv4 del VPS** (`curl -s https://api64.ipify.org` en el VPS: tiene que dar la IPv4;
     el VPS salia por IPv6, `/etc/gai.conf`);
   - monedas permitidas: **las 8 de la whitelist Y USDC** (leccion del 02/10: `50123` = moneda no permitida en la clave;
     comprobar tambien la de cotizacion);
   - nombre: `ploutos-real`.
4. **Ponerla en el `.env` del VPS** (el propietario, como siempre: nunca en el chat). Nombres nuevos para que NO se confunda con
   la del demo: `OKX_REAL_API_KEY`, `OKX_REAL_API_SECRET`, `OKX_REAL_PASSWORD` (en `.env.example` sin valores). La del
   demo se queda donde esta.
5. **Healthchecks:** una comprobacion nueva para el ejecutor real (5 min + 15 min, como la del demo):
   `HEALTHCHECK_EJECUTOR_REAL`. La crea el propietario.

## 3. Lo que hay que construir (portatil, rama `fase-7`, tests primero)

Hoy el ejecutor se NIEGA a arrancar con una clave que no sea del demo (`run_exec.py`: "nada de dinero real hasta la fase
7"). Esa proteccion se queda; lo que se anyade es un segundo modo, explicito, que no se pueda activar por error.

| # | Pieza | Que |
|---|---|---|
| a | Entorno explicito | `run_exec.py --entorno demo|real`. En `real`: exige `exchange.demo: false` en `settings.yaml` Y las claves `OKX_REAL_*`; sin `set_sandbox_mode`; se niega si la clave real tiene retirada o si falta `feeType 1` (como ahora). Con `--entorno demo`, exactamente lo de hoy. Dos servicios: `ploutos-exec` (demo) y `ploutos-exec-real`, cada uno con su base (`var/ploutos-exec-real.db`) |
| b | Los pares | en real estan las 8 contra USDC (grupo de comision 12): NEAR, XRP, AVAX y TRX pasan a operarse si sus comisiones reales no son mas caras que las configuradas (la comprobacion par por par ya existe). `check_exec.py` deja de tener los pares del demo fijos (`PARES_DEMO`) |
| c | El slider del ejecutor | hoy fijo en 3 (`execution/riesgo.py`, `SLIDER`); pasa a `settings.yaml` (`ejecucion.slider_real`), validado en 1-2 para el entorno real. La cantidad sigue siendo `min(papel, motor)`: con el slider 1 el motor la recorta y veta los setups que el nivel 1 no permite |
| d | Que cartera espeja | `--paper-db` ya existe: la de la IA o la del baseline (decision A). El juez, igual |
| e | Avisos y panel | los mensajes y el panel dicen "Cuenta real" y no "Demo de OKX" (`notify.messages.cierre_demo`, `api/foto.py`); un aviso al arrancar el real que diga el slider y la cartera espejada |
| f | El CSV fiscal | el del panel sale hoy del papel: anyadir las operaciones del ejecutor REAL, en euros (`api/cambio.py`), que son las que tributan (PRD 14) |
| g | `fijar_comision_usdc.py` y `comprobar_cuenta_demo.py` | con `--entorno real` (solo lectura por defecto; `--aplicar` solo para el `feeType`) |
| h | Copias y jueces | la base `ploutos-exec-real` en `backup.sh`, `verify_backups.py`, `daily-backup.ps1`; `check_exec.py --entorno real` como decimo juez de cada noche |

Cada pieza con tests contra el OKX simulado (`tests/okx_simulado.py`) y comprobando que alguien la llama de verdad. Al
juntar en `main`, la huella del camino tiene que seguir igual (el ejecutor copia, no decide).

## 4. Las pruebas en la cuenta real, antes de copiar nada (con el propietario delante)

Sin llenados y con importes minimos, como las del demo del 02/10 (`docs/preparacion-fase-4.md` 11):
1. `comprobar_cuenta --entorno real`: permisos (sin retirada), `feeType 1`, comisiones par por par, saldo.
2. Una compra **post-only al 50 % del precio** en cada una de las 8 (no se puede llenar) y cancelarla: comprueba la
   clave, las monedas permitidas (`50123`), `tradeQuoteCcy` y los ids.
3. Una OCO de venta sobre una cantidad que NO se tiene: tiene que rechazarla por saldo, no por formato.
4. `check_exec.py --entorno real` sin operaciones: sin descuadres.

Lo que no se puede probar sin dinero en juego (una OCO que salta, un llenado parcial) se ve con la primera operacion,
igual que en el demo. **No se hace ninguna operacion "de prueba" con dinero**: la primera es la primera copia de verdad.

## 5. Desplegar

En una ventana despues de una vela de 4 h (como la parada de la fase 4; evitar las 00:30, 03:15, 07:15 y el domingo
07:30). Copia a mano de las bases antes; jueces en seco sin FALLA; huella apuntada.
1. Instalar `ploutos-exec-real` (`MemoryMax`, `Restart=always`), sin arrancarlo.
2. Arrancarlo: foto del saldo (50 $ virtuales), operables, la primera pasada cuadra. Aviso de Telegram de arranque.
3. Esperar a la siguiente orden de la cartera espejada. Nada de adoptar posiciones abiertas (en el demo se hizo para
   tener actividad; con dinero, solo decisiones nuevas).

## 6. Durante la fase 7: la revision semanal (el criterio del PRD)

Cada domingo, un informe de una pagina (lo preparo yo, lo lee el propietario):
- `check_exec.py --entorno real` de la semana: descuadres (tiene que ser 0), operaciones, OCO;
- equity real contra la cartera de papel espejada: **la diferencia es el coste de la realidad** (deslizamiento de las
  salidas a mercado, entradas post-only rechazadas, llenados parciales);
- comisiones pagadas contra las del modelo, y cuanto movio el precio cada salida a mercado;
- reglas que actuaron (veto, cooldown, escalones de drawdown) y modos;
- la decision de la semana: seguir, bajar el slider, pausar o parar.

## 7. Cuando se para (propuesta, decide el propietario)

Ademas de las reglas duras, que ya actuan solas (regla 7: suelo de 25 $ enclavado; regla 10: 3 $ al dia; regla 9:
escalones):
- **cualquier descuadre** que la conciliacion no explique -> `HALTED` y se mira antes de seguir;
- equity real por debajo de **40 $** (el segundo escalon) -> pausa y revision con el propietario antes de seguir;
- la diferencia real contra papel peor que **-0,2 R por operacion** de media en 10 operaciones -> la realidad cuesta
  mas de lo modelado: parar y revisar el modelo de costes;
- un fallo de la clave o de OKX que dure mas de un dia.

Para parar: `/kill` por Telegram o "parar" en el panel (`HALTED`: cancela las entradas, las OCO siguen protegiendo);
"cerrar todo" en el panel (doble confirmacion) vende. **Retirar el dinero lo hace el propietario a mano**: la clave no puede.

## 8. Riesgos que el demo no ha podido ensenyar

1. **Deslizamiento real** en las salidas a mercado (stop y objetivo son taker): el demo llena siempre igual.
2. **Entradas post-only rechazadas** cuando el precio ya ha cruzado: no se pierde dinero, se pierde la operacion.
3. **Llenados parciales**: en el demo el libro se repone al momento; en real pueden pasar. El ejecutor ya cancela el
   resto (decision del 02/10) y OKX crea la OCO por lo llenado.
4. **Huecos de precio** que saltan el stop (riesgo de hueco: la reversion y los stops estrechos lo sufren mas).
5. **OKX caido** con posiciones abiertas: las OCO estan en el exchange y siguen; el ejecutor entra en DEGRADED.
6. **Hacienda:** cada venta tributa (IRPF, PRD 14). El CSV de la pieza f es el que vale.

## 9. Calendario orientativo

| Paso | Cuanto | Cuando, como pronto |
|---|---|---|
| Condiciones 1-3 | - | fase 4: desde el 10/10; veredicto: 16/10 - 20/11 |
| Segunda ronda de estrategia (condicion 4) | 1-2 semanas | tras el veredicto |
| Papel + demo con la estrategia nueva (condicion 5) | ~3 semanas | despues |
| Piezas de la seccion 3 | 3-5 dias | en paralelo al tramo de papel |
| Cuenta, clave y pruebas (secciones 2 y 4) | 1 dia | al final |
| Desplegar | 1 dia | con el OK del propietario |

**Como pronto, mediados o finales de noviembre**, y solo si la estrategia pasa.
