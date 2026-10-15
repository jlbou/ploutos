# Inventario de Ploutos (15/10/2026): que se queda, que se reaprovecha, que se descarta, que se limpia

Paso 0 del plan aprobado por el propietario el 15/10 (opcion a): inventario y limpieza; despues, las decisiones de fondo otra vez
(paso 1, como en Ebisu); despues, un estudio profundo (paso 2); y solo si una estrategia pasa, construir (paso 3).
**Nada se borra ni se para sin el OK del propietario, decision a decision.** Mientras tanto el VPS sigue solo, en silencio.

La pregunta que ordena todo: **¿esto sirve sea cual sea la estrategia que salga del paso 2?** Si si, se queda. Si
solo servia a una estrategia que ya sabemos que pierde, se descarta. Lo que no esta claro, se reaprovecha adaptado.

## 1. Lo que hay (medido el 15/10)

| Pieza | Ficheros | Lineas | Que es |
|---|---|---|---|
| `core/` | 8 | 1.286 | modos, reloj, logging, secretos, salud |
| `data/` | 32 | 2.904 | ingesta WS/REST, base, validacion, USDC, noticias, medios |
| `features/` | 6 | 1.073 | indicadores, regimen, correlaciones, paridad, noticias |
| `strategy/` | 11 | 2.137 | costes, filtros, **los 3 setups**, candidatos, baseline |
| `ai/` | 12 | 1.540 | el analista (contrato, parser, presupuesto, decisor) y el clasificador del embudo |
| `risk/` | 8 | 1.548 | las 19 reglas, sizing, limites, equity |
| `execution/` | 16 | 2.798 | ordenes, OCO, conciliacion, ejecutor del demo |
| `portfolio/` | 7 | 3.036 | simulador de papel, bucle, juez |
| `notify/` | 8 | 1.319 | Telegram, comandos, latidos |
| `api/` + `ui/` | 21 | 2.805 | el panel |
| `scripts/` | 39 | 8.554 | servicios, jueces, verificaciones |
| `deploy/` | 35 | 2.287 | systemd, instalacion, copias, sync |
| `tests/` | 101 | 28.373 | 1.674 tests |
| `docs/` | 48 + estudios | | PRD, disenyos, cierres, propuestas, estudios |

**En el VPS** (15/10 16:00 UTC; 1,2 de 2 GB de memoria usada, disco 15 %, `var/` 493 MB): 8 servicios en marcha
(`ingest`, `paper`, `paper-ai`, `news`, `medios`, `telegram`, `panel`, `exec`) y 5 temporizadores (`embudo`,
`papel-l`, `jueces`, `backup`, `actualizaciones`).

**Ramas sin desplegar:** `revision-1510-b` (15/10), `objetivo-taker` (07/10), `sombra-log` (07/10).

## 2. Se queda tal cual (sirve para cualquier estrategia)

Lo que se hizo despacio, por fases, con criterio escrito y jueces. Es la base.

- **Las 19 reglas y el motor de riesgo** (`risk/`): tests primero, mutacion 16/16, dos sitios por regla.
- **Ingesta y datos** (`data/` salvo medios): velas cerradas, validacion, huecos, paridad de USDC.
- **Ejecucion en OKX** (`execution/`): OCO en el exchange con `tdMode: cash`, conciliacion, `clOrdId`, redondeos al
  lado seguro. Probada 7 dias en el demo (fase 4 cerrada). Todo lo verificado de OKX (`docs/hallazgos-*.md`).
- **Telegram, latidos y Healthchecks** (`notify/`), **copias y restauracion** (`deploy/`), el simulacro del 06/10.
- **Los jueces de cada noche** como mecanismo (que criterio juzgan, depende de la estrategia).
- **Las trampas aprendidas** (`CLAUDE.md` "Trampas"): WAL, `set -e`, CRLF, IPv6, `needrestart`...

## 3. Se reaprovecha adaptado

- **El simulador de papel** (`portfolio/paper.py`) y su juez (`portfolio/audit.py`): con las 7 suposiciones (la 7, en
  `revision-1510-b`). Es la base de la prueba de oro.
- **El simulador de los estudios** (`docs/estudios/tendencia/tendencia.py`) y `scripts/papel_l.py --validar`: el
  unico sitio donde hoy ya se comprueba "papel = medicion".
