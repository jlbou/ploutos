# La whitelist: decision del 09/10/2026 (AVAX, DOGE y NEAR)

**Estado: DECIDIDO el 09/10 (opcion a, LINK como primera alternativa; seccion 5).** Preparado el 28/09/2026, con
AVANCES del 04/10 (seccion 4b) y del 07/10 (4c); pendiente de los numeros del 09/10.** el propietario decidio el 27/09 decidir ese dia,
con dos semanas de datos y dos fines de semana. Este documento deja listo el como: ese dia es lanzar la orden,
pegar la salida y decidir.

## 0. El guion del 09/10

| Paso | Que | Donde |
|---|---|---|
| 0 | Parar y quitar la medicion temporal: `systemctl disable --now ploutos-spread-extra` y borrar su unidad de `/etc/systemd/system`; bajar `var/spread/extra-20260928.csv` y resumirlo con `scripts/analyze_spread.py` | VPS y portatil |
| 1 | Bajar la copia de la noche (`bash deploy/fetch-backup.sh ploutos`) | portatil |
| 2 | Descomprimir la copia principal mas reciente de `var/backups/` en el scratchpad | portatil |
| 3 | `.venv/Scripts/python.exe scripts/estudio_spread.py --db <copia> --desde 2026-09-23` | portatil |
| 4 | Pegar la salida en la seccion 5, tal cual | aqui |
| 5 | Decidir con el propietario (seccion 4) | los dos |

En el portatil y sobre la copia, no en el VPS: con dos semanas son ~1 M de filas y en el VPS compite con el bot.
**Desde el 23/09**: el 22/09 solo tiene medio dia y el servicio de medicion del spread aun corria aparte.

## 1. La pregunta

La whitelist se eligio el 22/09 con el criterio del informe 4.1: **spread medio < 0,05 %** y profundidad de al
menos 20 veces una orden de 15 $. ADA (0,067 %) y LINK (0,065 %) se quedaron fuera por eso. DOGE y NEAR entraron
en el borde y se decidio medirlas mas (23/09). Con 5 dias (27/09):

| Moneda | Media | Lo peor | Cierres de vela que la regla 16 bloqueo |
|---|---|---|---|
| AVAX | **0,0503 %** | 0,055 % en fin de semana | 0 de 30 |
| DOGE | 0,0460 % | 0,052 % en la franja de America | 1 de 30 |
| NEAR | 0,0459 % | 0,048 % los laborables | 1 de 30 |

**El spread es COSTE, no rentabilidad.** Que una moneda gane o pierda en las posiciones de estos dias no entra
en la decision (el propietario, 27/09: AVAX era la unica en beneficio).

## 2. Lo que pesa, a favor y en contra

- **En dinero es poco:** un 0,05 % de una orden de 15 $ es menos de un centimo por operacion.
- **La regla 16 ya protege donde importa:** con el spread por encima del 0,10 % al decidir, no se entra.
- **Pero la linea del 0,05 % dejo fuera a ADA y LINK.** Si se relaja para AVAX, DOGE y NEAR, lo coherente es
  mirar ADA y LINK con el mismo criterio. **No hay datos suyos**: la ingesta solo guarda las 8 de la whitelist.
  Para compararlas de verdad habria que medirlas hasta el 09/10 (ver 3.3).

## 3. Lo que condiciona la decision (comprobado el 28/09)

1. **La regla 3 obliga a EXACTAMENTE 8 monedas** (`HARD_WHITELIST_SIZE = 8` en `core/config.py`; con otro numero
   el bot no arranca). Quitar una exige poner otra; quedarse en 7 seria cambiar una regla dura.
2. **Cambiar la whitelist parte la muestra de la fase 6**: esta en la huella del camino de decision
   (`ai.journal.camino`). Aunque se decida el 09/10, **el cambio se aplicaria despues del veredicto de la fase 6**
   (desde el 16/10), no ese dia.
3. **ADA y LINK SE ESTAN MIDIENDO desde el 28/09 10:25 UTC** (el propietario, 28/09), junto a AVAX, DOGE y NEAR y con el
   MISMO metodo (una muestra de cada par cada 30 s, datos publicos): servicio temporal `ploutos-spread-extra`
   (`deploy/ploutos-spread-extra.service`, poca prioridad, 250 MB como mucho, el primero en caer), CSV en
   `/opt/ploutos/var/spread/extra-20260928.csv`. Acaba solo hacia el 09/10 08:00. Sin tocar el bot.
