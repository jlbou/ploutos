# Investigacion: que dice la evidencia sobre operar cripto (09/10/2026)

Pedida por el propietario tras quedarse la segunda ronda sin ideas que pasen ("a veure si pots trobar alguna cosa, sigui
aprendre, trobar una nova estrategia"). **Solo lectura de fuentes; no se ha medido nada.** Muchas fuentes son
preprints o resumenes: se dice el nivel de cada una. Filtro de todo: lo que le sirve a Ploutos (spot, solo largos,
50 $, 8 monedas grandes contra USDC, 4 h, comisiones 0,10/0,20 %, la IA como analista).

## 1. Lo que dice la literatura, por temas

**Momentum de serie temporal (tendencia de la propia moneda).** Es lo que mas apoyo academico tiene: Liu y Tsyvinski
(RFS 2021) encuentran que el rendimiento de 1-4 semanas predice el de las semanas siguientes. Pero su muestra acaba en
2018; un trabajo de 2025 (Arefev, SSRN) no encuentra efecto significativo en 2016-2023 para un minorista, y Han, Kang y
Ryu (SSRN) muestran que con costes y precios diarios muchos portafolios de momentum dejan de ganar. Un test de
practicante 2017-2025 fuera de muestra: la senyal de tendencia anyade ~0,05 de Sharpe; **lo que se mantiene es la
reduccion de caidas, no el rendimiento**.
- Encaja con lo medido aqui: la idea 2 y 2 + D bajan la caida maxima (25 % -> 18 %) pero acaban con el mismo dinero o
  menos que la referencia.

**El filtro de la media de 200 dias de BTC.** Un backtest abierto (10 monedas grandes, 2021-2026, 10 pb de coste) lo
describe asi: corta la caida maxima casi a la mitad (-90 % -> -54 %), pero **no gana a comprar y mantener** en Sharpe:
"control de caidas, no fuente de ventaja". Y tarda: BTC estuvo bajo su media mas de 9 meses (11/2025-08/2026).

**Momentum entre monedas (comprar las mas fuertes).** Liu, Tsyvinski y Wu (factores de mercado, tamanyo y momentum)
vs. replicas: en las 30 mas grandes, +1,74 %/semana en 2016-2020 solo con significacion del 10 %, y en el tramo
posterior negativo; casi todo lo publicado es largo-corto (inaccesible con la regla 1).

**Volatilidad (posicion mas pequenya cuando el mercado se agita).** En BTC hay estudios con mejoras grandes de Sharpe,
pero en muestra; en acciones, 103 estrategias fuera de muestra: no mejora. El bot ya dimensiona por la distancia del
stop (que es una forma de esto).

**Sentimiento (Fear & Greed), financiacion e interes abierto.** El indice de miedo y codicia **sigue al precio, no lo
predice** (2018-2025: no Granger-causa y no mejora la prediccion fuera de muestra; otro de 2026: util para leer el
riesgo, no como regla). Financiacion e interes abierto: algo de senyal en preprints, sin fuera de muestra claro.

**Estacionalidad (horas y dias).** Existe en bruto (p. ej. 21-23 h UTC), pero nadie la mide neta de costes, exige
operar a diario y huele a minado de datos.

**IA (LLM) operando.** Alpha Arena (Nof1, 10/2025): seis modelos con 10.000 $ reales en perpetuos; **cuatro de seis
perdieron**, varios mas del 40 %; las comisiones por operar demasiado pesaron mucho. Un benchmark academico en vivo
("When Agents Trade", arXiv 2510.11695) es mas favorable, pero ningun modelo gana siempre. **El disenyo que mejor sale
es el restringido** ("From Hypotheses to Factors", arXiv 2604.26747): el LLM PROPONE hipotesis y un motor determinista
con datos, costes y cortes fijos las prueba y las registra todas. Es la filosofia de Ploutos y de este metodo.

**Modelos de prediccion de velas.** Comparativa reciente (arXiv 2606.27100, acciones): mejoras sobre el paseo
aleatorio "escasas y pequenyas". Tesis con BTC/ETH/DOGE/XRP: lo mejor de media, una regresion lineal o Chronos-2, y el
sentimiento empeora el error. Kronos, medido aqui: no acierta.

**Minoristas.** Las cifras de "el 70-97 % pierde" vienen casi todas de encuestas o blogs (pocas con datos de cuentas);
la evidencia seria (Barber, Lee, Liu y Odean en Taiwan; futuros en Brasil) apunta en la misma direccion.

## 2. Lo que se aprende (lo mas util)

1. **Los resultados de Ploutos coinciden con la literatura:** en spot, solo largos y monedas grandes, la unica
   regularidad que aguanta es "estar dentro cuando sube y fuera cuando baja", y sirve sobre todo para **caer menos**,
   no para ganar mas que comprar y mantener. Nada de lo encontrado apunta a una ventaja grande que se nos escape.
2. **El liston, con fundamento.** El "Sharpe deflactado" (Bailey y Lopez de Prado) sube la exigencia segun cuantas
   variantes se han probado: con solo 7 configuraciones ya se espera un backtest de 2 anyos con Sharpe > 1 por pura
   suerte. Aqui se han probado ~25 variantes (contadas en `docs/archivo/diseno-tendencia.md`): es la razon por la que el liston tiene que ser alto, y la forma
   de fijarlo con numeros en vez de a ojo. Se puede adoptar para lo que se mida A PARTIR de ahora (no para rescatar lo
   ya medido).
3. **Donde puede aportar la IA:** no adivinando el precio, sino como en el disenyo restringido: proponer hipotesis que
   un motor fijo prueba (lo que ya preve la fase 8, `docs/archivo/diseno-aprendizaje.md`), y leer noticias como filtro de
   riesgo (los medios en sombra).
4. **Lo que NO hacer:** mas modelos de velas, estacionalidad horaria, indices de sentimiento, operaciones de horas.

## 3. Ideas que encajan con las reglas (sin medir, para decidir)

- **Rotacion semanal de tendencia, solo largos:** cada semana, de las 8, las hasta 3 con rendimiento de 4 semanas
  positivo y mas fuerte; si ninguna lo tiene, en USDC. Es lo que mas apoyo tiene, opera poco (menos comisiones) y es
  la familia de la idea 2. Cambia la forma del bot (no son setups de 4 h con OCO), asi que antes habria que ver como
  encaja en el PRD (regla 13: stop y objetivo siempre en el exchange).
- **Filtro de financiacion:** no entrar con la financiacion de los perpetuos muy alta (largos apalancados en exceso).
  Evidencia floja; la historia de financiacion habria que bajarla (la API publica da ~3 meses).
- Cualquiera de las dos, con el criterio fijado antes, el liston por numero de pruebas y la reserva al final.

## 4. Una cosa de fondo para el propietario

El PRD dice que el exito es (1) que se cumplan las reglas, (2) la trazabilidad y (3) saber si la IA aporta frente al
baseline; **"la rentabilidad es secundaria"**. La decision 4a del 25/09 (sin estrategia que no pierda en la reserva no
hay fase 7) es del propietario y es prudente, pero la literatura sugiere que una estrategia que GANE con claridad en spot, solo
largos, puede no existir. Vale la pena decidir que se quiere de la fase 7: ganar dinero, o medir la IA con dinero
real con el riesgo acotado (50 $ y las 19 reglas).

## 5. Ampliacion (10/10): como se sabe si una cripto sube o baja

Pedida por el propietario ("com es sap quan una cripto puja o baixa"). Solo lectura; no se ha medido nada.

**Lo primero: nadie lo sabe por adelantado.** Todos los metodos con algo de evidencia son REACTIVOS: confirman una
tendencia cuando ya ha empezado. El precio de eso es entrar tarde, salir tarde y equivocarse en los mercados laterales.

| Metodo | Que mira | Evidencia | Para Ploutos |
|---|---|---|---|
| Precio sobre su media (50, 100, 200 dias) | si el precio esta por encima de su media | Detzel et al. (Financial Management 2021): el cociente precio/media predice el rendimiento diario de BTC dentro y fuera de muestra. Hudson y Urquhart (Annals of OR 2021): ~15.000 reglas tecnicas, predictivas en muestra, **pero en BTC sin prediccion fuera de muestra** | Es H y el filtro de 2 + D |
| Rupturas a maximos (Donchian, "MAX") | si el precio marca el maximo de N dias | Zarattini, Pagani y Barbon (SFI 2025): varias Donchian de 5 a 360 dias juntas, solo largos, tamanyo por volatilidad; top-20 con Sharpe > 1,5 neto de comisiones. Quantpedia: comprar en el maximo de 10-50 dias aguanto 2022-2024 fuera de muestra; comprar en minimos, no | La familia de la tendencia; idea nueva posible: el conjunto de varios plazos |
| Rendimiento pasado (momentum de serie temporal) | si la moneda ha subido las ultimas 1-8 semanas | Liu y Tsyvinski (2021) si; Arefev (2025) y Han, Kang y Ryu, no tras costes (seccion 1) | Es F (fallo en la reserva) |
| Cruces de medias ("golden/death cross") | la media corta cruza la larga | 13 "death cross" desde 2011: a 3 meses, BTC mas abajo en 6 (una moneda al aire; Coin Metrics via Forklog) | No |
| On-chain (MVRV, precio realizado) | si los tenedores van muy en ganancia o en perdida | Solo proveedores y boletines; 3-4 ciclos; los picos se encogen cada ciclo | No: pocos ciclos, sin prueba seria |
| Liquidez global (M2) | si los bancos centrales inyectan dinero | Comentarios: retraso de 1-3 meses que cambia; con variaciones (no niveles), correlacion ~0,04 en el mismo mes | No |
| Sentimiento (Fear & Greed) | lo que dice la gente | Sigue al precio, no lo predice (seccion 1) | No |

**Lo que se aprende:**
1. Lo unico con evidencia razonable es **seguir el precio**: estar dentro cuando esta por encima de su media o en
   maximos, y fuera cuando no. Sirve sobre todo para **caer menos**; ganar mas que mantener, depende del periodo.
2. **Juntar varios plazos** (5, 20, 60, 120, 360 dias) en vez de uno solo reduce la dependencia de haber acertado el
   plazo, que es justo lo que le paso a F (28 dias, ajustado a 2021).
3. Lo demas (on-chain, liquidez, cruces, sentimiento) no tiene pruebas serias o tiene muy pocos ciclos.

Fuentes de la ampliacion: [Detzel et al.](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html),
[Hudson y Urquhart](https://link.springer.com/article/10.1007/s10479-019-03357-1),
[Zarattini, Pagani y Barbon](https://abarbon.com/papers/catching-crypto-trends)
([CXO](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/)),
[Quantpedia, MAX/MIN en BTC](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/),
[cruces, Forklog](https://forklog.com/en/will-bitcoins-golden-cross-appear-in-2026/),
[MVRV, Bitcoin Magazine](https://bitcoinmagazine.com/markets/how-the-updated-mvrv-z-score-improves-bitcoin-price-predictions),
[M2, BIT](https://www.bit.com/insights/knowledge-hub/global-m2-decoupling),
[200 dias, Bitget](https://www.bitget.com/news/detail/12560605704884).

## Fuentes

- Momentum y tendencia: [Arefev, SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/7405060.pdf?abstractid=7405060&mirid=1),
  [Han, Kang y Ryu, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565),
  [practicante, Summitward](https://summitward.com/learn/crypto-trend-following),
  [Liu, Tsyvinski y Wu, NBER](https://www.nber.org/system/files/working_papers/w25882/w25882.pdf),
  [momentum "has (not) its moments"](https://link.springer.com/article/10.1007/s11408-025-00474-9),
  [backtest con filtro de 200 dias](https://github.com/IsaacDodds/crypto-momentum-backtest),
  [AdaptiveTrend, arXiv 2602.11708](https://arxiv.org/abs/2602.11708).
- Volatilidad: [BTC, ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1042444X22000019),
  [103 estrategias en acciones](https://www.lehigh.edu/~xuy219/research/COWY.pdf).
- Sentimiento y derivados: [FGI no predice](https://www.sciencedirect.com/science/article/pii/S305070062600006X),
  [FGI 2026](https://ideas.repec.org/a/spr/digfin/v8y2026i3d10.1007_s42521-026-00218-y.html),
  [Palazzi et al., SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6725492).
- Estacionalidad: [Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/).
- IA operando: [Alpha Arena, Protos](https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto/),
  [When Agents Trade](https://arxiv.org/abs/2510.11695), [From Hypotheses to Factors](https://arxiv.org/abs/2604.26747).
- Modelos de velas: [arXiv 2606.27100](https://arxiv.org/pdf/2606.27100),
  [tesis del Politecnico di Milano](https://www.politesi.polimi.it/handle/10589/253774).
- Sobreajuste: [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf),
  [Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
- Minoristas: [resumen de cifras y su calidad](https://coinspot.io/en/cryptocurrencies/crypto-traders-lose-money-percentage/).
