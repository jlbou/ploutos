# Propuesta: como revisar la estrategia antes de la fase 7

Estado: **DECIDIDO por el propietario el 25/09/2026: 1a, 2a, 3a y 4a** (seccion 6): reserva USDT sin mirar, lista
cerrada de 5, se aplica tras el veredicto de la fase 6, y sin estrategia que pase la reserva no hay
dinero real. Es el METODO, no la revision:
no se ha medido ninguna idea todavia. Decision del propietario del 25/09: revisar la estrategia antes de la
fase 7 (`docs/archivo/propuesta-time-stop.md`).

## 1. El problema

En un anyo de datos reales (21/08/2025-25/09/2026) el baseline pierde: 159 operaciones, 19 % de
aciertos, **-0,38 R de media**, de 50 $ a 37,74 $. Pierde en el tramo bajista y en el alcista. Con esta
estrategia, la fase 7 (dinero real) perderia dinero. Donde se pierde (del mismo estudio):

- el 27 % de las operaciones muere en 0-1 velas (-1,31 R): la compra limit se llena PORQUE el precio cae;
- los stops cuestan -1,27 R de media, no -1 (huecos y comision de salida);
- por setup: pullback -0,47 R (73 op.), reversion -0,50 R (43), ruptura -0,10 R (43).

## 2. El riesgo: sobreajustar

Probar muchas ideas sobre los mismos datos hasta que una "funcione" siempre acaba encontrando algo, y
casi siempre es azar. Por eso el metodo se decide ANTES de medir nada: que datos se usan para buscar,
cuales se guardan sin mirar, que ideas se prueban y cuando una idea cuenta como buena.

**Un aviso honesto:** el anyo contra USDC ya lo hemos mirado (el estudio del time-stop y el diagnostico
de arriba salen de ahi). Las ideas de la seccion 4 se nos ocurrieron mirandolo, asi que ese anyo ya no
sirve como comprobacion limpia.

## 3. Los datos

Medido el 25/09 (`docs/hallazgos-fase-3-4.md`, 5b): contra USDC solo hay un anyo; contra USDT, de 5 a 8
(BTC y ETH desde 2017; las 8 a la vez desde el 02/12/2020). Los precios contra USDT se parecen a los de
USDC un 0,05-0,36 % de media: sirven para buscar patrones con stops del ~3,3 %.

Propuesta de reparto (decision 1):

| Tramo | Datos | Para que |
|---|---|---|
| Exploracion | USDT, 02/12/2020 -> 30/06/2024 (~3,5 anyos, las 8; incluye el bajista de 2022) | medir las ideas, tantas veces como haga falta |
| **Reserva** | USDT, 01/07/2024 -> 20/08/2025 (~14 meses, las 8) | **se mira UNA sola vez**, al final, con la idea ya fijada |
| Segunda comprobacion | USDC, el anyo ya visto | que la idea no se rompa con los precios de verdad |

Todo con el mismo recorrido que el bot (`scripts/replay_baseline.py`: el bucle de verdad, las 19 reglas,
comisiones de `settings.yaml`, spread medido) y el resultado por candidato (contrafactual, como la fase 6).

## 4. Las ideas: una lista CERRADA (decision 2)

Cinco, escritas antes de medir. Solo se prueban combinaciones de dos si cada una por separado mejora.

1. **No comprar cayendo:** en vez de una orden limit que se llena mientras el precio baja, entrar solo
   si la vela cierra por encima del nivel (confirmacion). Ataca el 27 % que muere en 0-1 velas.
2. **Filtro de tendencia de BTC:** no abrir largos si BTC esta en tendencia bajista en 1 dia (por
   ejemplo, cierre bajo su media de 200). El bot solo va largo (regla 1): en un mercado que cae, no entrar.
3. **Solo la ruptura:** quitar pullback y reversion, que son los que mas pierden.
4. **Stop y objetivo por setup:** el multiplo de ATR de cada setup, dentro de un rango fijado antes
   (1,5-2,5 el stop; el objetivo, lo que exija la regla 16).
5. **Velas de 1 dia en vez de 4 h:** menos operaciones y menos coste por operacion.

Nada de esto toca las 19 reglas duras: son setups, filtros y parametros de `settings.yaml`.

## 5. Cuando una idea cuenta como buena

Fijado antes de medir:
- **En la exploracion:** R medio por operacion con intervalo del 90 % (bootstrap por dias) ENTERO por
  encima del baseline actual, con >= 100 operaciones. Y que no gane solo en un tramo (se mira por anyos).
- **En la reserva (una vez):** R medio > 0 y mejor que el baseline actual. Si no, la idea se descarta,
  aunque en la exploracion fuera buena: eso es precisamente lo que la reserva sirve para ver.
- **En el anyo USDC:** que no pierda mas que el baseline actual.
- Siempre al lado: comprar y esperar BTC y las 8 a partes iguales.

## 5b. Resultados (se van anyadiendo)

- **26/09 - La referencia** (la estrategia actual en la exploracion, 3,5 anyos): 497 operaciones,
  **+0,13 R** (IC 90 %: -0,04 a +0,30), gana en 2021 y 2023, pierde en 2022 (-0,35 R). La reversion pierde
  (-0,59 R, IC entero bajo cero). Detalle y limites: `docs/estudios/revision-estrategia/README.md`.
- **26/09 - Las 5 ideas:** ninguna pasa el criterio tal como se fijo. La unica que cambia algo es la 2
  (tendencia de BTC): +0,28 R (IC +0,06 a +0,51), caida maxima 18 %, ni una operacion en 2022; no pasa por
  poco (el extremo bajo no llega a +0,13). Detalle en el README del estudio (seccion 3). Decision del propietario
  del 26/09: la idea "quitar solo la reversion" (salio de mirar) se decide despues de las 5.
