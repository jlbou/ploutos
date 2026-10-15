# L en papel hacia adelante (APROBADA por el propietario el 10/10, antes de construirlo)

Preparada el 10/10/2026 a peticion del propietario ("prepara el disseny de L. Explica'm quins son els passos a seguir i totes
les opcions que tenim"). **Estado: APROBADA por el propietario el 10/10** ("Aprovo totes les teves recomanacions pero trobo que 6 mesos es molt de
temps, i entenc que em seguira avisant quan faci una operacio"). Lo decidido:
- 2.1 a (rehacer L cada noche con el simulador validado), 2.2 a (VPS), 2.3 a (lunes 12/10/2026 00:00 UTC), 2.6 a
  (L sola, sin la IA), corte anticipado al 25 %.
- **2.4: 3 meses, hasta el lunes 11/01/2027 00:00 UTC** (el propietario: 6 meses es mucho).
- **2.5: Telegram con CADA operacion** (compras y ventas de los lunes, y stops u objetivos entre semana), en el
  mensaje de la noche siguiente (el papel se rehace cada noche: el aviso llega con hasta un dia de retraso).

## 0. De donde sale y que se sabe

- **L** (`docs/archivo/diseno-tendencia-2.md`): cada lunes, de las 8 monedas, hasta 3 que esten por encima de sus medias de
  20, 50, 100 y 200 dias, si BTC lo esta en al menos 2; las mas por encima primero; 30 % del equity cada una; stop a
  3 ATR diarios y objetivo a +100 % en el exchange; las reglas duras simuladas.
- **Lo medido:** exploracion ampliada 12/2020-08/2025, 50 -> 421 $, caida 44,5 %, deflactado 0,978 (pasa); **anyo
  USDC 09/2025-09/2026: -6,9 % con BTC en -22,3 % y caida 20,5 % frente a 53 %: no pasa** (pierde). Buena parte de su
  ganancia historica viene de 12/2020-05/2021.
- **Lo que significa el papel:** L **no ha pasado** el criterio fijado. El papel no es "la prueba que le falta para
  el dinero real": es seguirla con datos que nadie ha visto, sin riesgo, para decidir con mas informacion. Opera poco
  (13 operaciones en el anyo USDC): unos meses de papel dicen poco en estadistica; dicen si se comporta como en la
  simulacion y si hay sorpresas.

## 1. Los pasos

1. **el propietario aprueba este disenyo** (las opciones de la seccion 2), con el criterio de la seccion 3. Se sube antes de
   arrancar.
2. **Construir el papel de L** (~medio dia): un script que rehace L cada dia con los precios reales y un juez.
   Validacion antes de arrancar: con los datos ya conocidos tiene que dar EXACTO lo del anyo USDC (`L-usdc.json`).
3. **Desplegar en el VPS** (sin parar ni reiniciar nada de lo que corre; solo un temporizador nuevo).
4. **Arranca el lunes elegido** (2.3) y corre el tiempo elegido (2.4). Las dos carteras de la fase 6 y el demo no se
   tocan: la muestra de la fase 6 no se parte (huella `f063d80147a9`).
5. **Al final, el juez** dice si cumple el criterio. **el propietario decide** que hacer (seccion 4).

## 2. Las opciones (con la recomendada)

**2.1 Como se hace el papel**
- **a) Rehacerlo cada dia con el simulador ya validado (recomendada).** Cada noche, el mismo `tendencia.py` que se
  midio corre L desde el lunes de inicio hasta hoy con los precios reales que ya recoge la ingesta. Sin estado propio
  (todo sale de las velas guardadas), sin claves, sin ordenes; si el VPS se reinicia no se pierde nada. Lo que se
  mira es exactamente lo que se midio.
- b) Un servicio nuevo como `ploutos-paper`, con su libro y el motor de riesgo del bot. Prepara el camino al dinero
  real, pero son varios dias de trabajo y otra pieza que vigilar, para algo que quiza no pase. Mejor despues, si pasa.

**2.2 Donde**
- **a) En el VPS (recomendada):** ahi estan los precios en vivo y corre aunque el portatil este apagado.
  Historia: `time-stop/historia.db` (USDC desde el 21/08/2025; se copia una vez al VPS, solo 1 h y 4 h) + la ingesta.
- b) En el portatil, con la copia diaria: se retrasa un dia y depende de que el portatil se encienda.

**2.3 Cuando empieza**
- **a) El lunes 12/10/2026 a las 00:00 UTC (recomendada)**, si el propietario aprueba hoy o manyana; si no, el lunes siguiente.
  L decide los lunes, asi que siempre empieza en lunes.

