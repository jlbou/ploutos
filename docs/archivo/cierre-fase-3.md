# Cierre de la fase 3

**Estado: CERRADA el 02/10 (OK del propietario); resultados en la seccion 6.** Ensayo general hecho el 28/09 (5b): sin FALLA.
Redactado el 27/09/2026. La seccion "Resultados" se rellena el 02/10 con la salida de los comandos, tal
cual, sin resumir.

La convencion (CLAUDE.md): al terminar una fase, parar, ensenyar que hay, como se prueba y si se cumple
el criterio. No empezar la fase 4 sin el OK del propietario.

---

## 0. El guion del 02/10, en orden

| Hora (UTC) | Que | Donde |
|---|---|---|
| por la manyana | Mirar si los jueces de las 00:30 mandaron algo por Telegram (solo avisan si hay FALLA) | movil |
| desde ~12:05 | `check_fase3.py` (sin `--sin-papel`): las dos carteras cubren 7 dias cuando se procesa la vela de las 08:00 (cierra a las 12:00) | VPS |
| desde ~18:30 | `check_news.py` y `check_control.py`: 7 dias de servicio desde el despliegue (25/09 ~18:20) | VPS |
| el mismo dia | el propietario mira la cuota semanal en **Settings > Usage** (no hay API: es lo unico que no mide un juez) | el propietario |
| despues | Pegar las salidas en la seccion 6, tal cual, y el veredicto | aqui |
| con el propietario | Las decisiones de la seccion 5 | los dos |

**El codigo que se juzga:** el de `main`, desplegado. Durante la semana solo han cambiado piezas que
NO tocan el camino de decision (el tramo sigue siendo `f063d80147a9`): el panel, los jueces, el aviso de
arranque y la revision de actualizaciones. `check_fase6.py` lo comprueba: si el tramo se hubiera partido,
lo diria.

## 1. Los criterios, y como se comprueba cada uno

Juntando el PRD (12) y el informe (6), en `docs/archivo/plan-fase-3.md` seccion 5:

| # | Criterio | Juez | Que es FALLA |
|---|---|---|---|
| 1 | Una semana estable | `check_fase3.py` | una cartera atrasada, o una vela perdida por una parada (`skipped_stale`) |
| 2 | Cero salidas invalidas SIN controlar | `check_fase3.py` | una vela con candidatos y sin fila en el journal (excepcion del analista) |
| 3 | Consumo de cuota medido | `check_fase3.py` + el propietario | no es un veredicto: es la medida (llamadas, tokens, coste equivalente, latencia) y la cuota semanal |
| 4 | Juez de papel en verde para las DOS carteras | `check_paper.py` (lo lanza `check_fase3.py`) | cualquier FALLA del juez de papel |

Y los de la pieza de noticias y comandos, desplegada con la fase 3 (su criterio es el mismo dia):

| Pieza | Juez | Criterio |
|---|---|---|
| Noticias | `check_news.py --paper-db ... --paper-db ...` | 7 dias sin FALLA |
| Comandos | `check_control.py --paper-db ... --paper-db ...` | 7 dias sin FALLA |

```bash
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_fase3.py'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_fase6.py'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_news.py --paper-db var/ploutos-paper.db --paper-db var/ploutos-paper-ai.db'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_control.py --paper-db var/ploutos-paper.db --paper-db var/ploutos-paper-ai.db'
# Los reinicios: NRestarts no cuenta los de needrestart. Mirar CUANDO arranco cada servicio.
ssh ploutos 'for s in ploutos-ingest ploutos-paper ploutos-paper-ai ploutos-news ploutos-telegram ploutos-panel; do systemctl show $s -p ActiveEnterTimestamp -p MemoryPeak -p MemoryMax; done'
```

**Por que los jueces son de fiar:** cada uno tiene tests y se ha roto a proposito (mutacion): el de la
fase 3, 6/6 cambios en rojo. Y el simulacro de restauracion del 27/09 los paso todos sobre copias.

## 2. Que hay (desplegado desde el 25/09)

- `ploutos-paper-ai`: la IA como analista en sombra, en su servicio y con su base (decision 1 de la
  pieza 9), `MemoryMax` de 900 MB. Solo decide `open`/`skip` (decision D) con candidatos nuevos (B).
