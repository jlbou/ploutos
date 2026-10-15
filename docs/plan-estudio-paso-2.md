# Plan del paso 2: el estudio de la estrategia (BORRADOR, 15/10/2026)

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
- **Impuestos:** como se cuentan (p. ej. el tramo del ahorro sobre cada venta con ganancia, FIFO) **[decide]**.
- **Peor caida historica** lejos del suelo (p. ej. <= 35 %).
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
