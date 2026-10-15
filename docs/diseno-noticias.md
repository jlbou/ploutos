# Disenyo de la pieza de noticias

Estado: **DISENYO con las decisiones del propietario del 25/09/2026** (seccion 9: 1a, 2a, 4 como se
proponia; la 3, a su manera: ver alli). Lo ya decidido por el propietario (22/09, en CLAUDE.md) no se re-litiga:
pieza propia entre la fase 3 y la 6; servicio aparte `ploutos-news` con base propia; primero lo
determinista (anuncios de OKX + palabras clave); si la fuente cae se avisa pero no se bloquea; una
flag critica ya vista se mantiene hasta que caduque. Aqui va el COMO, con datos reales, y las
decisiones que quedan (seccion 9). No se escribe codigo hasta el OK.

## 1. Que pide el PRD, exactamente

- Seccion 6: las noticias son **solo un filtro de riesgo** (flags que bloquean o reducen entradas),
  **nunca una senyal de compra**, y son **texto no confiable**.
- Seccion 5: al gestionar posiciones, **salida a mercado ante una flag critica de hackeo o
  deslistado**.
- Informe 3.4: flags por moneda (`hack`, `delisting`, `regulatory`, `exploit`, `macro_event`,
  `unlock`); los anuncios del propio exchange son "muy relevantes"; deduplicar.

## 2. Lo medido: el historial entero de anuncios de OKX (24/09/2026)

API publica `GET /api/v5/support/announcements?annType=<tipo>&page=<n>` por `eea.okx.com` (sin
claves). Cada anuncio trae SOLO `annType`, `title`, `url`, `pTime` y `businessPTime`: **no dice a
que moneda afecta**; hay que sacarla del titulo.

Bajados los 5 tipos que pueden importar (deslistados, suspensiones de depositos y retiradas,
cambios de trading, otros, nuevos listados): **1.758 anuncios, desde el 03/03/2023**.

| | Anuncios |
|---|---|
| Mencionan alguna de las 8 monedas (buscando ticker o nombre sin cuidado) | 117 |
| ...de verdad de las 8 (sin "Bitcoin Cash", "Ethereum Classic", "Wrapped Bitcoin"...) | 92 |
| ...de derivados, Earn, staking, campanyas (no afectan al spot) | 51 |
| ...informativos (mantenimiento de red, actualizaciones, listados) | 41 |
| **...criticos (deslistado, suspension de trading, incidente, migracion) de NUESTRAS 8** | **0** |

