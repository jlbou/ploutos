# Idea A': cortos pensados para el mercado bajista (disenyo para aprobar ANTES de medir)

Escrito el 28/09/2026 a peticion del propietario. **Estado: APROBADO por el propietario el 28/09, ANTES de medir** (seccion 6); **MEDIDO el
08/10 en la exploracion: NO PASA** (166 cortos a +0,06 R, IC -0,18 a +0,28; 2022 +0,20; la combinacion no mejora a la
idea 2 sola; `docs/estudios/segunda-ronda/README.md`). La reserva, sin tocar. Se mide en la segunda ronda (desde el 16/10,
tras el veredicto de la fase 6), una sola vez, con lo que el propietario apruebe aqui. Plan: `plan-segunda-ronda-estrategia.md`
seccion 2 (A'). **Aunque pasara, abrir la regla 1 es otra decision** (6.5 del plan).

## 1. De donde viene, y el aviso

el propietario (28/09): con largos y cortos hay oportunidades en cualquier mercado. El espejo de los tres setups actuales no
paso (`docs/estudios/revision-estrategia/README.md` seccion 5): 220 cortos a -0,01 R con financiacion (IC -0,25 a
+0,24); ganan en 2022 (~+12 R) y lo pierden en el giro de principios de 2023 (19 cortos, ~-15 R).

**El aviso, antes que nada:** este disenyo se escribe DESPUES de ver esos numeros en la misma exploracion. Todo lo que
se parezca a "arreglar lo que fallo en 2023" esta contaminado: encajaria con estos datos aunque no tuviera ventaja
real. Por eso:
- **una sola variante**, cerrada aqui; si no pasa, no se prueban retoques;
- **liston mas alto** que el de la primera ronda (seccion 5);
- **decide la reserva** (USDT 07/2024-08/2025, sin mirar), una sola vez, y despues el anyo USDC;
- cada pieza dice si sale de la practica general o de lo que se vio (seccion 2).

## 2. La idea: que la separa del espejo

El espejo copiaba los setups de largo al reves y solo miraba a BTC. A' pide tres cosas mas, sacadas de la practica
general de operar en tendencia (no de nuestros datos), y una cuarta que el propietario decide:

1. **Tendencia bajista en DOS niveles** (practica general). BTC bajo su media de 200 dias (como el espejo) Y la propia
   moneda en tendencia bajista diaria: cierre diario bajo su media de 50 dias y la de 50 bajo la de 200. El espejo
   vendia monedas que no estaban cayendo solo porque BTC si.
2. **Un solo setup: el rebote fallido** (practica general: "vender los rebotes" en tendencia bajista). En la tendencia
   del punto 1, el precio rebota hasta la EMA20 de 4 h (a 0,5 ATR o menos) y **la vela siguiente cierra otra vez por
   debajo de la EMA20 y por debajo de la apertura** (la confirmacion de que el rebote fallo). Nada de rupturas ni de
   reversiones: la reversion perdio en largo y en corto, y la ruptura bajista es la que mas sufre los rebotes bruscos.
3. **Stop y objetivo fijos por construccion** (practica general):
   - entrada: orden limit al cierre de la vela de confirmacion, valida 2 velas (como el bot);
   - stop: por encima del maximo del rebote (las 3 ultimas velas) + 0,5 ATR, y como minimo 1,5 ATR desde la entrada;
   - objetivo: **2 R**, sin proyecciones (menos piezas que ajustar);
   - la regla 16 igual: objetivo >= 3 veces el coste de ida y vuelta.
4. **(Para decidir) Salida por cambio de regimen:** si BTC cierra un dia por encima de su media de 200, se cierran los
   cortos al cierre de la siguiente vela de 4 h. **ESTA pieza sale de lo que se vio** (el giro de 2023): esta
   contaminada. Recomendado: **NO incluirla**, para que la prueba sea limpia. Si el propietario la quiere, el liston sube (5).

Lo que NO cambia: 0,50 $ de riesgo por operacion, max. 3 posiciones (largos y cortos juntos), los escalones, la
perdida diaria, el suelo, las comisiones de `settings.yaml` (entrada maker, stop taker) y la financiacion pesimista
(el corto PAGA 0,01 % cada 8 h, siempre, cobros a las 00, 08 y 16 UTC).

## 3. Como se mediria (en la segunda ronda)

- **Un simulador de cortos SOLO para el estudio** (`docs/estudios/`), con las seis suposiciones de `portfolio/paper.py`
  al reves (el stop gana los empates y sufre los huecos; el objetivo no). El bot no se toca. Recomendado frente a
  invertir precios: con medias diarias de la moneda (punto 1), la inversion ya no es exacta.
- **Validacion antes de medir:** configurado como el espejo, tiene que reproducir `cortos-operaciones.json` (220
  operaciones) con diferencias solo de redondeo. Si no, no se mide nada.
- Los largos, los de la idea 2 (BTC sobre su media de 200), sin cambios: la comparacion es "idea 2 sola" contra
  "idea 2 + A'", compartiendo los 3 huecos de la regla 4 (el espejo los media por separado).
- Trabajo: ~1 dia el simulador y su validacion; medir y documentar, medio dia.

## 4. Lo que se mira (y en que orden)

1. Exploracion (USDT 12/2020-06/2024), UNA vez, con el criterio de la seccion 5.
2. Si pasa: la reserva, UNA vez. Si no pasa, fin: no se retoca.
3. Si pasa la reserva: el anyo USDC como segunda comprobacion.

## 5. El criterio (a aprobar ahora)

Los cortos SOLOS, con la financiacion pesimista:
- **al menos 100 operaciones** en la exploracion;
- **IC 90 % (bootstrap por dias) entero por encima de 0, y R medio >= +0,13** (la referencia de la primera ronda);
- **2022 positivo** (el anyo bajista: es el motivo de todo esto);
- y la combinacion con la idea 2, **mejor que la idea 2 sola** en la comparacion emparejada (IC de la diferencia
  entero por encima de 0).

Opcion mas dura (la que se apunto en el plan): IC entero por encima de +0,13 en los cortos solos. Con ~200 operaciones
el intervalo mide +-0,25 R (el del espejo: 220 op., de -0,25 a +0,24), asi que haria falta un R medio de ~+0,38 o mas:
casi imposible para cualquier estrategia; por eso se recomienda la de arriba, que ya es mas dura que la de la primera
ronda (alli bastaba la combinacion). Ojo: el filtro doble (2.1) deja menos operaciones que el espejo; si no llega a
100, no pasa.

**Si se incluye la salida por regimen (punto 2.4):** ademas, los cortos tienen que pasar SIN ella en la exploracion
(la salida solo puede mejorar algo que ya funciona, no rescatarlo).

Reserva: cortos R medio > 0 con financiacion, y la combinacion mejor que la idea 2 sola.

## 6. Decisiones del propietario (28/09, las cuatro recomendadas, ANTES de medir)

1. **El setup** (seccion 2, puntos 1-3): **tal como esta**. Ya no se toca.
2. **La salida por cambio de regimen** (2.4): **NO se incluye** (contaminada).
3. **El liston** (5): **IC 90 % entero > 0 y R medio >= +0,13**, >= 100 operaciones, 2022 positivo y la combinacion
   mejor que la idea 2 sola; en la reserva, R > 0 y la combinacion mejor que la idea 2 sola.
4. **Como se mide** (3): **simulador de cortos del estudio**, validado reproduciendo el espejo antes de medir.

## 7. Como se mide de verdad (08/10, escrito ANTES de medir A')

el propietario adelanta la medicion al 08/10 (como la B, la C y la D), en la exploracion y **sin tocar la reserva**. El
"simulador de cortos" se monta asi (`docs/estudios/segunda-ronda/cortos_a.py`), y cumple lo que pedia la decision 4
sin escribir un simulador nuevo con sus propios fallos:
- **Una base combinada:** las 8 monedas reales y, al lado, sus gemelas invertidas (`BTCINV/USDC` = C/precio, con el
  C del espejo). Un largo sobre la gemela ES un corto sobre la real: el stop y el objetivo saltan en las mismas velas
  y el stop sufre los huecos (las suposiciones de `paper.py` al reves). Cada operacion se pasa a corto con la cuenta
  exacta del espejo (`cortos.a_corto`: mismo riesgo, comisiones, financiacion pesimista).
- **La senyal de A' se calcula sobre los precios REALES** (EMA20, ATR, medias diarias de 50 y 200, BTC) y se entrega a
  la gemela en su escala: asi se evita la objecion del punto 3 (con medias diarias, la inversion no es exacta).
- **Un solo recorrido del bot** con las 16: largos (la idea 2) y cortos comparten los 3 huecos y las 19 reglas; una
  moneda y su gemela son el mismo simbolo (regla 4, 1 por simbolo).
- **Dos validaciones antes de medir:** solo largos tiene que reproducir la idea 2 de la primera ronda (293 op.) y
  solo los tres setups actuales sobre las gemelas con BTC bajista, los 220 cortos del espejo. Si alguna no sale, no
  se mide nada.
- **Aproximaciones que se diran:** el equity, la exposicion y el tope de 20 $ de las gemelas se cuentan en su escala
  (el nocional de un corto difiere en ~3 %, la distancia del stop) y la financiacion se resta despues, no en el equity.
- **Lo que decide**, sin cambios: la seccion 5 y la decision 3 (cortos solos con financiacion: >= 100 op., IC 90 %
  entero > 0 y R medio >= +0,13, 2022 positivo; la combinacion mejor que la idea 2 sola en la emparejada). El
  objetivo, maker como en todo el disenyo; el taker, solo informativo.
