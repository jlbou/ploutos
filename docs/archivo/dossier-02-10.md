# Dossier del 02/10/2026: lo que hay que decidir, en una pagina

Preparado el 29/09/2026 y **puesto al dia el 01/10 (08:32 UTC, 5,8 de 7 dias de la fase 3)** a peticion del propietario.
**No decide nada:** junta lo que esta repartido en varios documentos, con los numeros de hoy, para que el 02/10 se
decida con todo delante. Las cifras de la seccion 1 se rehacen ese dia con los comandos de `docs/archivo/cierre-fase-3.md`
(seccion 0); las decisiones son del propietario.

## 1. Donde estamos (01/10, 08:32 UTC)

| Que | Hoy | Se cumple el |
|---|---|---|
| Una semana estable (`check_fase3.py`) | 5,8 de 7 dias; las dos carteras al dia; ninguna vela perdida por una parada | 02/10 ~12:05 |
| Salidas invalidas sin controlar | 0 (3 velas con candidatos, 3 respuestas validas) | 02/10 |
| Consumo de la IA | 3 llamadas (0,5 al dia, pico 2), 0,09 $ equivalentes cada una, latencia mediana 21 s | 02/10 + cuota semanal (el propietario, Settings > Usage) |
| Juez de papel, las dos carteras | CUMPLIDO en las dos (140 h; 5 y 4 ordenes) | 02/10 |
| Noticias y comandos (`check_news`, `check_control`) | sin FALLA (01/10; aun sin los 7 dias) | 02/10 ~18:30 |
| Fase 6 (`check_fase6.py`) | datos bien; 1 discrepancia de 30; tramo `f063d80147a9` sin partir | minimo 16/10, tope 20/11 |

Carteras (vela de las 04:00): **baseline 49,31 $**, llena (AVAX, SOL y NEAR); **IA 49,02 $**, 2 posiciones (AVAX y
SOL). Dos operaciones cerradas en cada una, las dos en su stop (-1,05 $ y -0,95 $).

## 2. Las decisiones del 02/10, con lo que hay que saber de cada una

### 2.1 Cerrar la fase 3

Los cuatro criterios (PRD 12), mas noticias y comandos. Si `check_fase3.py` sale con 0 y el propietario confirma la cuota
semanal, esta cerrada. **Nada de esto es una decision dificil: es un juez.** El bloqueo de la regla 17 (2.5) no
cuenta como inestabilidad: no se perdio ninguna vela (se procesaron todas, sin entradas). Recomendacion dada el
01/10: no alargar la fase por el (lo que mide es que el sistema no se caiga, y no se cayo).

### 2.2 Candidatos en sombra (decision 5 del protocolo de la fase 6)

`docs/archivo/propuesta-candidatos-sombra.md`. El numero de la regla ("con 1 o menos al dia, plantearselo"):

| | Al dia | Cartera llena |
|---|---|---|
| Baseline | **0,9** candidatos (5 en 5,8 dias) | 29 de 35 velas |
| IA | **0,7** (4 en 5,8 dias) | 17 de 35 velas |
| Historia (anyo USDC / exploracion) | 0,51 / 0,48; con sombra, DISTINTOS 0,81 / 1,02 | 25 % / 39 % |

Las dos por debajo de 1. **Ojo:** la IA tuvo hueco la mitad del tiempo y aun asi vio 4 candidatos: el mercado da
pocos, no solo la cartera llena. La sombra ayuda con lo segundo, no con lo primero. Sin sombra, la fase 6 (3-8
semanas) daria unos 10-28 candidatos: casi seguro "no concluyente". Opciones: **A** no hacer nada, **B** sombra en
vivo en el servicio de la IA (recomendada, ~1 dia de trabajo, no parte la muestra), **C** sombra diferida. Si B:
el juez de la sombra se escribe ANTES de ver datos. Dato para la decision: las dos carteras no ven siempre los
mismos candidatos (2.3).

**Lo que puede ver la fase 6 (estudio del 01/10, `docs/estudios/potencia-fase-6/README.md`):** sin sombra, a las 8
semanas habra ~10 discrepancias; el juez pide 30 para APORTA, asi que **solo puede decir PERJUDICA o NO
CONCLUYENTE**. La sombra, juzgada aparte, tampoco llega a 30. Juntas (cambiaria el protocolo) llegarian a 28-43, y
APORTA solo saldria si la IA fuera MUY buena (+1 R por decision distinta). La sombra no hace concluyente la fase 6:
su valor es el doble de datos para lo que se siga midiendo y ver antes una IA mala. Con una IA neutra, el juez dice
PERJUDICA en falso el ~7 % de las veces.

### 2.3 Las dos carteras y el techo de ATR (hallazgo del 29/09)

`docs/estudios/divergencia-atr/README.md`. NEAR, 29/09 08:00: ATR 5,333 %. El baseline (49,85 $) lo dejo pasar
(techo ~5,34 %) y la IA (49,68 $) no (techo 5,323 %). El techo sale del riesgo por operacion, que es un % del equity.
**No es un fallo: es la regla 12 actuando sobre dos carteras distintas.** En un anyo de historia esa diferencia no
habria costado ni un candidato (0 de 198); lo que si pesa es la regla 9 (una cartera por debajo de 45 $ pierde el
8,6 %). La M1 no se sesga (mide los candidatos de la IA). Recomendado: A, dejarlo escrito sin tocar nada; B, que el
juez lo cuente; C (igualar el techo) parte la muestra y no se recomienda.