Y las mismas reglas sobre TODAS las monedas si detectan lo que tienen que detectar: 59
deslistados, 87 migraciones de token, 4 avisos de volatilidad (entre ellos "Price Volatility of
MANTRA (OM)", el desplome del 14/04/2025) y 1 suspension de trading.

**Tres cosas que salen de esto:**
1. **El tipo del anuncio no basta:** "DAI Delisting Announcement EEA" y la volatilidad de MANTRA
   estan en `announcements-others`, no en deslistados. Se leen todos los tipos y se clasifica por
   el titulo.
2. **Buscar la moneda sin cuidado da falsas alarmas**: "Bitcoin Cash" no es BTC, "Ethereum
   Classic" no es ETH, "NEAR" en mayusculas es la moneda y "near" no. Y "suspend USDC deposit on
   SOLANA network for wallet maintenance" es rutina, no un problema de SOL.
3. **OKX nunca ha anunciado un hackeo** (0 titulos con hack/exploit/attack en 3,5 anyos). Los
   anuncios cubren deslistados, migraciones y suspensiones; un hackeo de una red solo se veria en
   los medios, que meten mucho mas ruido ("hackers stole 5 M$ in ETH" no es un hackeo de Ethereum).

## 3. Las flags

Una flag = (moneda, tipo, gravedad, fuente, id del anuncio, titulo, url, visto_ms, caduca_ms).

| Tipo | Ejemplo real (de otra moneda) | Gravedad | Efecto | Caduca |
|---|---|---|---|---|
| `delisting` | "OKX to delist DORA, ICX... spot trading pairs" | CRITICA | no entrar + **salir a mercado** si hay posicion | **nunca sola**: hasta que el propietario la quite (y cambie whitelist + clave de OKX) |
| `trading_suspension` | "LEND Trading Suspensions" | CRITICA | no entrar + salir a mercado | 72 h, o al ver la reanudacion |
| `migration` | "OKX to support OM crypto migration" | ALTA | no entrar (la posicion sigue con su OCO) | 7 dias |
| `incident` | (solo medios, ver seccion 5) | CRITICA | no entrar + salir a mercado | 72 h |
| `volatility` | "Price Volatility of MANTRA (OM)" | ALTA | no entrar | 24 h |
| informativo | mantenimiento de red, upgrade, hard fork | - | nada; se guarda y se ensenya en el panel | - |

Por que salir a mercado solo con las CRITICAS: es lo que pide el PRD (hackeo o deslistado), y con
un deslistado el par deja de cotizar en dias; con una migracion la OCO ya protege y salir a
mercado en un momento de nervios paga el peor spread.

**Aplicacion:** las flags las lee el filtro de `strategy/filters.py` **antes** del baseline y de
la IA: **los dos reciben exactamente la misma lista** y la comparacion de la fase 6 no se toca (su
M1 compara sobre la lista que vio la IA). La salida a mercado la hace el bucle, determinista, en
las dos carteras igual. La IA no ve los titulos (no hay superficie de inyeccion).

## 4. Las piezas

| Pieza | Que hace | Puro |
|---|---|---|
| 1. `features/news.py` | titulo + tipo -> flags. Monedas por ticker en mayusculas como palabra entera y por nombre (sin "Cash", "Classic", "Wrapped"...); ruido fuera (derivados, Earn, campanyas); reglas de la tabla | si |
| 2. `data/news/okx.py` | pide los anuncios nuevos cada 5 min (4-5 peticiones, una por tipo); User-Agent fijo | no |
| 3. Base `var/ploutos-news.db` | anuncios vistos (sin duplicados, por `url`) y flags con su caducidad | - |
| 4. Servicio `ploutos-news` | el bucle de 2 y 3, con su latido (quinta comprobacion de Healthchecks; el plan gratuito da 20) | no |
| 5. Filtro en `strategy/filters.py` | moneda con flag activa = no genera candidatos, con el motivo en el journal | si |
| 6. Salida en el bucle | flag CRITICA + posicion abierta = cerrar a mercado (papel: a la apertura de la vela siguiente, como taker) | si |
| 7. Avisos de Telegram | flag nueva, flag que caduca, fuente caida mas de 1 h. **El titulo va escapado** (`esc()`): es texto de fuera metido en HTML | si |
| 8. Juez `check_news.py` | el servicio no ha tenido huecos; cada flag tiene su anuncio; ninguna vela con flag activa genero candidatos de esa moneda | no |

Los bucles de papel leen la base de noticias en `mode=ro`, como la principal: un escritor por base.

### Estado de las piezas (25/09/2026)

**Todas hechas y probadas, sin desplegar**, en la rama `noticias-servicio` (que junta
`fase-3-integracion` y `noticias`):

| Pieza | Donde |
|---|---|
| 1. Clasificacion | `features/news.py` (`clasificar`) |
| 2. Lector de OKX | `data/news/okx.py` |
| 3. Base y ciclo de vida | `data/store/news_migrations/`, `data/news/store.py`, `features/news.py` (`flags`) |
| 4. Servicio | `scripts/run_news.py`, `deploy/ploutos-news.service` |
| 5. Filtro | `filter_event` (ya existia) + `features/news.event_flags` + el bucle (al CIERRE de la vela) |
| 6. Salida a mercado | `PaperBroker.close_at_market`, el bucle, y el juez de papel que la audita |
| 7. Avisos | `notify/messages.py` (`aviso_noticia`, `noticias_pendientes`, `fuente_noticias_caida`) |
| 8. Juez | `scripts/check_news.py` |

**Se despliega junto con los comandos de Telegram** (decision del propietario del 25/09): los pasos
conjuntos estan en `docs/diseno-comandos-telegram.md`. Los de esta pieza sola eran: fusionar `noticias-servicio`;
el propietario crea en Healthchecks una QUINTA comprobacion (`ploutos-news`, periodo 10 min) y su URL va al
`.env` del VPS como `HEALTHCHECK_NOTICIAS`; instalar y arrancar `ploutos-news`; reiniciar las dos
carteras (para que lean la base de noticias); `check_news.py` y `check_paper.py` en verde; una
semana despues, `check_news.py` con salida 0 cierra la pieza.

## 5. Los medios (RSS), en una segunda etapa y EN SOMBRA

Solo con los medios se veria un hackeo de una red. Pero el ruido es mucho mayor, asi que:
- Etapa 2, despues de que la etapa 1 (OKX) lleve semanas estable.
- **En sombra primero:** las flags de los medios se calculan y se guardan, pero NO se aplican,
  durante al menos 2 semanas. Se revisa a mano cuantas eran de verdad y cuantas falsas alarmas.
  Solo con esos numeros se decide activarlas.
- Fuentes candidatas (informe 3.4): RSS directos de CoinDesk, Cointelegraph, The Block, Decrypt.
  Google News RSS no es oficial y puede cambiar sin aviso. CryptoPanic: planes cambiantes, verificar.
- Deduplicar: la misma noticia en 20 medios es UNA flag.

## 6. Tests

- **El historial real como banco de pruebas:** los 1.758 anuncios (datos publicos) guardados como
  fixture. Test: sobre nuestras 8, cero flags; sobre todas, los 59 deslistados, las 87 migraciones y
  los 4 de volatilidad detectados. Si una regla cambia, se ve que gana y que pierde.
- Titulos inventados para lo que la historia no tiene: "OKX to delist NEAR", "OKX to suspend
  XRP/USDC trading", "near-term update" (no es NEAR), "Bitcoin Cash hard fork" (no es BTC).
- Titulos maliciosos: HTML y texto de inyeccion en el titulo no rompen Telegram ni llegan a Claude.
- Filtro y salida: con flag, ni el baseline ni la IA ven la moneda; con flag critica y posicion,
  se cierra en las dos carteras igual.

## 7. Que NO hace

- No compra nunca por una noticia (PRD 6).
- No pasa titulos a Claude. Si algun dia Claude clasifica titulares, sera como dato entrecomillado
  y solo si los datos dicen que mejora a las reglas (decision del propietario del 22/09).
- No bloquea el bot si la fuente cae (avisa); lo que si hace es mantener las flags ya vistas.
- **Eventos macro (FOMC, IPC ±30 min):** el informe los lista como filtro, el PRD no. No entran aqui;
  seria otra decision.

## 8. Criterio de avance de la pieza

Servicio estable 1 semana sin huecos (juez), todos los tests en verde, las dos carteras con el
filtro enchufado DE VERDAD (comprobar que alguien lo llama en el camino que corre, no solo en sus
tests: el patron que mas ha costado).

## 9. Decisiones del propietario (25/09/2026)

**1. Que fuentes al principio.**
- a) **Solo los anuncios de OKX** (recomendado): precision medida (0 falsas alarmas en 3,5 anyos)
  y cubren lo que mas puede pasar en la UE (deslistados por MiCA, migraciones). Los medios, en la
  etapa 2 y en sombra.
