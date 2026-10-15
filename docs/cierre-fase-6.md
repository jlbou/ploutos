# Cierre de la fase 6 (15/10/2026): retirada SIN veredicto

**Decision del propietario (15/10, inventario `docs/inventario-1510.md`, decision 1, opcion b):** se retiran ya las dos
carteras de papel de la fase 6 (`ploutos-paper`, el baseline; `ploutos-paper-ai`, la IA) y el ejecutor del demo
(`ploutos-exec`), sin esperar al veredicto. En sus palabras: no tiene sentido mantenerlas para ver si la IA ayuda.

## Por que, y lo que NO se concluye

- La pregunta de la fase 6 era si la IA aporta eligiendo entre los 3 setups de 4 h. Esos setups **pierden** (el
  baseline, -0,38 R en el anyo USDC), asi que la respuesta ya no cambia nada.
- A 15/10 16:00 UTC: **5 discrepancias de las 30** del protocolo (`docs/archivo/protocolo-fase-6.md`), en 3 semanas y 6 velas
  decididas; al tope (20/11) habrian sido ~10: casi seguro "no concluyente".
- **No se concluye nada sobre la IA**: ni que aporta ni que no. Se abandona la pregunta; no se juzga.

## El estado al retirarlas (15/10, ultima vela procesada las 12:00 UTC)

| Pieza | Estado |
|---|---|
| Baseline (`ploutos-paper`) | modo NORMAL, sin posiciones ni pendientes, 6 operaciones cerradas |
| IA (`ploutos-paper-ai`) | modo NORMAL, sin posiciones ni pendientes, 7 operaciones cerradas |
| Demo (`ploutos-exec`) | modo NORMAL, sin posiciones, equity 49,13 $ (saldo virtual), conciliacion: cuadra |

## Que se hace

- Los tres servicios: `systemctl disable --now` (no arrancan solos). Sus unidades siguen en `deploy/` y sus bases en
  `var/`; la copia de cada noche las sigue copiando (no cambian).
- Los siete jueces que solo les servian salen de `scripts/jueces_diarios.py` (quedan cuatro: noticias, comandos de
  Telegram, papel de L y embudo). Los scripts siguen, para juzgar una copia si hace falta.
- El panel los ensenya como "Retirado" (no "Caido"), con sus ultimos datos.
- **Healthchecks (lo hace el propietario en su cuenta):** pausar o borrar las tres comprobaciones `HEALTHCHECK_PAPEL`,
  `HEALTHCHECK_PAPEL_IA` y `HEALTHCHECK_EJECUTOR`; si no, avisan de caida a los ~20 min.
- Las ramas `objetivo-taker` y `sombra-log` y la sombra M1: decision 3 del inventario.
