# Plan del paso 2: el estudio de la estrategia (15/10/2026)

**CRITERIO APROBADO Y CONGELADO por el propietario el 15/10/2026 (decision 11, opcion a), antes de medir nada**
(etiqueta de git `criterio-paso2`). Cambiar algo de aqui = un intento nuevo, escrito y aprobado antes.
**V5:** recolector de libros de ordenes en el VPS durante 2 semanas; la exploracion se mide al acabar, con sus costes.

Del PRD v3 (`docs/prd-ploutos-v3.md`, secciones 1, 4 y 7) y las decisiones 1-9. **Nada se mide hasta que este plan y
el criterio esten aprobados y subidos a git.** Lo marcado **[decide el propietario]** se le pregunta una cosa por
mensaje.

## 0. Comprobaciones antes de nada (no miden estrategias)

| # | Que | Como | Estado |
|---|---|---|---|
| V1 | El demo tiene BTC/EUR y ETH/EUR | API publica con `x-simulated-trading: 1` | **Hecho (15/10): los dos `live`** |
| V2 | Comisiones REALES de BTC/EUR y ETH/EUR | `account/trade-fee` con una clave de la cuenta real (solo lectura) | **Hecho (15/10): grupo 18, maker 0,10 % y taker 0,20 % en los dos** (las configuradas) |
| V3 | Historia en euros desde 2017 | **Decidido (15/10, opcion a): la historia NATIVA en euros de Bitstamp** (BTC/EUR y ETH/EUR diarias desde 10/2017, API publica): sin cambio EUR/USD ni USDT | Bajada con permiso del propietario |
| V4 | Que Bitstamp se parezca a OKX donde coinciden (desde 11/2023) | cierres diarios en UTC (`1Dutc` en OKX), diferencia relativa | **Criterio fijado ANTES de mirar (15/10):** se acepta si la mediana de la diferencia absoluta es < 0,10 % y el 99 % de los dias < 1 %, en los dos pares; si no, se estudia por que antes de usar Bitstamp. **Resultado: BTC pasa; ETH NO (p99 1,026 %), por la poca liquidez de OKX en 11/2023-03/2024; el propietario acepta Bitstamp despues de verlo, escrito en `docs/estudios/paso2/v4-resultado.md`** |
| V5 | Profundidad de BTC/EUR y ETH/EUR en varios momentos (no una foto) | el libro cada hora durante 2 semanas, compra y venta | Pendiente (un recolector de solo lectura) |
| V7 | El error del descuento de USDT | ya no hace falta: la historia es nativa en euros (V3) | **Cerrado** |
| V6 | Si OKX spot deja dos stops de venta a la vez o hay que modificar el que hay | en el demo | Para el paso 3 (no afecta al estudio) |

## 1. Los datos y como se reparten

- **BTC/EUR y ETH/EUR de Bitstamp**, velas de 1 dia en UTC, desde 10/2017 (V3); OKX en euros (desde 11/2023) para
  comprobarlas (V4) y para los costes.
- **Exploracion:** 12/2020 - 09/2026 (ya vista en estudios anteriores: se puede explorar en ella, no prueba nada).
- **Prueba limpia, UNA vez:** 10/2017 - 11/2020 (sin mirar por ningun estudio de Ploutos: buscado el 15/10; que nadie
  la haya mirado nunca no se puede demostrar). Incluye el mercado bajista de 2018, el lateral de 2019 y la caida de
  03/2020. **La prueba limpia va ANTES en el tiempo que la exploracion**: se dice y se acepta (el mercado de 2018 no es
  el de hoy).
- **Calentamiento:** las medias largas (200 dias) necesitan historia previa; en la prueba limpia, los primeros 200
  dias solo calientan.
- **Despues:** el papel hacia adelante (fase siguiente) es la unica prueba del todo limpia.

## 2. Cuantos anyos hacen falta (antes de medir)

Con el deflactado (N = 35 + los intentos nuevos), para Sharpe 0,8 / 1,0 / 1,5, cuantos anyos de datos diarios hacen
falta para llegar a 0,95 (`docs/preregistro-papel-l.md` 2: con N = 35, ~107 / ~21 / ~3,7 anyos). La prueba limpia
tiene ~2,6 anyos utiles (3,1 menos el calentamiento). **Consecuencia que se dice antes:** con esos anyos, solo una
estrategia con un Sharpe muy alto podria pasar el deflactado en la prueba limpia; lo mas probable es "no se puede
demostrar con la historia".

