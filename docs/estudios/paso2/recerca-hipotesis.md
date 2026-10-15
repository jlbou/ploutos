# Revision de la literatura: que hipotesis tienen evidencia para BTC y ETH (15/10/2026)

Generada con la skill `literature-review`. **Tipo: revision de alcance (scoping)**, no sistematica: busqueda
reproducible y cribado por titulo y resumen, sin leer los articulos enteros. Ventana: 2017-2026.
Fuentes: arXiv (API), Crossref (API), OpenAlex (API, para los resumenes), busqueda web para lo que faltaba.
Semantic Scholar se intento y se abandono (limite de peticiones sin clave).

## Pregunta

Para **BTC y ETH al contado, solo largo, sin apalancamiento, contra euros/efectivo, con frecuencia diaria o
semanal**: ¿que senyales tienen evidencia de **ganar a comprar y mantener**, o **igualarlo con menos caida**, **neto de
costes y fuera de muestra**?

**Incluido:** articulos de revista o documentos de trabajo de una institucion; BTC/ETH o cripto grande; reglas
diarias/semanales; con costes o fuera de muestra. **Excluido:** largo-corto con muchas monedas (no es nuestro caso, se
dice cuando informa), intradia, prediccion de precio sin estrategia, opiniones comerciales.

## Registro de busqueda (15/10/2026)

| Fuente | Consultas | Resultados unicos | Relevantes tras el cribado |
|---|---|---|---|
| arXiv | 6 (momento de series temporales, medias moviles, tendencia, volatilidad gestionada, aprendizaje automatico fuera de muestra, momento con costes) | 41 | 6 |
| Crossref | 7 (las mismas ideas, articulos de revista desde 2017) | 136 | 9 |
| OpenAlex | 15 DOI concretos + 1 titulo, para leer resumenes | 17 | 14 |
| Web | 6 (lo que no tenia resumen) | — | 5 |

Datos crudos (fuera de git): `var/estudios/recerca/{arxiv,crossref,openalex}.json`.

## La evidencia, por temas

### 1. Tendencia con medias moviles y reglas tecnicas — **confianza media**
- **Hudson y Urquhart (Annals of Operations Research, 2019):** ~15.000 reglas, cinco familias, con correcciones por
  probar muchas (data snooping): predicen y protegen de caidas largas frente a comprar y mantener. **Pero, en sus
  palabras, no hay predictibilidad para Bitcoin en el periodo fuera de muestra** (si en otras monedas). *[resumen leido]*
- **Detzel, Liu, Strauss y Zhou (Financial Management, 2021):** el cociente precio/media movil predice el rendimiento
  diario de Bitcoin dentro y fuera de muestra; las estrategias dan alfa y mejor Sharpe que comprar y mantener.
  *[resumen leido]*
- **Grobys, Ahmed y Sapkota (Finance Research Letters, 2020):** medias de 20 dias, 11 monedas, 2016-2018: funciona
  **excluyendo a Bitcoin**. *[resumen leido]*
- **Svogun y Bazan-Palomino (J. Int. Fin. Markets, 2022):** 69 reglas, 2016-2021: ganar a comprar y mantener depende
  de las burbujas; en Bitcoin, las burbujas no ayudan. *[resumen secundario]*
- **Corbet et al. (Finance Research Letters, 2019):** reglas de medias moviles efectivas en cripto. *[solo titulo]*
- **Lo que se repite:** las reglas **reducen las caidas**; **ganar a mantener BTC, fuera de muestra y neto, es dudoso
  en Bitcoin** y mas probable en otras monedas.

### 2. Conjuntos de plazos (varias medias o rupturas a la vez) — **confianza media-baja**
- **Zarattini, Pagani y Barbon (Swiss Finance Institute, documento de trabajo 25-80, 2025):** varias rupturas de
  Donchian con plazos distintos juntas, tamanyo por volatilidad, solo largos: en las 20 monedas mas liquidas, Sharpe
  > 1,5 y alfa del 10,8 % anual frente a Bitcoin, neto. Empiezan por Bitcoin solo. **No revisado por pares**; varias
  monedas. *[resumen secundario]*
- Juntar plazos reduce el riesgo de elegir el plazo con suerte (lo mismo que mostro la robustez de L, 10/10).

### 3. Momento de series temporales (rendimiento de 1-4 semanas) — **confianza media**
- **Liu y Tsyvinski (Review of Financial Studies, 2021):** "fuerte efecto de momento de series temporales" en cripto.
  *[resumen leido]* Su muestra acaba hacia 2018-2019.
- Documentos posteriores (Arefev 2025; Han, Kang y Ryu) lo ven debilitado tras costes (de
  `docs/estudios/recerca-trading-cripto.md`, **no releidos hoy**). Kang y Ryu (Risk Management, 2026) existe, sin
  resumen accesible.

### 4. Rotacion entre dos (momento doble BTC/ETH) — **confianza baja**
- **No se encontro evidencia academica directa** para rotar entre BTC y ETH. El momento entre monedas (Liu, Tsyvinski
  y Wu, Journal of Finance 2022) es **largo-corto con cientos de monedas**: no se traslada a dos.

### 5. Gestion por volatilidad — **confianza baja en BTC**
- **Moreira y Muir (Journal of Finance, 2017):** en acciones y factores, menos riesgo con volatilidad alta sube el
  Sharpe. *[resumen leido]*
- **Cederburg et al. (Journal of Financial Economics, 2020):** en 103 estrategias de acciones, **fuera de muestra y en
  tiempo real lo hace peor** que sin gestionar en la mayoria. *[resumen secundario]*
