# Kronos, paso 1: acierta con nuestras monedas? (08/10/2026): NO

Idea E de la segunda ronda (`docs/archivo/plan-segunda-ronda-estrategia.md`). Criterio y detalles aprobados por el propietario el 08/10
ANTES de medir (`9ffcb7c`), con las descargas. Kronos (`github.com/shiyu-coder/Kronos`, MIT; arXiv 2508.02739) es un
modelo entrenado con ~12.000 millones de velas de 45 bolsas **hasta junio de 2024**: aqui se mide solo despues.

**Como:** `medir_kronos.py`, en su propio entorno (`var/kronos/.venv`, PyTorch 2.14.1 para CPU), sin tocar el bot.
Kronos-small (`NeoQuasar/Kronos-small` + `Kronos-Tokenizer-base`) sin reentrenar, solo OHLC, 400 velas de 4 h de
contexto, prediccion de 6 velas (24 h), media de 5 muestras con semilla fija; una prediccion cada 6 velas. Datos:
`time-stop/historia.db`, contra USDC, del 21/08/2025 al 28/09/2026 (AVAX desde el 09/10/2025, NEAR desde el 26/02/2026).
El codigo de Kronos se leyo entero antes de ejecutarlo (sin red ni ejecucion de nada; los pesos en `safetensors`).
2.450 predicciones, 2,0-2,7 s cada una en el portatil.

## Resultado

| | Predicciones | Spearman (predicho frente a real, a 24 h) |
|---|---|---|
| **Las 8 juntas** | 2.450 en 336 dias | **-0,042** (IC 90 %: -0,106 a +0,021) |
| AVAX | 287 | +0,007 |
| BTC | 336 | -0,074 |
| DOGE | 336 | -0,047 |
| ETH | 336 | -0,033 |
| NEAR | 147 | -0,029 |
| SOL | 336 | -0,057 |
| TRX | 336 | +0,013 |
| XRP | 336 | -0,027 |

| Criterio | |
|---|---|
| IC 90 % del conjunto entero por encima de 0 | **no** (-0,106 a +0,021) |
| Positiva en >= 5 de las 8 | **no** (2 de 8) |

Informativo: acierta la direccion el 46,8 % de las veces; el precio subio el 47,6 % (decir "siempre baja" acertaba el
52,4 %).

## Lo que dice

1. **Kronos no sabe nada de nuestras monedas a 24 h**: la correlacion es cero, si acaso un poco NEGATIVA, y en 6 de
   las 8 monedas apunta al reves. Ni de lejos la senyal que haria falta para pagar ~0,3 % por operacion.
2. **Encaja con lo que ya se sospechaba** (08/10): mira las mismas velas que los setups y su ventaja publicada (IC
   ~0,04 ordenando acciones) es pequenya; en cripto, despues de su entrenamiento, no aparece.
3. **Por el criterio, se cierra el tema:** el paso 2 (Kronos como filtro) no se hace, y no se prueban otros
   horizontes, contextos ni versiones del modelo.

## Ficheros

`medir_kronos.py` (la medicion y el criterio), `resultados/predicciones.jsonl` (cada prediccion), `veredicto.txt` y
`veredicto.json`, `predecir.log`. El entorno, el codigo de Kronos y los pesos estan en `var/kronos/` (fuera de git,
~860 MB). **Se guardan para Ebisu** (el propietario, 09/10): el articulo tiene divisas; alli se probaria con la misma prueba
limpia.