- `ploutos-paper`: el baseline, el grupo de control, sin IA (lo comprueba el juez de papel).
- `ploutos-news` y `ploutos-telegram`: los anuncios de OKX como filtro y los comandos.
- `ploutos-panel` (26/09): el panel por Tailscale, con controles.
- Latidos a Healthchecks (6), jueces cada noche (`ploutos-jueces.timer`, con `check_fase3.py` desde el
  26/09), copias cada noche de las cinco bases y la revision semanal de actualizaciones.

## 3. Lo que se encontro por el camino

1. **26/09, libexpat:** `needrestart` reinicio los servicios al actualizar la libreria. No costo ninguna
   vela: el bucle retoma desde su cursor. El aviso de "vuelta a arrancar" (26/09) lo dice por Telegram.
2. **La primera llamada salio 6.551 s despues del cierre de su vela:** fue la del despliegue (la vela de
   las 12:00 se decidio a las 17:49). No es inestabilidad.
3. **Las dos carteras llenas casi siempre:** en las primeras 36 h, 8 de 9 velas con 3 posiciones, y 3
   candidatos en 2 velas. Con la cartera llena no se generan candidatos: es el dato de la decision 5.
4. **Memoria (revisada el 27/09 15:43 UTC, 46 h de servicio):** 988 MB usados de 1.967, 978 MB
   disponibles; swap de 1 GB usada 12 KB; presion de memoria 0; ningun proceso matado por falta de
   memoria desde el 25/09. Picos desde el ultimo arranque (26/09): ingesta 195 MB, papel 189 MB, IA
   189 MB de 900 MB, panel 57 MB, noticias 28 MB, telegram 31 MB. **OJO:** desde el 26/09 no ha habido
   ninguna llamada a la IA (cartera llena), asi que el pico de la IA NO incluye una llamada; la del
   despliegue midio 230 MB. Si en la semana hay llamadas, mirar `MemoryPeak` de `ploutos-paper-ai`.
5. **Disco:** 5,4 GB de 58 GB. La base principal crece ~19 MB al dia (95 MB en 5 dias, casi todo el
   libro de cada 10 s); a ese ritmo, ~7 GB en un anyo. Las copias se guardan 14 dias. **A vigilar, no
   urgente:** `fetch-backup.sh` baja TODAS las copias cada domingo, y cada una de la base principal
   pesa mas que la anterior (29 MB hoy).

## 4. Lo que una semana puede y no puede demostrar

- **Puede:** que la pieza funciona, no se sale del contrato, no se cae y cuanto gasta.
- **No puede decir si la IA aporta.** Eso es la fase 6 (minimo hasta el 16/10, 30 discrepancias).
- **El consumo se mide con pocas llamadas** (2 hasta el 27/09): con la cartera llena casi no se llama.
  Es un consumo real, pero de una semana en que el mercado ha dado pocos candidatos.

## 5. Lo que se decide el 02/10

1. **Si la fase 3 esta cerrada** (los cuatro criterios) y **el OK del propietario para la fase 4**.
2. **Candidatos en sombra** (decision 5 del protocolo de la fase 6), con el recuento de `check_fase3.py`
   (candidatos por dia y velas con la cartera llena). La regla que se fijo: con 2-3 al dia no hace falta;
   con 1 o menos, plantearselo. Es una funcionalidad fuera del PRD y cambiaria la pregunta: se decide con
   el numero delante.
3. **Antes de empezar la fase 4**, si el propietario da el OK: la comision en USDC (`feeType = 1`) en la cuenta demo
   (el propietario, o yo con su permiso), actualizar ccxt con los tests (decision del 27/09) y la parada de
   mantenimiento para los paquetes de Ubuntu.

## 5b. Ensayo general del 28/09 (21:20 UTC, 3,3 dias de 7)

Los mismos comandos de la seccion 1, en el VPS, para ver con 4 dias de margen si algo va mal. **Ningun juez da
FALLA; todos dicen "aun no" solo porque faltan dias.**