4. **La whitelist vive en dos sitios**: `settings.yaml` y la clave de API de OKX (limitada por moneda). La del demo
   solo tiene 5 pares contra USDC (BTC, ETH, SOL, DOGE, NEAR); la real se crea en la fase 7, con las 8 que toquen.

## 4. Las opciones (para el 09/10)

- **a) Dejarla como esta** y decir por escrito que la linea del 0,05 % pasa a ser un aviso y la norma es la regla
  16 (recomendado si AVAX, DOGE y NEAR siguen alrededor del 0,05 %). Entonces, por coherencia, ADA y LINK quedan
  como candidatas si alguna vez sale una de las 8.
- **b) Cambiar una moneda por otra** (la que peor salga, por ADA o LINK si se han medido y salen mejor). Se aplica
  tras el veredicto de la fase 6 y cambia la clave de OKX.
- **c) Esperar mas datos** si en las dos semanas pasa algo raro (un fin de semana anomalo, una caida de la ingesta).

## 4b. Avance del 04/10/2026 (11 dias de 14; el 09/10 se repite con todo)

Sobre la copia de la noche del 04/10 (portatil). Dos fuentes: `estudio_spread.py` (las 8 de la whitelist, `book_metrics`
de la ingesta, una muestra cada ~10 s) y `analyze_spread.py` sobre `extra-20260928.csv` (ADA y LINK con AVAX, DOGE y
NEAR, el libro publico cada 30 s, desde el 28/09 10:25).

**Las 8, del 23/09 al 04/10 03:18 (11,1 dias):**

| Par | Media | Mediana | p95 | Peor franja | Dias > 0,05 % | Tiempo > 0,05 % | > 0,10 % | Cierres bloqueados (regla 16) |
|---|---|---|---|---|---|---|---|---|
| AVAX | **0,0422 %** | 0,0446 | 0,0717 | 0,0443 (finde) | 5/12 | 24,8 % | 0,7 % | 0/67 |
| DOGE | **0,0392 %** | 0,0325 | 0,0719 | 0,0430 (America) | 1/12 | 25,0 % | 0,8 % | 1/67 |
| NEAR | **0,0455 %** | 0,0421 | 0,0734 | 0,0472 (laborables) | 1/12 | 30,0 % | 1,1 % | 1/67 |
| XRP | 0,0247 % | | 0,0637 | | 0/12 | 10,1 % | 0,9 % | 0/67 |
| TRX, SOL, ETH, BTC | 0,002-0,022 % | | | | 0/12 | <= 1,6 % | 0 % | 0/67 |

**ADA y LINK, del 28/09 10:25 al 04/10 11:08 (6 dias, 81.815 muestras), con AVAX, DOGE y NEAR por el MISMO metodo:**

| Par | Media | p95 | > 0,10 % | Profundidad minima | Veredicto del 0,05 % |
|---|---|---|---|---|---|
| ADA | **0,0786 %** | 0,1221 | **9,0 %** | 152 $ | falla: media y profundidad |
| LINK | **0,0534 %** | 0,0811 | 1,6 % | 2.057 $ | falla: media |
| AVAX | 0,0327 % | 0,0655 | 0,3 % | 276 $ (una muestra) | pasa la media |
| DOGE | 0,0333 % | 0,0539 | 0,2 % | 883 $ | pasa |
| NEAR | 0,0457 % | 0,0650 | 0,8 % | 1.177 $ | pasa |

**Los dos metodos coinciden** en la misma ventana (28/09-04/10): AVAX 0,0337 frente a 0,0327; DOGE 0,0335 frente a
0,0333; NEAR 0,0456 frente a 0,0457. La diferencia con las medias de 11 dias es la ventana: del 23 al 28/09 los
spreads fueron mas anchos (AVAX llego a 0,050 %) y desde entonces han bajado.

**Lectura provisional (la decision es del propietario el 09/10):**
- Las tres del borde **pasan** la media del 0,05 % con 11 dias; NEAR es la mas justa (0,0455 %, un 30 % del tiempo por
  encima del 0,05 %). La regla 16 solo ha bloqueado 1 cierre de 67 en DOGE y en NEAR.