### 2.4 El OK a la fase 4

`docs/archivo/guion-fase-4.md`. Unas dos semanas y media hasta "1 semana sin descuadres", en dos partes: construir (parada
de mantenimiento, comprobar la cuenta demo, **9 pruebas** a mano, seis piezas, la rama en `main`) y desplegar y
medir. Depende de 2.2: si es la B, va ANTES (toca el servicio de la IA, que el demo va a copiar).

- Antes de empezar: `fijar_comision_usdc.py` SIN `--aplicar` (el demo tiene que decir `feeType = 1`).
- Parada de mantenimiento (`docs/archivo/parada-mantenimiento-fase-4.md`): ccxt 4.5.84 (probado, no entra en la huella) y
  los 6 paquetes de Ubuntu que no son de seguridad. Reinicia servicios: se elige la hora.
- **Nuevo desde el 30/09 (decide el propietario): pagar en USDC de forma EXPLICITA.** OKX junto sus libros en dolares
  (`hallazgos-fase-3-4.md` 5d): el libro `X-USDC` acepta USD, USDC, USDG y RLUSD, y con que se paga lo dice
  `tradeQuoteCcy`, que hoy por defecto es USDC. Propuesta: mandarlo siempre (`tradeQuoteCcy: "USDC"`) y que la
  guardia rechace cualquier otro valor, como ya hace con `tdMode: cash`; si OKX cambiara el valor por defecto, el
  bot pagaria con otra moneda sin decirlo. Y una **prueba 9** en el demo para comprobarlo (tambien en la OCO, de la
  que la documentacion no dice nada). Si el propietario dice que si, entra en la pieza a (`ordenes.py`) y en la guardia.

### 2.5 Incidente del 30/09-01/10: la regla 17 bloqueo 20 h (ya arreglado)

OKX retiro el par BTC/USD el 30/09 (al juntar sus libros en dolares, 2.4). La paridad de USDC se calculaba con dos
fuentes y una necesitaba ese par: quedo DESCONOCIDA y, como manda la regla 17, las dos carteras no entraron en nada
durante 5 velas (30/09 08:00 - 01/10 00:00). Nadie lo supo: ningun juez lo veia como fallo y no habia aviso. Las dos
carteras quedaron igual de bloqueadas: la comparacion de la fase 6 sigue siendo justa, pero la muestra no crecio en
esas 20 h (el baseline estaba lleno; la IA tenia un hueco: con ~0,5 candidatos al dia, lo probable es que se perdieran 0 o 1). Lo hecho el 01/10:

- **Solo la fuente A** (el propietario), con el mismo umbral; desplegado ~07:30 UTC, sin partir la muestra. A las 08:00 la
  paridad volvio (-0,011 %) y salio el aviso de "recuperada".
- **Aviso de Telegram** cuando la regla 17 empieza o deja de bloquear.
- **Juez de bloqueos silenciosos** (`check_bloqueos.py`, septimo juez de cada noche): FALLA si una cartera lleva 3+
  velas sin poder entrar por un motivo de sistema. Con el, este incidente se habria avisado a las 00:30 del 01/10.
  La pasada de esta noche ya no lo cuenta (acabo hace mas de 24 h).

### 2.6 Lo demas del 30/09-01/10 (hecho, para saberlo)

- **Copia al portatil:** la del 30/09 se corto a medias (Windows la mato) sin avisar. Desde el 01/10 se hace la
  primera vez que el portatil esta en uso desde las 12:00, avisa si la anterior se corto y late a una septima
  comprobacion de Healthchecks (dos dias sin copia buena = aviso, aunque el portatil este apagado). Probada: 10
  copias bajadas y restaurables, latido recibido.
- **Panel:** al tocar una posicion abierta sale su grafico de velas de 4 h con entrada, stop y objetivo.

## 3. Lo que viene despues

| Cuando | Que |
|---|---|
| 09/10 | Whitelist: DOGE, NEAR, AVAX y (ADA, LINK) con 14 dias de spread. Guion en `docs/archivo/decision-whitelist-0910.md`. Parar `ploutos-spread-extra` |
| desde 16/10 | Veredicto de la fase 6; despues la segunda ronda de la estrategia (idea 2, la reserva, mesurar A'), el programa de la IA y los medios de comunicacion en sombra |
| antes de la fase 7 | Una estrategia que no pierda en la reserva. Sin ella no hay dinero real |

## 4. Una precision del 29/09 sobre las entradas

El simulador (y el juez) dejan llenar una entrada en cualquiera de las **3 velas siguientes** a la que la crea
(12 h), y caduca si la tercera tampoco baja al limite. `ENTRY_BARS_TO_LIVE = 2` cuenta las velas SIN llenarse
antes de caducar, y varios textos lo decian como "caduca a las 2 velas". El codigo no cambia; se precisaron el
README, el protocolo de la fase 6 y el comentario de `portfolio/comparacion.py`. El juez y el simulador cuentan lo
mismo (test `test_caduca_a_la_tercera_vela_sin_llenarse`), asi que la M1 no se ve afectada.