- **Costes y filtros** (`strategy/costes`, filtros de spread y de 3x el coste): valen para cualquier estrategia.
- **Noticias de OKX** (`ploutos-news`): el deslistado y la suspension importan siempre.
- **El panel** (`api/`, `ui/`): la estructura se queda; las tarjetas, segun la estrategia. **Con un hueco de seguridad
  pendiente** (S5 de Ebisu: DNS rebinding en `api/mando.py`; ver 5).
- **La IA**: el contrato, el parser y el presupuesto (`ai/`) son reutilizables; **que papel tiene la IA** se decide
  otra vez en el paso 1.

## 4. Candidato a descartar (solo servia a estrategias que ya sabemos que pierden)

- **Los 3 setups de 4 h** (`strategy/setups`: pullback, ruptura, reversion) y el baseline: pierden en el anyo USDC
  (-0,38 R); la reversion pierde siempre.
- **Las dos carteras de la fase 6** (`ploutos-paper`, `ploutos-paper-ai`) y la pregunta "¿aporta la IA eligiendo
  entre esos setups?". El veredicto llega del 16/10 al 20/11; el dossier recomendaba retirarlas despues.
- **El ejecutor del demo** (`ploutos-exec`): espeja la cartera de la IA. Sirvio para cerrar la fase 4; el dossier
  recomendaba retirarlo con el veredicto.
- **Las ramas `objetivo-taker` y `sombra-log`**: arreglos para esas carteras.
- **La sombra M1 y los candidatos en sombra**; `learning/` (vacio; la fase 8 era para la IA de los setups).
- **El PRD v3** (aprobado con prisa el 11/10): lo sustituye lo que salga del paso 1. Queda como historia.

## 5. Se limpia

- **El hueco S5 del panel** (DNS rebinding): arreglarlo como en Ebisu, que el panel solo responda si la cabecera `Host`
  es la suya. Es seguridad: no depende de la estrategia.
- **Los nombres de Healthchecks** (renombrados el 15/10 desde Ebisu): la documentacion aun usa los antiguos.
- **Documentos:** 48 en `docs/`, muchos son propuestas ya decididas o superadas. Moverlos a `docs/archivo/` (sin
  borrar) y dejar en `docs/` solo lo vigente.
- **`CLAUDE.md`**: rehacerlo corto, con la base, lo verificado y las trampas; lo de la estrategia, cuando salga.
- **`docs/estudios/`** se queda entero: es el registro de los ~35 intentos (cuentan para el liston).

## 6. Lo que sigue en marcha mientras tanto

- **El papel de L** (12/10/2026-11/01/2027): no cuesta nada y son datos limpios hacia adelante.
- **El embudo de noticias** y los medios en sombra: igual.
- Lo de la fase 6 y el demo, segun la decision 1.

## 7. Decisiones del paso 0 (una por mensaje)

1. Las carteras de la fase 6 y el demo: **retiradas el 15/10 (el propietario, b)**, `docs/cierre-fase-6.md`.
2. El hueco S5 del panel: **se arregla en el paso 3, al rehacer el panel (el propietario, b)**. Hoy casi no tiene efecto (los
   controles ya no mandan sobre ninguna cartera); antes de cualquier dinero real, tiene que estar arreglado.
3. Las ramas: **`revision-1510-b` juntada en `main` el 15/10 (el propietario, a; 1679 tests, mutacion 16/16)**;
   `objetivo-taker` y `sombra-log`, archivadas como etiquetas `archivo/...` y borradas. El objetivo cobrado taker se
   rehace en el paso 3, con el simulador de la estrategia nueva.
4. Los setups, el baseline y lo que solo les servia: **no se borra nada ahora (el propietario, a)**; el codigo de hoy queda en la
   etiqueta `archivo/antes-de-limpiar` y la limpieza se hace en el paso 3, cuando se sepa que necesita la estrategia nueva.
5. La limpieza: **hecha el 15/10 (el propietario, a)**: 30 documentos a `docs/archivo/` (sin borrar; enlaces actualizados),
   `CLAUDE.md` corto y pensado para un repositorio publico (el anterior, en `docs/archivo/claude-md-1510.md`); lo
   personal, en `CLAUDE.local.md` (fuera de git).

**Paso 0 cerrado el 15/10.** Extra (el propietario, 15/10): el repositorio pasa a llamarse `ploutos` y se construye para ser
publico; se publica cuando este preparado (falta decidir como se limpia lo de antes).