| Juez | Resultado del ensayo |
|---|---|
| `check_fase3.py` | 1: las dos carteras al dia (ultima vela 28/09 16:00), ninguna vela perdida. 2: 3 velas para decidir, 3 validas. 3: 3 llamadas, 0,09 $ equivalentes cada una (~0,57 $/semana), latencia mediana 21 s (timeout 90). 4: juez de papel CUMPLIDO en las dos (80 h). Sombra: 4 candidatos en 3 velas (1,2/dia), cartera llena en 17 de 20 velas |
| `check_fase6.py` | datos coherentes, mismos candidatos en las dos carteras; 1 discrepancia de 30; tramo `f063d80147a9` sin partir |
| `check_news.py` | 5 comprobaciones OK (901 lecturas, 0 flags) |
| `check_control.py` | 5 comprobaciones OK (8 comandos de Telegram, todos respondidos) |

Lo que hay que saber para el 02/10:
- **Reinicios:** papel e IA arrancaron el 28/09 08:37 (el despliegue del arreglo de la vela de las ocho monedas,
  decision del propietario); el panel, el 28/09 21:16 (el diagrama de flujo). **29/09 ~08:03 UTC:** papel, IA y panel otra vez (la frase de
  "sin senyal"; solo apunta, huella `f063d80147a9` comprobada despues). Ninguna vela perdida por ello.
- **Memoria:** 1.140 MB usados de 1.967, swap sin usar. **El pico de la IA (185 MB de 900) NO incluye ninguna
  llamada** (la ultima fue a las 00:00 y el servicio se reinicio a las 08:37): si el 02/10 sigue asi, la medida
  buena de una llamada es la del despliegue (230 MB).
- **La cuota del analista** sale a ~0,6 $ equivalentes por semana con 0,9 llamadas al dia: poco, porque con la
  cartera llena casi no se le pregunta. Es el dato de la decision de los candidatos en sombra
  (`docs/archivo/propuesta-candidatos-sombra.md`).

## 6. Resultados (02/10/2026, 13:18 UTC; salidas tal cual, en el VPS)

### Criterios 1 a 4: `check_fase3.py`

```
1. Una semana estable
   baseline  desde 25/09 12:00: 7.0 dias, ultima vela 02/10 08:00
   IA        desde 25/09 12:00: 7.0 dias, ultima vela 02/10 08:00
   ninguna vela perdida por una parada

2. Salidas invalidas: todas controladas
   3 vela(s) para decidir: valida 3

3. Consumo de la IA
   llamadas: 3 (0 sonda(s)); media 0.4/dia, pico 2/dia (tope 40) y 2 en 5 h (tope 8)
   tokens: 8 de entrada, 4611 de salida, 54515 de cache creada
   coste equivalente (cuota, no dinero): 0.272 $ en total, 0.0908 $/llamada, ~0.27 $/semana
   latencia: mediana 21.3 s, p95 22.2 s, maxima 22.2 s (timeout 90 s)
   llamada tras el cierre de la vela: mediana 13 s, maxima 6551 s
   la cuota semanal: mirarla en Settings > Usage (no hay API para leerla)

4. El juez de papel de las dos carteras
   baseline  codigo 0: RESULTADO: criterio CUMPLIDO (168 h, 5 ordenes, todo coherente).
   IA        codigo 0: RESULTADO: criterio CUMPLIDO (168 h, 4 ordenes, todo coherente).

Para decidir los candidatos en sombra (decision 5 de la fase 6)
   baseline  5 candidato(s) en 4 vela(s): 0.7/dia; cartera llena en 36 de 42 velas
   IA        4 candidato(s) en 3 vela(s): 0.6/dia; cartera llena en 17 de 42 velas

RESULTADO: CUMPLIDO (falta que el propietario mire la cuota semanal en Settings > Usage).
exit=0
```

### Fase 6: `check_fase6.py` (el tramo no se ha partido)

```
Fase 6, IA contra baseline. Tramo f063d80147a9 desde 25/09/2026 12:00 UTC

  Datos
    OK    journal completo y coherente con la salida guardada
    OK    mismos candidatos en las dos carteras (4 comparados)

  Cobertura
    velas apuntadas por el analista: 3
    decididas: 3 (de ellas 0 con fallo de la IA, que cuentan como no abrir nada)

  Muestra
    juzgables: 1 velas; 2 esperando su horizonte de 42 velas
    velas en que la IA y el baseline discrepan: 1 de 30
    calendario: minimo 16/10/2026, tope 20/11/2026

VEREDICTO: todavia no (faltan 14 dias y 29 discrepancias). Los datos estan bien.
exit=2
```