- b) OKX y medios a la vez desde el principio.

**2. Que hace una flag CRITICA con una posicion abierta.**
- a) **Salir a mercado** (recomendado): lo pide el PRD 5 literalmente.
- b) Solo bloquear entradas y dejar que la OCO haga su trabajo.

**3. El deslistado no caduca solo; lo quita el propietario a mano** (recomendado), porque detras hay que
cambiar la whitelist y la clave de OKX (quinto punto de la regla 3). Alternativa: caducar a los
30 dias.

**DECIDIDO (el propietario, 25/09), a su manera:** que AVISE para enterarse, y despues del aviso se decide que
hacer. O sea: al verlo, el bot bloquea la moneda y, si hay posicion, vende a mercado (decision 2);
manda un Telegram con el anuncio y su enlace; la flag NO caduca sola y el resumen diario lo recuerda
mientras siga pendiente. El propietario decide despues: quitar la moneda (whitelist + clave de OKX) o levantar
la flag si era una falsa alarma. **Confirmado por el propietario (25/09): primero vende, despues avisa.**

**4. Las duraciones de la tabla de la seccion 3** (72 h, 7 dias, 24 h). Son de sentido comun, no
medidas: hay pocos casos reales para medirlas. Van en `settings.yaml`, cambiables sin tocar codigo.
