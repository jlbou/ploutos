# Segunda ronda: ideas C (time-stop) y D (sin reversion), medidas el 07/10/2026

> **Nota (15/10/2026, revision del codigo):** estos resultados se midieron con el simulador de papel ANTES de la
> suposicion 7 (`portfolio/paper.py`, rama `revision-1510-b`): en la vela que llenaba la entrada, el papel cobraba
> el objetivo aunque el maximo pudo pasar antes. Los R de los setups estan **algo inflados** (no se sabe cuanto sin
> volver a medir, y no se vuelve a medir: la estrategia de setups esta descartada y seria un intento mas). No afecta
> a la tendencia ni a L (`docs/estudios/tendencia/`), que entran a la apertura.


Criterio fijado y subido ANTES de medir (`docs/archivo/plan-segunda-ronda-estrategia.md`, "C y D: APROBADAS por el propietario el 07/10",
commit `2f62eef`). Exploracion USDT 02/12/2020-30/06/2024 (`var/estudios/exploracion.db`), el recorrido del bot sin
cambios (`revision-estrategia/medir.py`) parcheado en memoria (`medir_cd.py`); el veredicto lo saca `juzgar.py`. **La
reserva y el anyo USDC, sin tocar.**

**Validacion antes de mirar ninguna idea:** sin parches, las dos referencias salen EXACTAS: 497 op., +0,130 R (IC
-0,037 a +0,301) con el objetivo maker y +0,122 R (-0,044 a +0,292) con el objetivo taker.

## Resultado: NINGUNA PASA

| | Objetivo | Op. | R medio | IC 90 % | Diferencia con la referencia (IC 90 %, emparejada) | Anyos | Final | Pasa |
|---|---|---|---|---|---|---|---|---|
| Referencia | maker | 497 | +0,130 | -0,037 a +0,301 | - | 3/4 > 0 | 123,78 $ | - |
| Referencia | taker | 497 | +0,122 | -0,044 a +0,292 | - | 3/4 > 0 | 119,19 $ | - |
| **C**, 18 velas siempre | maker | 879 | +0,003 | | -0,127 (-0,267 a +0,006) | 1/4 mejor | 64,32 $ | no |
| **C**, 18 velas siempre | taker | 878 | -0,008 | | -0,130 (-0,264 a +0,001) | 1/4 mejor | 59,46 $ | no |
| **C**, 18 velas sin avance | maker | 875 | -0,009 | | -0,139 (-0,275 a -0,009) | 1/4 mejor | 58,05 $ | no |
| **C**, 18 velas sin avance | taker | 875 | -0,015 | | -0,136 (-0,271 a -0,007) | 1/4 mejor | 55,91 $ | no |
| **D**, sin reversion | maker | 399 | **+0,288** | **+0,099** a +0,482 | +0,158 (+0,083 a +0,235), informativo | 3/4 > 0 | 142,40 $ | no |
| **D**, sin reversion | taker | 398 | **+0,284** | **+0,095** a +0,478 | +0,162 (+0,087 a +0,239), informativo | 3/4 > 0 | 140,91 $ | no |

(El final de la referencia taker, de `operaciones-cortas/r4.json`: 50 $ + 69,19 $ netos.)

## Lo que dice

1. **El time-stop (C) empeora la estrategia, y mucho.** Corta unas 320 posiciones que, al cortarlas, iban GANANDO
   (+0,56 R de media) y que muchas veces habrian llegado al objetivo (en el anyo USDC, un objetivo valia +3,4 R). El
   hueco se llena con otra operacion (879 en vez de 497), pero el pullback pasa de +0,39 a +0,06 R. Solo mejora en 2022, el anyo bajista (+0,11). Lo
   mismo que el 25/09 en el anyo USDC, ahora con 3,5 anyos: **se descarta** (y, por el criterio, sin probar otras
   duraciones).
