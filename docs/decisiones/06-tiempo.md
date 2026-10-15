# Decision 6: el tiempo del propietario y lo que hace el bot solo (15/10/2026)

## Decidido (opcion a)

- **Mientras se construye: sin ritmo fijo.** Se avanza decision a decision, sin prisa.
- **Cuando funcione: totalmente autonomo.** El propietario no hace nada en el dia a dia: recibe avisos SOLO si algo va
  mal y un resumen corto cada semana.
- **Las decisiones de dinero son siempre suyas:** poner mas, retirar, parar o volver a arrancar.

## Por que

- Es lo que ya decia el PRD v2 ("100 % autonomo") y lo que el propietario eligio en su otro bot.
- Un bot que pide aprobar cada operacion llega tarde cuando no hay nadie, y deja de ser medible contra el simulador.

## Lo que implica

- Lo que ya existe sirve: avisos de Telegram solo si algo falla, jueces cada noche, Healthchecks, pausa y parada desde
  Telegram. Falta el **resumen semanal** (se disenya con el bot, en el paso 3).