### Noticias y comandos: `check_news.py` y `check_control.py`

A las 13:18 UTC llevan 6,8 dias (desplegados el 25/09 ~18:20): coherentes, sin FALLA. Los 7 dias se cumplen hoy a
las ~18:20 UTC; se vuelven a pasar entonces (abajo, "A las 18:30").

```
Noticias: 6.8 dias de servicio; carteras: ploutos-paper, ploutos-paper-ai
  OK    el servicio no se ha parado (lecturas cada <= 15 min)  (1957 comprobados)
  OK    si la fuente cayo mas de 1 h, se aviso  (1958 comprobados)
  OK    cada flag que llego a estar activa se aviso  (0 comprobados)
  OK    cada flag levantada a mano existe  (0 comprobados)
  OK    ninguna cartera genero candidatos de una moneda con flag  (18 comprobados)

RESULTADO: coherente, pero solo 6.8 dias de 7. Aun no.
exit=2

Comandos: 6.8 dias de servicio; carteras: ploutos-paper, ploutos-paper-ai
  OK    el servicio no se ha parado (una vuelta cada <= 10 min)  (23405 comprobados)
  OK    cada comando de Telegram recibio su respuesta  (8 comprobados)
  OK    comandos a tiempo, y el /kill solo se levanta en el VPS o el panel con motivo  (8 comprobados)
  OK    la pausa solo cae con /si a tiempo; la parada, solo desde el VPS o el panel  (8 comprobados)
  OK    cada cartera tuvo la pausa y la parada que tocaban en cada vela  (84 comprobados)

RESULTADO: coherente, pero aun no hay 7 dias de servicio.
exit=2
```

**A las 20:38 UTC (7,1 dias): CUMPLIDOS los dos** (se pasaron mas tarde de las 18:30 previstas; nada cambia).

```
Noticias: 7.1 dias de servicio; carteras: ploutos-paper, ploutos-paper-ai
  OK    el servicio no se ha parado (lecturas cada <= 15 min)  (2046 comprobados)
  OK    si la fuente cayo mas de 1 h, se aviso  (2047 comprobados)
  OK    cada flag que llego a estar activa se aviso  (0 comprobados)
  OK    cada flag levantada a mano existe  (0 comprobados)
  OK    ninguna cartera genero candidatos de una moneda con flag  (21 comprobados)

RESULTADO: criterio CUMPLIDO (7.1 dias, todo coherente).
exit=0

Comandos: 7.1 dias de servicio; carteras: ploutos-paper, ploutos-paper-ai
  OK    el servicio no se ha parado (una vuelta cada <= 10 min)  (24457 comprobados)
  OK    cada comando de Telegram recibio su respuesta  (8 comprobados)
  OK    comandos a tiempo, y el /kill solo se levanta en el VPS o el panel con motivo  (8 comprobados)
  OK    la pausa solo cae con /si a tiempo; la parada, solo desde el VPS o el panel  (8 comprobados)
  OK    cada cartera tuvo la pausa y la parada que tocaban en cada vela  (88 comprobados)

RESULTADO: CUMPLIDO.
exit=0
```

Primera vela despues de la parada de mantenimiento (13:56-14:03 UTC): la de las 12:00 (cerrada a las 16:00) y la
de las 16:00, procesadas en las DOS carteras con las 8 monedas (`paper_market`).

### Bloqueos silenciosos: `check_bloqueos.py` (juez nuevo del 01/10)

```
Bloqueos silenciosos: 3+ velas seguidas sin poder entrar por un motivo de sistema (ventana 24 h; notas de 7 dias)
  OK    ploutos-paper.db: 41 velas miradas
          (antes) 5 velas seguidas sin poder entrar (30/09 08:00 - 01/10 00:00 UTC), por: paridad de usdc
  OK    ploutos-paper-ai.db: 41 velas miradas
          (antes) 5 velas seguidas sin poder entrar (30/09 08:00 - 01/10 00:00 UTC), por: paridad de usdc

RESULTADO: sin bloqueos.
exit=0
```