2. **Quitar la reversion (D) mejora claro, pero no llega al liston que se fijo.** R medio +0,29 (de +0,13), final 142 $
   (de 124 $), caida maxima 22,5 % (de 25,2 %), y la diferencia emparejada con la referencia queda ENTERA por encima
   de cero (+0,08 a +0,24). Falla la condicion 1: el extremo bajo del IC (+0,10) no llega a +0,13. Sigue perdiendo en
   2022 (-0,31 R): quitar la reversion no arregla el anyo bajista.
3. **D es casi la idea 2 por otro camino** (+0,28 R, IC +0,06 a +0,51, primera ronda): las dos se quedan con el
   pullback, que es lo que gana (+0,35 R aqui). La 2 lo consigue quedandose fuera cuando BTC cae; la D, quitando el
   setup que pierde. Atacan cosas distintas (el anyo bajista y la reversion), asi que **la combinacion 2 + D** es la
   siguiente pregunta natural. El plan ya la preve ("tambien combinada con la idea 2"); **no se ha medido**: se fija
   su criterio con el propietario antes.
4. **Aviso de metodo, otra vez:** D se anyadio despues de saber que la reversion pierde. Que mejore era esperable;
   por eso el liston era el R entero sobre +0,13, no la diferencia. Mirar ahora la diferencia emparejada para darla
   por buena seria cambiar el criterio despues de ver el resultado.

## 2 + D (08/10): NO PASA, por dos milesimas

Criterio aprobado por el propietario el 08/10 antes de medir (`be7e775`; `juzgar_2d.py`). Validacion: la idea 2 sola reproduce
la primera ronda EXACTA (293 op., +0,278 R, operacion a operacion).

| | Objetivo | Op. | R medio | IC 90 % | Final | Caida max. | (1) IC > +0,13 | (2) >= 100 | (3) anyos | Pasa |
|---|---|---|---|---|---|---|---|---|---|---|
| Referencia | maker | 497 | +0,130 | -0,037 a +0,301 | 123,78 $ | 25,2 % | | | | - |
| Idea 2 sola | taker | 292 | +0,263 | +0,036 a +0,493 | | | | | | (informativo) |
| **2 + D** | maker | 256 | **+0,371** | **+0,134** a +0,625 | 117,62 $ | 18,0 % | si | si | si | si |
| **2 + D** | taker | 256 | **+0,363** | **+0,128** a +0,616 | 115,90 $ | 18,1 % | **no** | si | si | **no** |

Por anyo (taker): 2021 100 op. +0,74; 2023 78 op. +0,19; 2024 65 op. +0,06; 2022 sin operaciones (BTC bajo su media).

Lo que dice:
1. **No pasa: el criterio pedia pasar en las dos contabilidades** y con el objetivo cobrado como lo cobra OKX el
   extremo bajo queda en +0,128, a dos milesimas de +0,13. Es una diferencia del tamanyo del propio ruido del
   bootstrap, pero la regla se fijo antes y no se reinterpreta despues.
2. **Salio lo que se calculo a ojo antes de medir** (unas 250 op. a ~+0,38 R): 256 a +0,37. Confirma el aviso: la
   exploracion ya no podia sorprender con esta pregunta.
3. **Mas por operacion, menos en total:** +0,36 R por operacion (casi el triple que la referencia) y menos caida (18 %
   frente a 25 %), pero acaba con MENOS dinero (116-118 $ frente a 124 $) porque opera la mitad. Casi todo sale de
   2021 (+0,74); 2023 y 2024 son positivos pero flojos.
4. **La reserva, sin tocar.**

## A', cortos de mercado bajista (08/10): NO PASA

Disenyo y criterio aprobados por el propietario el 28/09 (`docs/archivo/diseno-cortos-bajistas.md`); como se mide, seccion 7, subida
antes de medir (`f3006ce`) con sus dos validaciones EXACTAS (la idea 2 sola: 293 op.; el espejo: 220 cortos).
`cortos_a.py`, `validar_a.py`, `resultados/a-*.json` y `veredicto-a.txt`. La reserva, sin tocar.