**2.4 Cuanto dura**
- a) 3 meses (hasta el lunes 11/01/2027): ~3-5 operaciones; dice poco.
- **b) 6 meses (hasta el lunes 12/04/2027) (recomendada):** ~6-10 operaciones y, probablemente, algun cambio de
  mercado. Con una revision a los 3 meses (solo mirar, no decidir).
- c) Sin fecha: hasta que el propietario decida. Facil, pero sin criterio de final no hay juez.

**2.5 Avisos**
- a) Ninguno: solo el panel/los ficheros y lo que se le cuente al propietario.
- **b) Telegram los lunes, solo si L cambia algo (recomendada):** "El papel de L compra X / vende Y; equity Z $". En
  castellano, sin nombrar a la IA (no participa).
- c) Telegram cada lunes, cambie o no.

**2.6 La IA**
- **a) L sola, sin la IA (recomendada):** es lo que se midio. La IA sigue en lo suyo (la fase 6).
- b) Con la IA como filtro de noticias (solo puede reducir o vetar, PRD 6): seria otra cosa que no se ha medido; si
  algun dia, como prueba aparte.

## 3. El criterio (fijado antes de arrancar)

**Juez automatico** (`check_papel_l.py`, con los jueces de cada noche; Telegram solo si FALLA el punto 1):
1. **Datos completos:** sin huecos en las velas de 4 h de las 8 monedas en el periodo (con huecos, el papel no vale y
   se dice; no se rellena a mano).
2. **Al final del periodo, pasa si:** rendimiento >= 0 **Y** caida maxima <= 2/3 de la de BTC mantenido en el mismo
   periodo (el mismo criterio que el anyo USDC).
3. **Corte anticipado (para dejar de seguirla, no por dinero):** si en cualquier momento cae mas del 25 % desde su
   maximo, se para el papel y se da por descartada. (Opciones: 20 %, **25 %** recomendada, o sin corte.)

**Nota de la revision del 15/10 (hallazgo 6; el propietario, opcion a):** la caida del criterio (puntos 2 y 3) se mide con el
equity al cierre de cada DIA, como se fijo antes de arrancar, y asi se queda: cambiarla a mitad seria mover la porteria.
Una caida dentro del dia que se recupera antes del cierre no cuenta. Desde el 15/10 se mide tambien, **solo como
informacion**, la caida con el cierre de cada vela de 4 h (la de L y la de BTC mantenido): sale en el juez, en el
panel y en el informe final, y no cambia el resultado. **Si L va al bot, alli el corte del 25 % se mide vela a vela
desde el principio.**

**Lo que se dice antes:** con tan pocas operaciones, pasar no demuestra que L gane dinero; demuestra que en esos
meses se comporto como se esperaba. La decision de ir al dinero real seguiria siendo del propietario, con todo esto delante.

## 4. Despues, segun el resultado

- **No pasa (o el corte salta):** L se descarta; no se retoca. Lo que queda: replantear el objetivo
  (`docs/archivo/decision-fase-7.md`).
- **Pasa:** el propietario decide si va al dinero real. Si dice que si, por este orden:
  1. **Aprobar el PRD v3** (`docs/archivo/propuesta-prd-v3.md`): la regla 12 (5 % por posicion), operar semanal en vez de
     setups de 4 h, el objetivo a +100 %. Son reglas duras: las decide el propietario.
  2. **Construir L en el bot** (la opcion 2.1 b: libro, motor de riesgo, ejecutor de ordenes semanales con su OCO).
  3. **Probar las ordenes en el demo** de OKX (solo tiene 5 de las 8 monedas: sirve para la mecanica, no para la
     estrategia).
  4. **Clave real** con las 8 monedas y USDC (regla 19: sin retirada, IP del VPS), puesta por el propietario.
  5. **50 $ reales**, con las 19 reglas y revision semanal (`docs/archivo/guion-fase-7.md`). No mas capital hasta meses de
     verdad.

## 5. Lo que no cambia mientras tanto

- La fase 6 sigue igual hasta su veredicto (~20/11); el baseline y la IA, sin tocar.
- La fase 4 se cierra hoy (10/10) si el juez da codigo 0.
- Nada de dinero real ni claves nuevas por esto.

## 6. Coste

Construir y validar el papel: ~medio dia. Desplegar: ~1 h (un temporizador nuevo, nada que reiniciar). Despues,
mirar el juez de cada noche.