### Reinicios y memoria

```
ploutos-ingest MemoryPeak=217460736 MemoryMax=infinity ActiveEnterTimestamp=Wed 2026-09-30 06:23:52 UTC 
ploutos-paper MemoryPeak=184754176 MemoryMax=infinity ActiveEnterTimestamp=Thu 2026-10-01 07:25:06 UTC 
ploutos-paper-ai MemoryPeak=184336384 MemoryMax=943718400 ActiveEnterTimestamp=Thu 2026-10-01 07:25:06 UTC 
ploutos-news MemoryPeak=31842304 MemoryMax=209715200 ActiveEnterTimestamp=Wed 2026-09-30 06:23:48 UTC 
ploutos-telegram MemoryPeak=30855168 MemoryMax=209715200 ActiveEnterTimestamp=Wed 2026-09-30 06:23:48 UTC 
ploutos-panel MemoryPeak=61100032 MemoryMax=209715200 ActiveEnterTimestamp=Thu 2026-10-01 09:02:02 UTC 
               total        used        free      shared  buff/cache   available
Mem:            1967        1191         146           0         810         776
NAME      TYPE  SIZE USED PRIO
/swapfile file 1024M 7,8M   -2
/dev/vda3        58G  5,8G   50G  11% /
```

- **Reinicios durante la semana:** 26/09 (libexpat, `needrestart`), 28/09 08:37 (arreglo de la vela de las ocho
  monedas), 29/09 ~08:03 (la frase de "sin senyal"), **30/09 06:23 UTC: `unattended-upgrade` (seguridad) y
  `needrestart` reiniciaron TODOS los servicios** entre dos velas, y 01/10 07:25 (paridad solo con A, decision de
  el propietario). Ninguna vela perdida (criterio 1).
- **Memoria:** 776 MB disponibles de 1.967; swap usada 7,8 MB de 1 GB. Picos desde el ultimo arranque: ingesta
  217 MB, papel 185 MB, IA 184 MB de 900 MB (SIN ninguna llamada: la ultima fue el 29/09; la medida buena de una
  llamada sigue siendo la del despliegue, 230 MB), panel 61 MB, noticias y comandos ~31 MB. Disco al 11 %.

### Cuota semanal (el propietario, Settings > Usage)

**No se pudo mirar la de la semana de la fase 3:** la cuota semanal se reinicio el jueves 01/10 a las 2:00 hora de
Espanya (~00:00 UTC), antes del cierre. La que se ve ahora es la semana nueva, casi toda uso del propietario (el bot no ha
llamado desde el 29/09). El consumo del bot queda MEDIDO por el juez a partir del journal: 3 llamadas en 7 dias,
0,27 $ equivalentes en total (0,09 $ por llamada, ~0,27 $ por semana), latencia mediana 21 s. Con 0,4 llamadas al
dia es una parte despreciable de la suscripcion compartida. Para mirar una semana entera en Settings: el miercoles.

### Incidente de la semana

30/09 08:00 - 01/10 00:00: la regla 17 bloqueo todas las entradas de las dos carteras durante 5 velas, porque OKX
retiro BTC/USD al unificar sus libros en dolares (`hallazgos-fase-3-4.md` 5d). No es inestabilidad (el bot cumplio
la regla y no perdio ninguna vela), pero nadie lo supo en 20 h. Arreglado el 01/10: paridad solo con A, aviso de
Telegram de la regla 17 y el juez de bloqueos silenciosos (`dossier-02-10.md` 2.5).

### Veredicto

**CUMPLIDO.** Los cuatro criterios: (1) 7,0 dias de las dos carteras, al dia, ninguna vela perdida; (2) 3 velas para
decidir, 3 respuestas validas, ninguna salida sin controlar; (3) consumo medido por el juez (la cuota semanal de
Settings no se pudo leer, por el reinicio del 01/10); (4) juez de papel CUMPLIDO en las dos carteras (168 h).
Noticias y comandos: CUMPLIDOS a los 7,1 dias (20:38 UTC). **el propietario, 02/10: fase 3 CERRADA.** Decididos
el mismo dia: sombra opcion B y OK a la fase 4 con `tradeQuoteCcy: "USDC"` explicito (CLAUDE.md).