- **26/09 - Decision del propietario (opcion A):** el criterio NO se cambia. Se prueba la combinacion de las dos ideas
  que mejoran solas (2 + 3) con el mismo criterio. La comparacion emparejada (idea contra referencia sobre las
  mismas velas) se calcula SOLO como informacion. Si la combinacion no pasa, se decide con esos dos numeros.
- **26/09 - Combinacion 2 + 3: no pasa** (+0,10 R, IC -0,10 a +0,31), peor que cada una. La emparejada tampoco
  demuestra ventaja de la 2 en total (+17 R, IC -38 a +70). **Fin de la primera ronda: ninguna idea demuestra
  que mejore.** el propietario, 26/09: en mercado bajista el bot se queda fuera; vender en corto (abrir la regla 1),
  descartado. Detalle: `docs/estudios/revision-estrategia/README.md`, seccion 4.
- **26/09 - el propietario: se ESPERA al veredicto de la fase 6** (desde el 16/10) para decidir si hay segunda ronda y de
  que. La fase 7 queda parada hasta tener una estrategia que no pierda en la reserva (decision 4a).
- **28/09 - el propietario: los CORTOS pasan a ser idea CANDIDATA de la segunda ronda** (revisa lo del 26/09, que los
  descartaba). Solo como estudio con la historia, con la misma reserva sin mirar y sin tocar el bot: **la
  regla 1 NO cambia** y abrirla seria otra decision del propietario, con los numeros delante. Lo que tendria que medir:
  los costes reales del corto (intereses del margen o financiacion de los futuros), el riesgo de liquidacion con
  posiciones de ~15 $, y si en los tramos bajistas gana de verdad (que el baseline pierda al caer no significa
  que apostar a la baja gane). Antes, verificar si OKX EEA ofrece margen o futuros a un particular (no se sabe;
  no suponerlo). Opcional, a peticion suya: volver a medir velas de 1 h con los 4 anyos de USDT (en la fase 2,
  con menos datos, las comisiones se comian el 66 % del bruto).
- **28/09 - Si OKX EEA ofrece cortos a un particular: SI, por dos caminos** (leido en paginas de OKX y prensa,
  sin clave ni cuenta; la API publica de instrumentos no sirve para saberlo: da la lista global en todos los hosts):
  1. **Margen de spot (EEA Spot Margin):** pedir prestada la moneda y venderla, hasta 10x en mercados
     seleccionados, interes cada hora, test de idoneidad, liquidacion con el ratio de margen al 100 %. El
     prestamo lo da OKX Europe pero **queda fuera de MiCA**, y si la liquidacion no cubre la perdida, **la deuda
     es tuya** (no hay proteccion de saldo negativo).
  2. **X-Perps (desde el 15/04/2026, MiFID II, OKX Europe con licencia de la MFSA):** futuros "perpetuos" con
     vencimiento a 5 anyos (asi los permite MiFID a minoristas), hasta 10x, **financiacion (funding)** como un
     perpetuo, test de idoneidad obligatorio, **proteccion de saldo negativo** (no se pierde mas que la garantia),
     garantia en EUR, USD o cripto, y API. Monedas al salir: BTC, ETH, SOL, XRP, DOGE, ADA, LTC, SUI, PEPE, PUMP
     (AVAX, TRX y NEAR, sin confirmar).
  **Sin saber todavia:** comisiones y cada cuanto se cobra la financiacion de los X-Perps; que pares de margen hay
  contra USDC; si el demo tiene X-Perps; si la clave de API actual serviria (esta limitada por moneda y a spot).
  **Lectura:** si algun dia se abre la regla 1, los X-Perps son el camino menos malo (la perdida maxima queda
  acotada); el margen de spot puede dejar deuda. En los dos, habria que medir la financiacion o el interes.
  Fuentes: okx.com/en-eu/help/eea-spot-margin-faq, okx.com/en-us/learn/okx-x-perps-mifid-regulated-crypto-
  futures-derivatives-europe, financemagnates.com (X-Perps, 15/04/2026), businesswire (lanzamiento, 15/04/2026).

## 6. Decisiones para el propietario

**1. Que datos se reservan.**
- a) **Explorar con USDT 12/2020-06/2024 y reservar USDT 07/2024-08/2025 (sin mirar)**; el anyo USDC,
  como segunda comprobacion (recomendado).
- b) Explorar con todo lo que hay y validar solo en vivo, con la fase 6 (semanas, poca muestra).

**2. Que ideas se prueban.**
- a) **La lista cerrada de 5**, y combinaciones de dos solo de las que mejoran solas (recomendado).
- b) Lista abierta: probar lo que vaya saliendo (mas facil encontrar algo, y mas facil que sea azar).

**3. Cuando se aplica una estrategia nueva.**
- a) **Despues del veredicto de la fase 6 y antes de la fase 7** (recomendado): cambiarla antes partiria
  la muestra de la fase 6 y mediriamos la IA contra dos baselines distintos.
- b) En cuanto este validada, aunque parta la muestra.

**4. Si ninguna idea pasa la reserva.**
- a) **No pasar a dinero real hasta tener una estrategia que no pierda en la reserva** (recomendado):
  con -0,38 R de media, la fase 7 perderia unos 12 $ al anyo sin ensenyar nada nuevo.
- b) Fase 7 igualmente, como aprendizaje: el PRD acepta una rentabilidad "baja o negativa".
