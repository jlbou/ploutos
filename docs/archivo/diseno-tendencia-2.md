# Tendencia, segunda tanda: variantes nuevas y prueba conjunta (APROBADA por el propietario el 10/10, antes de medir)

Preparada el 10/10/2026 a peticion del propietario ("intentem trobar una variant de H o 2+D barrejant-les entre elles o amb F,
o intentem crear una nova estrategia amb aquesta nova informacio. Despres fem la prova de totes a la vegada").
**Estado: APROBADA por el propietario el 10/10, ANTES de medir.** Sus tres respuestas:
1. **La exploracion se queda hasta el 20/08/2025** (con la reserva gastada) y **el anyo USDC se guarda como la reserva
   nueva** (la prueba final). Se planteo ampliar la exploracion hasta 09/2026 y el propietario dijo que no.
2. **Sharpe deflactado: opcion b** (sirve para ELEGIR la que va al anyo USDC, no para eliminar).
3. **Las variantes K, L y M, aprobadas tal cual.**

**Resultado en la exploracion ampliada (10/10, `docs/estudios/tendencia/README.md`): PASAN L y M; va al anyo USDC L**
(50 -> 421 $, caida 44,5 %, Sharpe 1,46, 2022 -11 %, tramo de la reserva +30,5 %, deflactado 0,978). H, 2 + D y K
no pasan. Aviso: buena parte de L viene de 12/2020-05/2021.

## 00. La prueba del anyo USDC: DECISION del propietario (10/10), ANTES de ver nada de ese anyo

el propietario ("Si a tot"), despues del veredicto de la exploracion ampliada:
- **Periodo:** del lunes **01/09/2025** a las 00:00 al 28/09/2026 00:00 UTC (un mes mas que el 06/10/2025 fijado el 09/10).
- **Calentamiento (opcion b):** las medias (20-200 dias), el ATR diario y la correlacion se calientan con las velas USDT
  de la exploracion ampliada anteriores al 21/08/2025 (desde el 01/12/2024); desde el 21/08/2025, las de USDC
  (`time-stop/historia.db`). Asi ninguna media cuenta como "cumplida sin datos". Las decisiones empiezan el 01/09/2025.
- **Cuentan L y M** (las dos que pasaron), con el orden fijado ahora:
  - pasa L -> **L es la estrategia** (aunque M tambien pase);
  - L no pasa y M si -> **M es la estrategia**, con una prueba algo mas floja (se dice);
  - no pasa ninguna -> no se retoca nada y se replantea.
- H, 2 + D y K se miden alli solo como informacion.
- **Pasa si:** rendimiento >= 0 Y caida maxima <= 2/3 de la de BTC mantenido en el mismo periodo (lo del 09/10).

**Resultado del anyo USDC (10/10): NO PASA NINGUNA de las dos** (L -6,9 %, caida 20,5 %; M -0,02 %, caida 13,0 %;
BTC -22,3 %, caida 53,1 %). No se retoca nada. 2 + D (+3,1 %) pasa solo como informacion.

## 1. De donde sale

- **Lo medido** (`docs/archivo/diseno-tendencia.md`, `docs/estudios/tendencia/README.md`): H (BTC + ETH con el filtro de
  200 dias) protege en 2022 pero llega tarde; 2 + D cae poco (17 %) pero gana poco (posiciones de ~15 $); F se ajusto
  a un plazo (28 dias) y a un anyo (2021) y fallo en la reserva.
- **La investigacion** (`docs/estudios/recerca-trading-cripto.md`, seccion 5): lo unico con evidencia es seguir el
  precio (media movil, maximos), sirve sobre todo para caer menos, y **juntar varios plazos** en vez de uno reduce la
  dependencia de haber acertado el plazo (Zarattini, Pagani y Barbon 2025).
- **Las variantes nuevas salen de la literatura, no de mirar nuestras curvas:** los plazos (20, 50, 100 y 200 dias)
  son los clasicos, no se buscan.

## 2. Las variantes (lista CERRADA; una configuracion cada una; no se retocan)

**K. H con varios plazos (la "H multiplazo").** BTC y ETH, cada una con SU propia tendencia (no solo la de BTC). Cada
dia a las 00:00 UTC, con el cierre del dia anterior, para cada moneda se cuentan cuantas de estas cuatro se cumplen:
cierre por encima de su media de 20, 50, 100 y 200 dias.
- 4 de 4: la moneda al 45 % del equity; 2 o 3: al 22,5 %; 0 o 1: fuera (en USDC).
- Solo se compra o vende cuando cambia el nivel (menos comisiones). Si el ajuste queda por debajo del minimo por orden
  de OKX, no se hace (con 50 $, la mitad de una posicion son ~11 $, por encima del minimo de BTC, ~8,6 $).
- Mas rapida que H para entrar y salir (las medias cortas reaccionan antes) y sin depender de un solo plazo.

**L. F con varios plazos (la rotacion arreglada).** Las 8 monedas, cada lunes como F. Una moneda puede entrar solo si
cumple las CUATRO (cierre sobre su media de 20, 50, 100 y 200 dias) Y BTC cumple al menos dos. De las que pueden, se
toman hasta 3, primero las que mas por encima estan de sus medias (la media de las cuatro distancias), con la regla 15.
Las que ya se tienen y siguen pudiendo se mantienen. 30 % del equity cada una, como F.
- Es la idea de F (las monedas mas fuertes) sin su punto debil: ni un solo plazo ni rendimiento de 28 dias.

**M. Mitad K, mitad 2 + D.** El capital en dos partes iguales, cada una con sus reglas, sin rebalancear entre ellas;
como J, con las curvas medidas sumadas (misma aproximacion, dicha: las reglas que no escalan no se aplican a la suma).
- Junta la que protege por tendencia (K) con la que opera setups y cae poco (2 + D).

**Y las dos que ya teniamos, para comparar en el mismo escenario: H y 2 + D, tal cual.**

**Detalle fijado antes de medir (10/10, como H):** una media sin dias suficientes (200 dias hasta mayo de 2021) cuenta
como cumplida.

Comun a K y L (como F y H): comisiones taker en todo; stop a 3 ATR diarios bajo la entrada y objetivo a +100 % en el
exchange (regla 13); tras un stop, la moneda no vuelve en 7 dias; las mismas reglas duras simuladas que F y H (4, 7, 8,
9, 10, 12 nueva al 5 %, 15, 16).

## 3. Los datos: la exploracion ampliada con la reserva

La reserva ya se gasto con F (09/10): pasa a ser exploracion. **Exploracion ampliada: USDT del 14/12/2020 al
20/08/2025 (4,7 anyos)**, juntando `exploracion.db` y `reserva.db` (las velas que se solapan, 05-06/2024, son las
mismas). Se ensenya ademas el tramo 07/2024-08/2025 por separado, que es donde fallo F.

**La unica prueba limpia que queda es el anyo USDC** (`time-stop/historia.db`, del lunes 06/10/2025 al 28/09/2026).

## 4. El criterio en la exploracion ampliada (cada variante)

1. Gana dinero: rendimiento neto > 0.
2. Cae mucho menos: caida maxima <= 2/3 de la de BTC mantenido.
3. Mejor por riesgo: Sharpe >= el de BTC mantenido.
4. Aguanta el anyo bajista: en 2022 pierde como mucho 1/3 de lo que pierde BTC.
5. **Nueva: no se viene abajo en el tramo de la reserva** (07/2024-08/2025): rendimiento > 0.
6. **Sharpe deflactado** con N = 10 (la familia de 6, J y las tres nuevas), la V de `umbral.json`. **Dos opciones para
   el propietario (ver seccion 6).**

**De las que pasen, UNA sola va al anyo USDC: la de mayor Sharpe deflactado.** Si no pasa ninguna, no se retoca nada.

## 5. "La prueba de todas a la vez", y por que decide solo una

En el anyo USDC se miden **todas** a la vez (H, 2 + D, K, L, M) y se ensenyan todas. Pero **la que decide es la que se
eligio ANTES** con la exploracion. Motivo: si se prueban cinco y nos quedamos con la que salga mejor, volvemos a elegir
por suerte (lo que le paso a F con 27 variantes). Las otras cuatro son informacion, no aprobacion.

**Pasa el anyo USDC si:** no pierde (>= 0) y su caida maxima <= 2/3 de la de BTC mantenido (lo ya fijado el 09/10).
**Lo que hay que saber antes:** ese anyo BTC estuvo mas de 9 meses bajo su media de 200 dias (dato publico, no medido
aqui); una estrategia de tendencia estara mucho tiempo en USDC, asi que pasar significa sobre todo "protege y no hace
dano", no "gana mucho".

**Si pasa:** papel hacia adelante unos meses (despues del veredicto de la fase 6, para no tocar su muestra) y despues,
decision del propietario sobre el dinero real.

## 6. La decision que hay que tomar antes: que hace el Sharpe deflactado

Ninguna estrategia realista lo ha pasado con 3,5 anyos (todas entre 0,84 y 0,94; hace falta 0,95).
- **a) Que siga siendo eliminatorio (>= 0,95)**, como hasta ahora. Lo mas estricto; probablemente no pase ninguna.
- **b) Que sirva para ELEGIR, no para eliminar** (recomendada): las condiciones 1-5 eliminan; de las que pasan, va al
  anyo USDC la de mayor deflactado. El argumento: el deflactado sirve para no fiarse de la mejor de muchas pruebas; esa
  desconfianza la cubre la prueba limpia que viene detras (el anyo USDC y despues el papel), que es la que decide.
  El riesgo: es menos exigente, y el anyo USDC es una prueba mas floja que la reserva (un anyo, mayormente bajista).

## 7. Coste

Juntar las bases y anyadir K y L al simulador (`tendencia.py`), con su validacion: ~medio dia. Medir 2 + D en la
exploracion ampliada (el recorrido entero del bot): ~1-2 h. El juez y el anyo USDC: ~2 h. Sin tocar el bot.
