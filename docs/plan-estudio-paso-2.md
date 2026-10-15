# Plan del paso 2: el estudio de la estrategia (BORRADOR, 15/10/2026)

Del PRD v3 (`docs/prd-ploutos-v3.md`, secciones 1, 4 y 7) y las decisiones 1-9. **Nada se mide hasta que este plan y
el criterio esten aprobados y subidos a git.** Lo marcado **[decide el propietario]** se le pregunta una cosa por
mensaje.

## 0. Comprobaciones antes de nada (no miden estrategias)

| # | Que | Como | Estado |
|---|---|---|---|
| V1 | El demo tiene BTC/EUR y ETH/EUR | API publica con `x-simulated-trading: 1` | **Hecho (15/10): los dos `live`** |
| V2 | Comisiones REALES de BTC/EUR y ETH/EUR | `account/trade-fee` con una clave de la cuenta real (solo lectura) | Pendiente: hoy solo hay clave del demo **[decide el propietario]** |
| V3 | Historia del cambio EUR/USD diario desde 2017, tal como se conocia cada dia | fuente oficial (p. ej. el BCE, publicado cada dia habil) | Pendiente: bajarla pide permiso **[decide el propietario]** |
| V4 | Que BTC/USDT pasado a euros se parezca a BTC/EUR de OKX desde 11/2023 | comparar cierres diarios (diferencia media y maxima) | Pendiente (tras V3) |
| V5 | Profundidad de BTC/EUR y ETH/EUR en varios momentos (no una foto) | el libro cada hora durante 2 semanas, compra y venta | Pendiente (un recolector de solo lectura) |
| V7 | Historia de USDT/USD (o BTC en dolares de otra fuente) desde 2017, para pasar a euros sin el error del descuento de USDT de 2018 | fuente publica a elegir **[decide el propietario si hay que bajarla]** | Pendiente (revision R2) |
| V6 | Si OKX spot deja dos stops de venta a la vez o hay que modificar el que hay | en el demo | Para el paso 3 (no afecta al estudio) |

## 1. Los datos y como se reparten

- **BTC y ETH contra USDT** en OKX, velas de 1 dia (y de 4 h si una hipotesis lo pide), desde 10/2017, pasadas a euros
  con el cambio de V3.
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
demostrar con la historia". **[decide el propietario: que liston usar en la prueba limpia con tan pocos anyos]**.

## 3. La lista cerrada de hipotesis (cada una cuenta como intento)

Pocas, porque cada una sube el liston. Propuesta (a revisar):

| # | Hipotesis | Por que |
|---|---|---|
| H1 | **Tendencia en el tiempo**: en BTC y en ETH, dentro si el precio esta por encima de sus medias (4 plazos, como L) y fuera en euros si no | lo que la literatura y L dicen que funciona (protege) |
| H2 | **Momento doble**: la mas fuerte de BTC y ETH en las ultimas N semanas si su rendimiento es positivo; si no, euros | rotacion simple entre dos, con salida a efectivo |
| H3 | **H1 con tamanyo por volatilidad** (menos exposicion cuando la volatilidad sube) | reduce caidas sin cambiar la senyal |
| H4 | **Modelo de scikit-learn** (decision 5) | la idea del propietario; con walk-forward, purga y PBO |
| H5 | **"Muy seguro"** (decision 4): con H1, mas tamanyo / cortos cuando la senyal es fuerte | la idea del propietario; solo si H1 ya pasa sin ello |

Los parametros de cada una se fijan antes; si se prueban varios, cada combinacion es un intento y se calcula el PBO.

## 4. El criterio (se fija antes de medir) **[decide el propietario, punto a punto]**

- **Liston (decision 1):** en euros y neto, gana mas que BTC mantenido, o lo mismo con una caida "claramente menor"
  (numero a fijar, p. ej. <= 2/3 de la de BTC).
- **Contra la suerte:** deflactado >= 0,95 con N total; PBO < 0,50 si hay parametros probados.
- **Por tipo de mercado:** subida, bajada y lateral (definidos con BTC/EUR y su media de 200 dias, fijado antes): no
  tiene que perder de forma grave en ninguno.
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
