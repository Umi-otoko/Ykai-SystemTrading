# YKAI Quant Core — TradingBot v2

Bot de trading algorítmico para Binance USD-M Futures Testnet.  
Capital objetivo: $50 USD | Riesgo por trade: $1.00 (2%) | Circuit breaker: $3.00 (6%)

---

## Estrategia

- **Multi-timeframe**: tendencia en 1h, entrada en 15m
- **Indicadores**: EMA 20/50/200, RSI(14), ATR(14), Volumen relativo
- **Sistema de score**: 6 condiciones binarias, entra solo si score ≥ 4
- **Leverage automático**: calculado para que la pérdida sea siempre exactamente $1.00
- **TPs escalonados**: cierra 30% en TP1 (1:1) → trailing stop activo → TP2 (3:1)
- **Trailing stop**: tras TP1, el SL sigue al mejor precio visto (TRAIL_FACTOR = 0.5)
- **Circuit breaker**: $3 de pérdida diaria → bot pausado automáticamente

### Fórmula de leverage

```
leverage = riesgo_usd / (capital_usd × distancia_sl_pct)
```
Con $50 capital y $1 de riesgo, el leverage se ajusta al stop real del mercado (ATR-based), nunca al revés.

---

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `TradingBot_v2.py` | Bot principal |
| `YKAI_CONTEXTO_MAESTRO.py` | Documento de contexto del proyecto (historia, decisiones, arquitectura) |
| `.env.example` | Plantilla de credenciales |
| `.gitignore` | Excluye `.env`, logs y estado |

---

## Setup

### 1. Instalar dependencias

```bash
pip install ccxt pandas numpy requests python-dotenv
```

### 2. Crear el archivo `.env`

```bash
cp .env.example .env
```

Edita `.env` con tus keys del [Testnet de Binance Futures](https://testnet.binancefuture.com) y tu bot de Telegram.

```env
API_KEY_BINANCE=tu_key
API_SECRET_BINANCE=tu_secret
TELEGRAM_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id
```

### 3. Ejecutar

```bash
python TradingBot_v2.py
```

---

## Modos de operación

| Variable | Valor | Efecto |
|----------|-------|--------|
| `DRY_RUN` | `True` | Simula todo, no ejecuta órdenes reales |
| `DRY_RUN` | `False` | Ejecuta órdenes reales en el testnet |

Cambiar en la línea 25 de `TradingBot_v2.py`.

---

## Parámetros configurables

```python
CAPITAL_USD         = 50.0
RIESGO_USD          = 1.0        # $1 por trade = 2%
MAX_PERDIDA_DIA     = 3.0        # circuit breaker
MAX_TRADES_ABIERTOS = 2

ATR_MULT            = 1.3        # multiplicador para el stop loss
TP1_RATIO           = 1.0        # ratio del primer target
TP2_RATIO           = 3.0        # ratio del segundo target
TP1_CIERRE_PCT      = 0.30       # % de posición que cierra en TP1
TRAIL_FACTOR        = 0.5        # agresividad del trailing stop post-TP1

SCORE_MINIMO        = 4          # condiciones mínimas para entrar (de 6)
ACTIVOS             = ["BTC/USDT", "SOL/USDT", "ETH/USDT"]
INTERVALO_SCAN      = 30         # segundos entre ciclos
```

---

## Lógica de señal

### LONG (6 condiciones)
| # | Condición | Descripción |
|---|-----------|-------------|
| c1 | `precio > EMA200` | Tendencia de fondo alcista |
| c2 | `EMA20 cruza sobre EMA50` | Momentum positivo |
| c3 | `40 ≤ RSI ≤ 65` | Zona neutra, no sobrecomprado |
| c4 | `volumen > 1.3× media` | Confirmación de movimiento |
| c5 | `mínimo ≥ EMA20 × 0.998` | Pullback controlado |
| c6 | `tendencia 1h = ALCISTA` | Confirmación multi-timeframe |

### SHORT (condiciones simétricas)
Precio bajo EMA200, cruce bajista EMA20/50, RSI 35–60, volumen, tendencia 1h BAJISTA.

---

## Protecciones implementadas

- **Credenciales**: solo en `.env`, nunca en el código
- **Retry con backoff**: toda llamada al exchange tiene 3 reintentos
- **Circuit breaker**: para el bot si pérdida diaria ≥ $3
- **Cooldown post-SL**: 1 hora sin re-entrar al mismo símbolo tras una pérdida
- **Breakeven + trailing**: tras TP1, el SL sigue al mejor precio para asegurar ganancia
- **Persistencia de estado**: si el bot se reinicia, recupera posiciones abiertas desde `estado_bot.json`
- **PnL exacto**: usa precio del SL/TP, no el precio del scan (evita inflación por delay)

---

## Historial de versiones

| Versión | Cambios |
|---------|---------|
| v2.0 | Bot original reconstruido con auto-leverage, multi-TF, score 6 condiciones |
| v2.1 | Fix PnL exacto en SL/TP, breakeven automático tras TP1, cooldown post-SL |
| v2.2 | Persistencia de estado en JSON, trailing stop dinámico, TP2 bajado a 3:1 |

---

## Advertencia

Este bot opera en **testnet** (dinero ficticio). Nunca ha operado con capital real.  
Antes de activar `DRY_RUN = False` en producción real, verificar resultados en testnet por al menos 2–4 semanas.
