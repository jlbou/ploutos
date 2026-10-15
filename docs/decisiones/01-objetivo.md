# Decision 1: el objetivo de Ploutos (15/10/2026)

Paso 1 del replanteamiento (`docs/inventario-1510.md`), como en el otro bot del propietario: una decision por
mensaje, con opciones y la recomendada marcada. Sustituye el objetivo del PRD v2 (seccion 1: "la rentabilidad es
secundaria") y el del PRD v3 archivado.

## Decidido

- **Objetivo: ganar dinero (opcion a).** Una estrategia pasa si **gana mas que mantener BTC**, o **gana lo mismo con
  una caida claramente menor**, siempre **neto de comisiones e impuestos**.
- **Construido para escalar (anyadido del propietario):** nada se disenya a partir de los 50 $ (o su equivalente en euros). Lo que importa es
  demostrar que la estrategia funciona para poder ponerle mas capital despues; el bot, sus reglas y sus estudios tienen
  que valer igual con 50 $ que con mucho mas.

- **Todo se mide en EUROS (opcion b, anyadido del propietario):** resultados, listones, el BTC de referencia (tambien en
  euros) y los estudios, con el cambio EUR/USD de cada dia. Mientras se opere contra USDC, el cambio euro/dolar entra
  en los resultados (es lo que de verdad se gana o se pierde). **Ademas se estudia operar contra euros** (pares X/EUR,
  sin el riesgo del cambio) en la decision 3 (mercado): sin comprobar que OKX EU los tenga para las 8 monedas, ni con
  que liquidez y spread; cambiaria la regla 3 ("solo X/USDC").

## Por que

- Con 50 $, ganar dinero en euros es casi nada (+20 % al anyo son 10 $): el valor esta en demostrar la estrategia.
- Mantener BTC ya lo hace cualquiera sin bot: el bot solo vale si mejora eso, en rendimiento o en riesgo.
- El metodo necesita una linea de aprobado escrita antes de medir; sin ella, cualquier resultado se lee a conveniencia.
- Lo que dicen los datos y la literatura (`docs/estudios/recerca-trading-cripto.md`): seguir la tendencia en cripto
  spot sobre todo cae menos; ganar mas que BTC es un liston alto. Por eso cuenta tambien "lo mismo con menos caida".

## Lo que implica "construido para escalar" (a revisar en las decisiones siguientes)

- **Las reglas en importes fijos pasan a porcentajes del capital:** el suelo (25 $), el limite diario (3 $), los
  escalones (45/40/35 $), el colchon de la regla 8 (1 $) y el tope por posicion (20 $). Los numeros de hoy salen de
  50 $; con otro capital no significarian lo mismo.
- **Los costes que con 50 € no pesan, con mas capital si:** el deslizamiento y la profundidad del libro (hoy "nunca
  ata con 15 $"), y las comisiones por nivel de volumen de OKX.
- **Los minimos por orden** (`minSz`, BTC ~8,6 $) dejan de mandar con mas capital: las salidas parciales serian
  posibles.
- **Los estudios se miden en porcentaje** (rendimiento, caida, Sharpe), no en dolares, y con los costes del tamanyo
  al que se quiera llegar.
- **El paso a mas capital** necesita su propio criterio, escrito antes (cuanto, cuando y con que pruebas).

## Lo que queda abierto

- **Que es "claramente menor"** en la caida, **como se cuentan los impuestos** y **contra que BTC** (mantenido desde el
  mismo dia, con sus comisiones): se fija en el paso 2, en el criterio del estudio, antes de medir.
- **El capital inicial y como se escala:** la decision 2.