- **Ninguna de las de fuera es mejor que la peor de dentro:** ADA (0,079 %, un 9 % del tiempo por encima del 0,10 %:
  la regla 16 la bloquearia a menudo) y LINK (0,053 %) salen peor que NEAR. La opcion b) no tiene con que cambiar.
- Si los dos dias que faltan no cambian esto, **lo indicado seria la a)**: dejar la whitelist como esta y escribir que
  el 0,05 % es una referencia y la regla 16 la norma.
- Detalle a mirar: la profundidad MINIMA de AVAX en el CSV (276 $, una sola muestra) queda bajo los 300 $ del informe;
  su p5 en la ingesta es de 44.359 $. Es un instante, no la norma.

## 4c. Segundo avance, 07/10/2026 (14 dias de la ingesta; el 09/10 se repite con todo)

Mismos dos scripts: `estudio_spread.py` sobre la copia de la noche del 07/10 (23/09 00:00 -> 07/10 03:18, 14,1 dias) y
`analyze_spread.py` sobre `extra-20260928.csv` (28/09 10:25 -> 07/10 18:32, 224 h, 126.694 muestras).

| Par | Media (ingesta) | Tiempo > 0,05 % | > 0,10 % | Cierres bloqueados | Media (CSV, desde el 28/09) | Veredicto del CSV |
|---|---|---|---|---|---|---|
| AVAX | 0,0384 % | 19,8 % | 0,6 % | 0/85 | 0,0301 % | falla por la profundidad minima (276 $, la misma muestra del 04/10) |
| DOGE | 0,0392 % | 24,3 % | 0,7 % | 1/85 | 0,0360 % | pasa |
| NEAR | **0,0456 %** | 30,6 % | 1,3 % | 1/85 | 0,0457 % | pasa |
| ADA | - | - | 7,3 % | - | **0,0752 %** | falla: media y profundidad (152 $) |
| LINK | - | - | 1,1 % | - | **0,0489 %** | falla en la franja de America (0,0505 %) |

Lo que cambia frente al 04/10: **nada de fondo.** Las 8 pasan con 14 dias; NEAR sigue siendo la mas justa (0,0456 %) y
la regla 16 solo ha bloqueado 1 cierre de 85 en DOGE y en NEAR. LINK ha mejorado (0,053 -> 0,049 %) pero sigue peor
que NEAR y falla una franja; ADA sigue lejos. La lectura provisional sigue siendo la **a)**. La profundidad minima de
AVAX en el CSV es la misma muestra suelta del 04/10; su p5 en la ingesta es de 24.726 $.

## 5. Resultados (rellenar el 09/10/2026)

```
Copia de la noche del 09/10 (ploutos-20261009T031636Z), desde el 23/09:

book_metrics: 23/09 00:00 -> 09/10 03:16 UTC (16.1 dias)

Spread medio (%). Whitelist: < 0.05 % de media y en cada franja (informe 4.1)
  par          media mediana    p95    asia  europa america  cierre  labor.  finde  dias>  veredicto
  AVAX/USDC   0.0370  0.0293 0.0674  0.0375  0.0366  0.0371  0.0363  0.0364 0.0390   5/17  PASA
  BTC/USDC    0.0014  0.0001 0.0078  0.0013  0.0015  0.0016  0.0010  0.0015 0.0012   0/17  PASA
  DOGE/USDC   0.0397  0.0395 0.0716  0.0382  0.0375  0.0432  0.0385  0.0396 0.0402   1/17  PASA
  ETH/USDC    0.0061  0.0004 0.0231  0.0063  0.0057  0.0067  0.0048  0.0063 0.0054   0/17  PASA
  NEAR/USDC   0.0470  0.0417 0.0803  0.0455  0.0460  0.0491  0.0469  0.0483 0.0429   4/17  PASA
  SOL/USDC    0.0164  0.0166 0.0348  0.0171  0.0166  0.0160  0.0153  0.0176 0.0127   0/17  PASA
  TRX/USDC    0.0217  0.0209 0.0356  0.0220  0.0224  0.0211  0.0211  0.0219 0.0210   0/17  PASA
  XRP/USDC    0.0216  0.0197 0.0569  0.0213  0.0218  0.0232  0.0181  0.0225 0.0188   0/17  PASA

Lo que cuesta: tiempo por encima de cada linea y entradas que la regla 16 bloquea al decidir
  par          >0,05 %  >0,10 %  cierres bloqueados  prof. p5 $    min $
  AVAX/USDC      17.5%     0.5%                0/97      22,956      696
  BTC/USDC        0.0%     0.0%                0/97     220,879   44,099
  DOGE/USDC      23.8%     0.8%                2/97      52,166      277
  ETH/USDC        0.0%     0.0%                0/97     201,074   90,320
  NEAR/USDC      33.3%     2.1%                2/97      15,890      839
  SOL/USDC        1.1%     0.0%                0/97      72,495   23,751
  TRX/USDC        0.2%     0.0%                0/97      80,698    8,205
  XRP/USDC        7.0%     0.6%                0/97     105,997   15,861

Esto no decide nada: la whitelist es la regla 3 y la cambia el propietario (y con ella, la clave de OKX).
```