| | Op. | Aciertos | R medio | IC 90 % |
|---|---|---|---|---|
| **Cortos A'** (con financiacion pesimista) | 166 | 38 % | **+0,056** | -0,176 a +0,283 |
| Largos en la combinacion | 284 | 30 % | +0,268 | +0,046 a +0,509 |
| Idea 2 sola | 293 | 30 % | +0,278 | +0,057 a +0,514 |
| Combinacion entera | 450 | 33 % | +0,190 | +0,024 a +0,360 |

Por anyo, los cortos: 2021 20 op. a -0,46; **2022 127 op. a +0,20**; 2023 19 op. a -0,36. Emparejada (la
combinacion menos la idea 2 sola): +3,8 R (IC -38,4 a +46,4).

| Criterio (28/09) | |
|---|---|
| >= 100 operaciones | si (166) |
| IC 90 % entero > 0 | **no** (-0,18) |
| R medio >= +0,13 | **no** (+0,06) |
| 2022 positivo | si (+0,20) |
| La combinacion mejor que la idea 2 sola | **no** (-38 a +46 R) |

Lo que dice:
1. **A' hace lo que prometia en 2022** (127 cortos a +0,20 R, con la financiacion pesimista pagada), mejor que el
   espejo, pero **lo pierde en los giros**: los pocos cortos de 2021 y 2023 (39) salen a -0,4 R. Es el mismo patron del
   espejo, mas suave.
2. **No mejora la estrategia:** la combinacion gana +3,8 R en 3,5 anyos sobre la idea 2 sola, dentro del ruido; los
   cortos ocupan huecos que los largos habrian usado (284 largos en vez de 293).
3. **Por el criterio, no se retoca** (ni la salida por regimen, que se dejo fuera por estar contaminada).

## Idea I, el stop a +1 R tras un cierre a +2 R (09/10): NO PASA, empeora

Criterio aprobado por el propietario el 09/10 antes de medir (`1893c3e`; `juzgar_i.py`, `resultados/*+I-*.json`,
`veredicto-i.txt`). Sobre 2 + D, contra las mediciones del 08/10 sin la regla:

| | Op. | R medio | Final | Diferencia emparejada (IC 90 %) | Anyos mejores | Pasa |
|---|---|---|---|---|---|---|
| 2 + D, maker | 256 -> **319** | +0,371 -> **+0,211** | 117,62 $ -> **86,97 $** | -0,160 (-0,308 a -0,014) | 1 de 3 | no |
| 2 + D, taker | 256 -> **319** | +0,363 -> **+0,205** | 115,90 $ -> **85,66 $** | -0,158 (-0,306 a -0,013) | 1 de 3 | no |
| Referencia, taker (informativo) | 497 -> 570 | +0,122 -> +0,048 | 120,44 $ -> 73,76 $ | -0,074 (-0,173 a +0,024) | 2 de 4 | - |

Lo que dice:
1. **Empeora, y con el IC entero por debajo de cero.** Se movio el stop en 87 operaciones: 51 llegaron igualmente al
   objetivo y 36 salieron en el stop movido (+1 R). Las que salen pronto se pierden el resto del camino, y el hueco
   que dejan lo ocupan 63 operaciones NUEVAS que de media pierden: el mismo mecanismo que el time-stop (idea C).
2. **La leccion de las dos:** en esta estrategia las ganancias vienen de pocas operaciones que llegan lejos; todo lo
   que corta antes (por tiempo o por precio) las recorta y llena el hueco con operaciones peores.
3. Por el criterio, no se prueban otros umbrales (+1,5 R, +3 R...): seria buscar hasta que algo salga.

## Ficheros

`medir_cd.py` (el recorrido con los parches), `juzgar.py` (el criterio de C y D), `juzgar_2d.py` (el de 2 + D),
`resultados/` (cada medicion con todas sus operaciones; `veredicto.txt` y `veredicto-2d.txt`, las salidas tal cual). Cada medicion tarda ~10 min; las seis, en paralelo,
14 min.