**Calculo (15/10, con Bitstamp):** la prueba limpia util es de **1.002 dias (2,75 anyos, 04/03/2018-30/11/2020)**:
ETH desde el 16/08/2017 mas 200 dias de calentamiento. Para un deflactado >= 0,95 con N = 35-45 haria falta un Sharpe
anual de **1,65-1,80** (dispersion de los intentos 0,30-0,36).

**Decidido (propietario, 15/10, opcion a): el liston en dos etapas.**
- **Exploracion:** el deflactado (N >= 35 + los intentos nuevos) y el PBO < 0,50 sirven para **elegir UNA** candidata.
- **Prueba limpia, una vez y con una sola estrategia (N = 1 ahi):** el liston de la decision 1 (en euros y neto),
  no perder de forma grave en ningun tipo de mercado y **Sharpe probabilistico >= 0,95** frente a 0 (en 2,75 anyos,
  un Sharpe anual de ~1,0). El deflactado se informa, sin decidir.
- **Despues, el papel de 6-12 meses** confirma.

## 3. La lista cerrada de hipotesis (cada una cuenta como intento)

**Decidida por el propietario (15/10, opcion a) tras la revision de la literatura**
(`docs/estudios/paso2/recerca-hipotesis.md`; la primera lista no tenia fuentes y se rehizo):

| # | Hipotesis | Evidencia |
|---|---|---|
| H1 | **Tendencia con medias de 4 plazos** (20/50/100/200 dias), en BTC y ETH por separado; fuera, en euros | media (Detzel et al. 2021; Hudson y Urquhart 2019, que en BTC fuera de muestra no la ven) |
| H2 | **Rupturas de Donchian con varios plazos** juntas | media-baja (Zarattini et al. 2025, documento de trabajo) |
| H3 | **Momento de 1-4 semanas** (signo del rendimiento pasado) | media (Liu y Tsyvinski 2021; mas debil despues) |
| capa | **Tamanyo por volatilidad** dentro de H1 y H2, no como estrategia aparte | baja sola (Cederburg et al. 2020) |
| H5 | **"Muy seguro"** (decision 4): solo si H1 o H2 pasan sin ello | sin evidencia propia |

**Aplazadas:** scikit-learn (H4) y la rotacion BTC/ETH (sin evidencia directa). **3 intentos de base** (+ la capa y H5
si se usan): N = 35 + los que se prueben. Los parametros de cada una se fijan en el criterio, antes de medir; cada
combinacion probada es un intento y se calcula el PBO.

**Lo que se dice antes:** el estudio mas solido (Hudson y Urquhart) no encuentra predictibilidad en Bitcoin fuera de
muestra; lo mas probable es que ninguna pase.

## 4. El criterio (se fija antes de medir) **[decide el propietario, punto a punto]**

- **Liston (decision 1; propietario, 15/10, opcion a):** en euros, neto, contra BTC/EUR mantenido desde el mismo dia
  y con sus comisiones, pasa de UNA de dos maneras: **gana** (rendimiento anual >= el de BTC y caida maxima no mayor
  que la suya) **o protege** (rendimiento anual como mucho **5 puntos** por debajo del de BTC y caida maxima **<= 2/3**
  de la suya).
- **Contra la suerte:** deflactado >= 0,95 con N total; PBO < 0,50 si hay parametros probados.
- **Por tipo de mercado (propietario, 15/10, opcion a):** con BTC/EUR y su media de 200 dias, cada dia es
  **alcista** (precio sobre la media y la media sube), **bajista** (precio bajo la media y la media baja) o **lateral**
  (el resto). En cada tramo: en **bajista**, pierde menos que BTC; en **alcista**, gana al menos **la mitad** que BTC;
  en **lateral**, no pierde mas de un **10 % anualizado**.