```
extra-20260928.csv, final (el servicio se paro el 09/10 a las 09:56 UTC):

extra.csv: 148959 muestras, 263.5 h, 28/09 10:25 -> 09/10 09:56 UTC

Spread medio (%) contra USDC, por franja. Criterio del informe: < 0.05 %
  par           total     asia   europa  america   cierre     p95  >0,10%  prof.min $  veredicto
  ADA/USDC     0.0745   0.0742   0.0764   0.0749   0.0709  0.1180    6.5%         152  FALLA: media, profundidad
  AVAX/USDC    0.0297   0.0295   0.0290   0.0305   0.0293  0.0591    0.2%         276  FALLA: profundidad
  DOGE/USDC    0.0370   0.0358   0.0350   0.0397   0.0366  0.0625    0.3%         184  FALLA: profundidad
  LINK/USDC    0.0470   0.0453   0.0464   0.0491   0.0465  0.0762    0.9%       2,057  PASA
  NEAR/USDC    0.0477   0.0460   0.0462   0.0500   0.0482  0.0816    2.4%       1,177  FALLA: en alguna franja

USD contra USDC, en la MISMA ronda (spread medio % y cuantas veces gana USD)
  base    rondas     USDC      USD  USD/USDC  gana USD

Esto no cambia nada por si solo: la whitelist y la quote son la regla 3,
y la regla 3 la cambia el propietario. Ademas, que es 'USD' en OKX sigue sin saberse
(CLAUDE.md, pregunta abierta sobre la quote).
```

### Lectura (09/10, antes de la decision del propietario)

- **Las 8 pasan** la media del 0,05 % con 16 dias de la ingesta; NEAR sigue siendo la mas justa (0,0470 %, un 33 % del
  tiempo por encima del 0,05 %, 2 cierres bloqueados de 97). DOGE tambien 2 de 97.
- **Lo nuevo frente al 07/10:** en el CSV (28/09-09/10, el mismo metodo para las cinco), **LINK (0,0470 %) queda
  ligeramente por delante de NEAR (0,0477 %)**: menos tiempo por encima del 0,10 % (0,9 % frente a 2,4 %) y mas
  profundidad minima (2.057 $ frente a 1.177 $); NEAR falla la franja de America por una centesima (0,0500 %). La
  diferencia de medias es de 0,0007 puntos: ruido. ADA sigue lejos (0,0745 %).
- **Lectura:** **a) dejarla como esta**, con LINK como primera alternativa si alguna vez sale una de las 8. Cambiar
  NEAR por LINK costaria cambiar la clave de OKX y partir la muestra de la fase 6 por una diferencia que no se
  distingue del ruido. Si se adopta la estrategia de tendencia F (que rota entre las 8), el universo se vuelve a mirar
  ANTES de medirla.

### Decision

**a) DECIDIDO por el propietario el 09/10: la whitelist se queda como esta** (`BTC, ETH, SOL, XRP, DOGE, AVAX, TRX, NEAR`), con
**LINK como primera alternativa** si alguna vez sale una de las 8. No cambia nada en `settings.yaml` ni en la clave.
