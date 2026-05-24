# YKAI Quant Core — TradingBot v2

**© 2026 Ykai. Todos los derechos reservados.**  
Software privado — uso restringido al autor. No se autoriza copia, distribución ni modificación sin permiso expreso.

Bot de trading algorítmico para Binance USD-M Futures Testnet.  
Capital objetivo: $50 USD | Riesgo por trade: $1.00 (2%) | Circuit breaker: $4.00 (8%) | Activos: 6

---

## Estrategia

- **Multi-timeframe**: tendencia en 1h, entrada en 15m
- **Indicadores**: EMA 20/50/200, RSI(14), ATR(14), Volumen relativo
- **Sistema de score**: 6 condiciones binarias, entra solo si score ≥ 4
- **Leverage automático**: calculado para que la pérdida sea siempre exactamente $1.00
- **TPs escalonados**: cierra 30% en TP1 (1:1) → trailing stop activo → TP2 (3:1)
- **Trailing stop**: tras TP1, el SL sigue al mejor precio visto (TRAIL_FACTOR = 0.5)
- **Circuit breaker**: $4 de pérdida diaria → bot pausado automáticamente
- **Near-miss logging**: muestra en consola activos con score 3/6 (un paso de entrar)

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
MAX_PERDIDA_DIA     = 4.0        # circuit breaker (3 posiciones + margen)
MAX_TRADES_ABIERTOS = 3          # posiciones simultáneas

LEVERAGE_MIN        = 1          # 1x mín — respeta $1 riesgo en pares muy volátiles
LEVERAGE_MAX        = 15         # 15x máx — captura leverage óptimo en pares de bajo ATR%
TAMANO_MINIMO_USD   = 15.0       # ignora señales con posición < $15

ATR_MULT            = 1.3        # multiplicador para el stop loss
TP1_RATIO           = 1.0        # ratio del primer target (1:1)
TP2_RATIO           = 3.0        # ratio del segundo target (3:1)
TP1_CIERRE_PCT      = 0.25       # 25% cierra en TP1, 75% sigue con trailing
TRAIL_FACTOR        = 0.4        # trailing ajustado: 0.4× distancia TP1

SCORE_MINIMO        = 4          # condiciones mínimas para entrar (de 6)
ACTIVOS             = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "BNB/USDT"]
INTERVALO_SCAN      = 20         # segundos entre ciclos (antes 30s)
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
- **Trailing stop**: tras TP1, el SL sigue al mejor precio para asegurar ganancia
- **Persistencia de estado**: si el bot se reinicia, recupera posiciones abiertas desde `estado_bot.json`
- **PnL exacto**: usa precio del SL/TP, no el precio del scan (evita inflación por delay)

---

## Historial de versiones

| Versión | Cambios |
|---------|---------|
| v2.0 | Bot original reconstruido con auto-leverage, multi-TF, score 6 condiciones |
| v2.1 | Fix PnL exacto en SL/TP, breakeven automático tras TP1, cooldown post-SL |
| v2.2 | Persistencia de estado en JSON, trailing stop dinámico, TP2 bajado a 3:1 |
| v2.3 | 6 activos (BTC, ETH, SOL, BNB, AVAX, LINK), MAX_TRADES=3, CB=$4, near-miss logging |
| v2.4 | Activos Tier A (XRP, DOGE, BNB), leverage 1-15x, trail 0.4, TP1 25%, scan 20s, tamaño exacto $1 riesgo |
| v2.5 | Filtro macro 4h (c6/d6 dual), score mínimo 5/6, MAX_TRADES=2, pausa global 2 SLs/30min, cooldown 2h |
| v2.6 | Precisión: ATR mínimo 0.12%, volumen 1.5x, RSI SHORT 38-55, LONG 42-60, EMA gap 0.02%, vela confirmada, cap estado |
| v2.7 | Compounding 2%: riesgo dinámico $1→$2→... con capital; MAX_TRADES=3 anti-correlación Tier S; TP1 20%; objetivo 2x en 2 meses |
| v2.8 | Circuit breakers del documento: Fat Finger ±0.5%, Flash Crash Pauser BTC >3%/vela, Max Drawdown 15%, ATR trailing dinámico 1.5×, Kelly Criterion logger |
| v2.9 | BTC momentum filter 1.5% (Holly AI), R:R mínimo 1.8:1, Sharpe+Sortino en startup, capital en historial diario |

---

## Contacto

- **GitHub**: [@Umi-otoko](https://github.com/Umi-otoko)

---

> Este bot opera en **testnet** (dinero ficticio). Nunca ha operado con capital real.  
> Verificar resultados en testnet por al menos 2–4 semanas antes de activar capital real.
