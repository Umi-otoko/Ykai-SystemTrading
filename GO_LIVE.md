# 🚀 YKAI — Checklist Go-Live ($50 reales)

> **Lee esto completo antes de tocar nada.** El bot está listo técnicamente.
> Esta guía te lleva de testnet a $50 reales de forma segura, en orden.

---

## ⚠️ Antes de empezar — la verdad sobre los números

| Métrica (16 días, backtest honesto con costos maker) | Valor |
|---|---|
| Retorno NETO real | **+67.8%** (no el +120% bruto) |
| Probabilistic Sharpe (>0) | **0.949** (94.9% de que el edge sea real) |
| Deflated Sharpe (6 configs probadas) | **0.464** (necesita >0.95 para certeza) |
| Max Drawdown real | **16.5%** |

**Qué significa:** el edge probablemente es real, pero con 16 días de un solo
régimen (BTC bajista) NO está probado con certeza estadística. **Los $50 son
capital de validación, no de inversión.** Trátalos como el costo de validar en
vivo: podrían perderse. El bot tiene circuit breakers, pero ningún bot es infalible.

---

## Paso 1 — Validar primero en TESTNET con órdenes reales (2-3 días)

Antes de dinero real, prueba la ejecución real (limit orders, fills) en testnet:

```python
# TradingBot_v2.py
DRY_RUN      = False    # ejecuta órdenes
USAR_TESTNET = True     # pero en testnet (dinero falso)
```
Deploy y observa 2-3 días que las **limit orders llenan** y los SL/TP se ejecutan
bien. Esto valida la mecánica sin arriesgar nada.

---

## Paso 2 — Crear API keys de MAINNET en Binance

1. Binance → Perfil → **API Management** → Create API
2. Tipo: **System generated**
3. Permisos:
   - ✅ **Enable Futures**
   - ❌ **Enable Withdrawals** (NUNCA — que el bot no pueda sacar fondos)
   - ✅ Enable Reading
4. **Restrict access to trusted IPs only** → agregar `165.1.122.27` (el servidor Oracle)
5. Guardar API Key + Secret (el secret solo se muestra una vez)

---

## Paso 3 — Fondear Futures con $50

- Transferir **$50 USDT** de Spot a **Wallet de Futures USDT-M**
- Verificar que aparecen en el balance de Futures

---

## Paso 4 — Configurar el .env en el servidor

```bash
ssh -i C:\Users\amdry\.ssh\ssh-key-2026-05-25.key ubuntu@165.1.122.27
nano /home/ubuntu/BotTrader/.env
```
```
API_KEY_BINANCE=tu_key_de_MAINNET
API_SECRET_BINANCE=tu_secret_de_MAINNET
```
> El `.env` NUNCA se sube a git (está en .gitignore). Solo vive en el servidor.

---

## Paso 5 — El switch a real

```python
# TradingBot_v2.py
DRY_RUN      = False
USAR_TESTNET = False   # ⚠️ MAINNET — DINERO REAL
```
```bash
# Empezar con capital real correcto
CAPITAL_USD = 50.0
# Borrar el estado de testnet para arrancar limpio
rm /home/ubuntu/BotTrader/estado_bot.json
sudo systemctl restart ykai-bot
```

Verificar el banner: debe decir **"⚠️ DINERO REAL — MAINNET"** y
**"Exchange: Binance Futures MAINNET"**.

---

## Paso 6 — Primeras 48h: vigilancia activa

- Mira el primer trade completo de cerca (entrada limit → fill → SL/TP)
- Confirma que el capital en el log coincide con el balance real de Binance
- Si algo se ve raro: `sudo systemctl stop ykai-bot` (no pierdes la posición,
  solo dejas de abrir nuevas) y revisamos

---

## Guardarraíles ya activos en el bot

| Protección | Valor |
|---|---|
| Circuit breaker diario | Pérdida > $4.40/día → para hasta mañana |
| Max drawdown total | Caída > 15% del pico → para permanente |
| Riesgo por trade | 2% del capital (de-risking ×0.5 tras 2 SLs) |
| Max posiciones | 3 (máx 2 misma dirección) |
| Filtro de régimen | No opera en ADX 20-25 (zona muerte) |
| Filtro de noticias | No opera ±30min de CPI/FOMC/NFP |
| Cooldown post-SL | 2h sin re-entrar al mismo símbolo |

---

## ⛔ Antes del Paso 5, actualizar el calendario de noticias

`NOTICIAS_ALTO_IMPACTO` tiene fechas de EJEMPLO. Reemplázalas con el calendario
real de [Investing.com](https://www.investing.com/economic-calendar/) o
[ForexFactory](https://www.forexfactory.com/calendar) (CPI, PPI, FOMC, NFP del mes).
