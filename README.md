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
| `deploy.sh` | Setup automatizado para Oracle Cloud (una sola ejecución) |
| `update.sh` | Pull de GitHub + reinicio del servicio |
| `ykai-bot.service` | Template del servicio systemd (referencia) |

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
| deploy | Oracle Cloud Free Tier: deploy.sh, update.sh, ykai-bot.service, guia IP whitelist |

---

## Deploy 24/7 — Oracle Cloud Free Tier

Oracle Cloud es la opción ideal porque entrega **IP estática fija** — crítico para el whitelist de la API de Binance.

### ¿Por qué Oracle Cloud y no Heroku/Railway?

| | Oracle Cloud | Heroku / Railway |
|---|---|---|
| Costo | **Gratis forever** | Gratis con límites / de pago |
| IP | **Estática fija** | Cambia en cada deploy |
| Binance IP Whitelist | ✅ Compatible | ❌ Problemático |
| RAM | **6 GB** (ARM Ampere A1) | 512 MB – 1 GB |
| Uptime | 24/7 sin dormir | Se duerme sin actividad |

---

### Paso 0 — Crear VM en Oracle Cloud (una sola vez)

1. Ir a [cloud.oracle.com](https://cloud.oracle.com) → **Create Instance**
2. **Shape**: `VM.Standard.A1.Flex` — 1 OCPU, 6 GB RAM *(Always Free)*
3. **Image**: Ubuntu 22.04 LTS
4. **Red**: VCN con subred pública → habilitar IP pública
5. **SSH Key**: subir tu clave pública (`id_rsa.pub`) o generar una nueva
6. Anotar la **IP pública** que te asignan (es fija, no cambia)

**Abrir puertos en el firewall de Oracle:**
- Ir a: VCN → Security Lists → Ingress Rules
- No es necesario abrir puertos adicionales (el bot solo hace llamadas salientes)

**Conectarse al servidor:**
```bash
ssh ubuntu@<TU_IP_ORACLE>
```

---

### Paso 1 — Deploy automático (una sola ejecución)

```bash
# En el servidor Oracle:
curl -O https://raw.githubusercontent.com/Umi-otoko/Ykai-SystemTrading/main/deploy.sh
bash deploy.sh
```

El script hace todo automáticamente:
- Instala Python 3 + dependencias del sistema
- Clona el repositorio desde GitHub
- Crea el virtualenv e instala paquetes Python
- Te pide las credenciales interactivamente (nunca las guarda en git)
- Crea `.env` con `chmod 600` (solo readable por tu usuario)
- Muestra tu IP pública para el whitelist de Binance
- Instala el servicio systemd con auto-restart
- Arranca el bot

---

### Paso 2 — Configurar IP Whitelist en Binance

Después de que `deploy.sh` te muestre tu IP pública:

1. Ir a [Binance API Management](https://www.binance.com/en/my/settings/api-management)
2. Clic en tu API Key → **Edit restrictions**
3. Activar: *"Restrict access to trusted IPs only"*
4. Agregar la IP que mostró el deploy script
5. Guardar

> ⚠️ **Sin whitelist**: tu key es válida desde cualquier IP del mundo — riesgo de seguridad.  
> ✅ **Con whitelist**: solo el servidor Oracle puede usar la key.

---

### Paso 3 — Verificar que el bot corre

```bash
# Estado del servicio
sudo systemctl status ykai-bot

# Logs en tiempo real (Ctrl+C para salir)
tail -f ~/BotTrader/trading.log

# Logs del sistema (incluye crashes y reinicios)
sudo journalctl -u ykai-bot -f
```

---

### Comandos de gestión diaria

```bash
# Ver estado
sudo systemctl status ykai-bot

# Detener el bot
sudo systemctl stop ykai-bot

# Iniciar el bot
sudo systemctl start ykai-bot

# Reiniciar el bot
sudo systemctl restart ykai-bot

# Ver logs recientes
tail -n 100 ~/BotTrader/trading.log

# Historial de PnL
cat ~/BotTrader/historial_pnl.json
```

---

### Actualizar a una nueva versión

Cada vez que hagas `git push` desde tu PC con mejoras:

```bash
# En el servidor Oracle:
bash ~/BotTrader/update.sh
```

El script hace `git pull`, actualiza dependencias y reinicia el servicio automáticamente.

---

### Configurar DRY_RUN en el servidor

El bot tiene `DRY_RUN = True` por defecto. Para activar órdenes reales:

```bash
# Editar el bot en el servidor
nano ~/BotTrader/TradingBot_v2.py
# Cambiar línea: DRY_RUN = False

# Reiniciar
sudo systemctl restart ykai-bot
```

> ⚠️ Dejar en `DRY_RUN = True` mientras estés en testnet. Cambiar solo cuando todo esté verificado.

---

## Contacto

- **GitHub**: [@Umi-otoko](https://github.com/Umi-otoko)

---

> Este bot opera en **testnet** (dinero ficticio). Nunca ha operado con capital real.  
> Verificar resultados en testnet por al menos 2–4 semanas antes de activar capital real.