- **Con las reglas del PRD v3 simuladas:** escalones, limite diario, suelo, exposicion y riesgo (techo 5 % / 10 %).
- **Costes:** comisiones de V2 (si no, las configuradas, 0,10/0,20 %) + deslizamiento de V5 con 10.000 €.
- **Impuestos (propietario, 15/10, opcion a):** los tramos de la base del ahorro de cada anyo natural (19 % hasta
  6.000 €, 21 % hasta 50.000 €, 23 % hasta 200.000 €, 27 % hasta 300.000 € y 30 % por encima; el ultimo, 28 % o 30 %
  segun la fuente: subido por la Ley 7/2024, sin efecto por debajo de 300.000 €), coste por **FIFO**, las perdidas
  compensan las ganancias del anyo y las sobrantes, las de los 4 anyos siguientes. **El BTC de referencia vende el
  ultimo dia y paga entonces** (el aplazamiento es una ventaja real de mantener). Fuentes de los tramos (15/10):
  guiafiscal.es, Rankia, Billeo; sin la norma oficial abierta.
- **Peor caida historica <= 35 %** (propietario, 15/10, opcion a): 15 puntos de margen hasta el suelo del 50 %.
- **Senyales de alarma:** Sharpe > 2 o fuera de muestra casi igual que dentro: se investiga antes de creer.

## 5. Las herramientas

- **Un simulador nuevo** para BTC/EUR y ETH/EUR con las reglas del PRD v3, con tests, validado contra un caso sencillo
  (comprar y mantener debe dar exactamente lo de BTC mantenido) antes de medir nada.
- Reutiliza lo que sirva de `docs/estudios/tendencia/tendencia.py` (copiado, no importado).

## 6. Revisiones (el metodo)

Plan -> revision con las skills (lookahead-bias, data-leakage, point-in-time, backtest-overfitting, deflated-sharpe)
-> correcciones -> revision final -> aprobacion del propietario -> subir el criterio -> medir la exploracion -> decidir
apalancamiento y cortos (decision 4) -> la prueba limpia, una vez -> veredicto.

## 7. Revision con las skills (15/10/2026) y correcciones

Skills: ml4t-lookahead-bias, ml4t-data-leakage, ml4t-point-in-time, ml4t-deflated-sharpe y ml4t-backtest-overfitting.

| # | Skill | Hueco | Correccion |
|---|---|---|---|
| R1 | point-in-time | El cambio EUR/USD oficial se publica cada dia habil por la tarde; la cripto cotiza 7 dias | Union "hacia atras": cada vela usa el ultimo cambio YA publicado a su cierre; fines de semana y festivos, el del ultimo dia habil |
| R2 | point-in-time | **USDT no siempre valio 1 dolar** (en 10/2018 cotizo con descuento de varios %): BTC/USDT × EUR/USD no es BTC en euros | Pasar a euros con una historia de USDT/USD (o de BTC en dolares de otra fuente) y medir el error; sin ella, el error se dice y se acota. Nueva comprobacion **V7** |
| R3 | lookahead-bias | El plan no dice cuando se ejecuta la senyal | La senyal con la vela cerrada del dia t; la orden, a la apertura de t+1 (o la vela siguiente), con sus costes |
| R4 | data-leakage | H4 (scikit-learn): escalado y seleccion de variables | Todo ajuste solo con el tramo de entrenamiento (Pipeline); walk-forward con purga y embargo del horizonte de la etiqueta; nunca validacion barajada |
| R5 | deflated-sharpe | El deflactado necesita la dispersion de los Sharpe de los intentos (V) y se calcula por periodo, no anualizado | V con los intentos guardados (`umbral.json`, 11) mas los nuevos; Sharpe diario; N = 35 + nuevos (prudente: los intentos estan correlacionados, el N efectivo seria menor) |
| R6 | backtest-overfitting | La prueba limpia util es de ~2,5 anyos, por debajo de los 5 que pide la skill | Se dice antes; el liston de la prueba limpia (seccion 2) lo decide el propietario sabiendolo |
| R7 | backtest-overfitting | H1 se parece a L, que se eligio DESPUES de ver la exploracion: su resultado en la exploracion no prueba nada | Solo cuenta la prueba limpia (y el papel); la exploracion solo descarta |
| R8 | backtest-overfitting | Costes de 2018 distintos de los de hoy | Se usan los costes de hoy (los que pagaria el bot), y se dice |

Con las correcciones, quedan para el propietario (una por mensaje): V2 (clave de solo lectura), V3 (bajar el cambio
oficial), el liston de la prueba limpia, la lista de hipotesis y los numeros del criterio (seccion 4).

## 8. Los parametros (propietario, 15/10, opcion a), fijados antes de medir