- En cripto solo hay piezas de practicantes o articulos poco citados (Yang, Finance Research Letters 2025, sin leer).
- Como capa de tamanyo dentro de una regla de tendencia (como Zarattini et al.) es otra cosa que como estrategia sola.

### 6. Aprendizaje automatico — **confianza baja**
- Muchos articulos, casi todos con **una sola muestra de prueba corta, muchos modelos probados** (41 en
  arXiv 2407.18334) y **rendimientos muy altos** (Sharpe > 3 tras costes en una revista de 2022, *[resumen secundario]*): las senyales de alarma
  de la skill de sobreajuste. Ninguno con el rigor de las secciones 1-3.
- Antecedentes propios: Kronos no acerto en cripto (08/10); en Ebisu, scikit-learn no aporto (PBO 0,77).

### 7. Lo que se descarta por la evidencia o por el alcance
- Estrategias con Sharpe > 2 (p. ej. arXiv 2602.11708, 2,41, largo-corto en 150 monedas): senyal de alarma y fuera
  del alcance.
- Intradia (Shen, Urquhart y Wang, Financial Review 2021): fuera del ritmo del bot.

## Que significa para la lista de hipotesis

| Antes (sin revision) | Con la evidencia | Propuesta |
|---|---|---|
| H1 tendencia con medias (4 plazos) | la mejor apoyada (temas 1 y 2), pero en BTC fuera de muestra es dudosa | **Se queda** |
| — | rupturas de Donchian en conjunto (tema 2) | **Nueva H2** (alternativa de tendencia; documento de trabajo) |
| H2 momento doble BTC/ETH | sin evidencia directa (tema 4) | **Fuera** (o en el ultimo lugar) |
| H3 H1 + volatilidad | debil fuera de muestra (tema 5) | **Como capa de tamanyo de H1/H2**, no aparte |
| — | momento de 1-4 semanas (tema 3) | **Nueva H3** |
| H4 scikit-learn | debil (tema 6) | **Aplazada**, o con un solo modelo fijado antes |
| H5 "muy seguro" | sin evidencia propia; depende de que H1/H2 pasen | **Se queda condicionada** (decision 4) |

## Huecos y limites de esta revision

- No se leyeron los articulos enteros: hay afirmaciones de resumenes secundarios (marcadas).
- Sin Semantic Scholar ni SSRN directos; la busqueda web cubrio parte.
- Casi toda la evidencia acaba antes de 2022; la de despues es mas floja (documentos de trabajo).
- La evidencia mas fuerte (Hudson y Urquhart) dice justo lo que preocupa: **en Bitcoin, fuera de muestra, nada**.

## Referencias

- Hudson, R. S. y Urquhart, A. (2019). Technical trading and cryptocurrencies. *Annals of Operations Research*.
  [10.1007/s10479-019-03357-1](https://doi.org/10.1007/s10479-019-03357-1)
- Detzel, A., Liu, H., Strauss, J., Zhou, G. (2021). Learning and predictability via technical analysis.
  *Financial Management*. [10.1111/fima.12310](https://doi.org/10.1111/fima.12310)
- Grobys, K., Ahmed, S., Sapkota, N. (2020). Technical trading rules in the cryptocurrency market. *Finance Research
  Letters*. [10.1016/j.frl.2019.101396](https://doi.org/10.1016/j.frl.2019.101396)
- Svogun, D. y Bazan-Palomino, W. (2022). Technical analysis in cryptocurrency markets: Do transaction costs and
  bubbles matter? *J. Int. Financial Markets, Institutions and Money*. [10.1016/j.intfin.2022.101601](https://doi.org/10.1016/j.intfin.2022.101601)
- Corbet, S., Eraslan, V., Lucey, B., Sensoy, A. (2019). The effectiveness of technical trading rules in
  cryptocurrency markets. *Finance Research Letters*. [10.1016/j.frl.2019.04.027](https://doi.org/10.1016/j.frl.2019.04.027)
- Zarattini, C., Pagani, A., Barbon, A. (2025). Catching Crypto Trends. *Swiss Finance Institute RP 25-80*
  (documento de trabajo). [ideas.repec.org](https://ideas.repec.org/p/chf/rpseri/rp2580.html)
- Liu, Y. y Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *Review of Financial Studies*.
  [10.1093/rfs/hhaa113](https://doi.org/10.1093/rfs/hhaa113)
- Liu, Y., Tsyvinski, A., Wu, X. (2022). Common risk factors in cryptocurrency. *Journal of Finance*.
  [10.1111/jofi.13119](https://doi.org/10.1111/jofi.13119)
- Moreira, A. y Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance*.
  [10.1111/jofi.12513](https://doi.org/10.1111/jofi.12513)
- Cederburg, S., O'Doherty, M., Wang, F., Yan, X. (2020). On the performance of volatility-managed portfolios.
  *Journal of Financial Economics*. [10.1016/j.jfineco.2020.04.015](https://doi.org/10.1016/j.jfineco.2020.04.015)
- Shen, D., Urquhart, A., Wang, P. (2021). Bitcoin intraday time series momentum. *Financial Review*.
  [10.1111/fire.12290](https://doi.org/10.1111/fire.12290)
- Kang, Y. y Ryu, D. (2026). Time-series momentum and market timing in Bitcoin. *Risk Management*.
  [10.1057/s41283-026-00234-7](https://doi.org/10.1057/s41283-026-00234-7) (sin resumen accesible)
- arXiv: [2407.18334](https://arxiv.org/abs/2407.18334), [2602.11708](https://arxiv.org/abs/2602.11708),
  [2602.10785](https://arxiv.org/abs/2602.10785) (preprints).
