# Medios de comunicacion como fuente de noticias, EN SOMBRA

Decision del propietario del 07/10/2026 (opcion A): **empezar ya a recoger** titulares de medios de cripto, en sombra, "cuantos
mas mitjans millor". Antes (25/09 y 28/09) estaba previsto proponerlo tras el veredicto de la fase 6; se adelanta SOLO
la recogida, que no toca nada de lo que decide el bot.

## 1. Que es y que NO es

- **Es:** un servicio aparte, `ploutos-medios`, que cada 10 min lee los RSS de 24 medios y guarda los titulares en su
  propia base (`var/ploutos-medios.db`). Nada mas.
- **NO entra en ninguna decision.** Ninguna cartera, ni el ejecutor, ni la IA leen esa base (hay un test). La huella
  del camino no cambia: la muestra de la fase 6 sigue igual.
- **NO manda nada por Telegram.** En sombra no se avisa: los titulares son texto no confiable y aqui no hace falta
  ensenyarlos a nadie.
- **NO es una senyal de compra** (PRD 6): si algun dia entra, sera como filtro de riesgo, igual que los anuncios de OKX.
- **La IA no lee los titulares** (decision F del 22/09). **Excepcion desde el 11/10 (el propietario):** el embudo de noticias
  de L, en sombra (`docs/diseno-embudo-noticias.md`): la IA lee los titulares de los casos ya confirmados y da el
  veredicto final. El juicio de esta seccion 3 no cambia (sigue con el clasificador tal cual). Se clasifican con el clasificador de palabras clave que ya
  usan los anuncios de OKX (`features/news.py`), TAL CUAL, sin ajustarlo a los medios (ajustarlo despues de ver los
  datos seria hacer trampa con el criterio).

## 2. Las fuentes (comprobadas el 07/10: las 24 responden)

Gratuitas, sin clave, por RSS. Se guarda la fuente de cada titular y una etiqueta de calidad puesta ANTES de mirar:

| Calidad | Medios |
|---|---|
| A (redaccion propia, referencia) | CoinDesk, Cointelegraph, The Block, Decrypt, Blockworks, DL News, Protos, Rekt (hackeos), The Defiant, Bitcoin Magazine, CryptoSlate, SEC (notas de prensa) |
| B (agregadores, mucho titular de precio) | NewsBTC, Bitcoinist, CryptoPotato, U.Today, BeInCrypto, Crypto Briefing, CoinJournal, AMBCrypto, The Daily Hodl, CoinGape, Cryptonews, Watcher.Guru |

Descartadas por no ser gratuitas o no servir (comprobado el 07/10): CryptoPanic (sin plan gratuito desde el 01/04/2026),
CoinDesk Data (sin plan gratuito desde el 21/05/2026), NewsAPI.org (el gratuito es solo para desarrollo), GDELT
(rechazo la primera peticion con un 429).

**Seguridad:** el XML de un RSS es texto de fuera. Se rechaza cualquier documento con `<!DOCTYPE` o `<!ENTITY` (las
bombas de entidades que tumbarian la memoria del VPS), mas de 2 MB o mal formado; los titulos se guardan como texto
plano, recortados a 300 caracteres, y nunca se ejecutan ni van a la IA.

## 3. Como se juzgara si sirven (fijado ANTES de tener ningun dato, 07/10)

**Cuando:** una sola vez, tras el veredicto de la fase 6 y con al menos 8 semanas de recogida. Antes, solo se mira que
la recogida funcione (cuantos titulares y de que fuentes), nunca que habrian bloqueado.

**La unidad:** cada CANDIDATO de las dos carteras (`paper_decisions`, `kind = 'candidate'`, tambien los de sombra). Un
candidato esta "bloqueado en sombra" si, en la vela en que se decidio, su moneda tenia una flag activa derivada de los
titulares de medios (`features.news.flags`, las mismas duraciones que los anuncios de OKX: 72 h un incidente o una
suspension, 7 dias una migracion, 24 h la volatilidad; un deslistado "de medios" cuenta 72 h, porque no hay quien lo
levante). Su resultado: el R contrafactual de la fase 6 (`portfolio.comparacion.resolver`, horizonte de 42 velas, el
objetivo como lo cobre el papel en esa fecha).

**Pasa** si se cumplen las tres:
1. al menos **20 candidatos bloqueados** en sombra;
2. el R medio de los bloqueados MENOS el de los no bloqueados, con su intervalo del 90 % (bootstrap por dias), **entero
   por debajo de 0** (los que habria bloqueado eran peores);
3. no habria bloqueado mas del **30 %** de los candidatos (si no, no filtra: deja de operar).

Se juzga con TODAS las fuentes juntas. Por calidad (A y B) y por fuente, solo como informacion: elegir despues la
combinacion que mejor sale seria buscar hasta encontrar algo.

**Si pasa:** se lleva al propietario como propuesta (entraria como filtro en las DOS carteras a la vez, con su propio tramo de la
muestra). **Si no pasa** (lo mas probable con ~0,5 candidatos al dia: 20 bloqueados pueden tardar mucho), se sigue
recogiendo o se para, decide el propietario. **Contado antes de empezar:** con 0,5 candidatos/dia, en 8 semanas hay ~28; que 20
caigan en una ventana de flag es improbable. La recogida sirve igual para ver cuanto ruido mete cada medio.

## 4. Las piezas

| Pieza | Que |
|---|---|
| `data/medios/rss.py` | las 24 fuentes, leer RSS y Atom (sin red en los tests), rechazar lo peligroso, nunca lanza |
| `data/medios/store.py` + `data/store/medios_migrations/` | la base: titulares (unicos por fuente y guid) y lecturas por fuente |
| `scripts/run_medios.py` | el servicio (cada 10 min), `--una-vez`, `--status` (por fuente: ultima lectura buena, cuantos; y las flags en sombra activas) |
| `deploy/ploutos-medios.service` | `MemoryMax=200M`, solo escribe en `var/`, sin Telegram |
| Copias y vigilante | la septima base en `backup.sh`, `verify_backups.py` y `daily-backup.ps1`; latido a Healthchecks si el propietario crea `HEALTHCHECK_MEDIOS` (sin ella, no late) |
| Test de arquitectura | ningun modulo que decide importa `data.medios` ni abre `ploutos-medios.db` |