Velas diarias de Bitstamp cerradas a las 00:00 UTC; la senyal con la vela cerrada del dia t, la orden a la apertura de
t+1 (taker 0,20 % + el deslizamiento de V5 con 10.000 €; mientras V5 no este, 0,01 % por lado).

| | Senyal (cada moneda por separado) | Tamanyo y proteccion |
|---|---|---|
| **H1** | dentro si el cierre esta por encima de las 4 medias simples (20/50/100/200 dias); fuera al perder alguna | hasta **45 %** del equity por moneda (90 % entre las dos, regla 15), riesgo hasta el stop <= 5 % (regla 12); **stop 3 ATR(14)** fijo desde la entrada, en el exchange |
| **H2** | 4 plazos N = 20/50/100/200: cada uno entra si el cierre supera el maximo de los N dias anteriores y sale si baja del minimo de los N/2 anteriores; **tamanyo = media de los 4** (0-100 % del maximo) | igual que H1 |
| **H3** | **cada lunes**: el signo del rendimiento de 1, 2, 3 y 4 semanas; tamanyo = fraccion positiva de las 4 | igual que H1 |
| **H1v, H2v** | H1 y H2 con el tamanyo × **min(1; 60 % / volatilidad anualizada de 30 dias)** | igual que H1 |

**5 intentos nuevos; N = 40.** H5 ("muy seguro") solo si alguna pasa, como intento aparte.

## 9. Como se elige y se juzga

1. **Simulador validado** antes de medir nada: comprar y mantener tiene que dar exactamente BTC/EUR mantenido.
2. **Exploracion** (12/2020-09/2026): las 5, con todas las reglas del PRD v3 simuladas. **Candidata = la de mayor
   deflactado (N = 40) entre las que cumplan en la exploracion el liston y los tipos de mercado**; PBO de las 5 < 0,50.
   Si ninguna cumple, **se para aqui** y no se mira la prueba limpia.
3. **Decision 4** (apalancamiento y cortos), con la candidata, antes de mirar la prueba limpia.
4. **Prueba limpia** (04/03/2018-30/11/2020), una vez, solo la candidata: liston, tipos de mercado, caida <= 35 % y
   Sharpe probabilistico >= 0,95.
5. **Veredicto** escrito; si pasa, el paso 3 (construir) y el papel de 6-12 meses.

## 10. Revision final (15/10/2026)

- **Calentamiento de la exploracion:** sus medias de 200 dias usan precios de 06-11/2020, que son de la prueba limpia.
  Se usan solo para calcular indicadores; **el simulador no da ningun resultado de fechas de la prueba limpia** durante
  la exploracion (un test lo comprueba).
- **El orden:** la prueba limpia es anterior a la exploracion; 2018 (bajista) no es el mercado de hoy. Se dice.
- **El 60 % de la capa de volatilidad** no sale de los datos: es una volatilidad tipica de BTC; cambiarlo seria otro
  intento.
- **El ETH de la prueba limpia** empieza el 16/08/2017: con el calentamiento, la prueba arranca el 04/03/2018 para
  las dos monedas.
- **Pendiente antes de medir:** V5 (la profundidad en varios momentos); hasta entonces, 0,01 % de deslizamiento por
  lado (lo medido el 15/10 con 10.000 €: 0,003-0,006 %).

## 11. Aclaracion 1 (propietario, 16/10/2026, opcion a), antes de medir

Los 10 huecos de `docs/estudios/paso2/revision-candidatas.md`, aprobados tal como se propusieron (etiqueta
`criterio-paso2-a1`). No cambian nada de lo congelado; dicen como hace el simulador lo que estaba a medias:
C1 volver a entrar tras un stop solo con una senyal nueva (apagarse y encenderse; en H3, el lunes siguiente);
C2 en los escalones, la mitad del tamanyo (22,5 %) y del riesgo (2,5 %); C3 el stop sale a su precio o a la apertura si
abre por debajo; C4 el tipo de mercado con el cierre de ayer; C5 el tamanyo con el equity al cierre del dia de la
senyal; C6 los tamanyos parciales solo se ajustan si cambia la fraccion y la diferencia llega al minimo por orden;
C7 el limite diario desde las 00:00 UTC; C8 BTC mantenido compra a la apertura del primer dia y vende al cierre del
ultimo, con costes e impuesto al final; C9 el PBO con 5 configuraciones se calcula y se dice que es poco informativo;
C10 un test comprueba que ninguna media se calcula con menos dias de los que dice.
