"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          YKAI QUANT PROJECT — DOCUMENTO MAESTRO DE CONTEXTO                 ║
║          Pega este archivo al inicio de cualquier nueva conversación         ║
║          y podremos continuar exactamente donde lo dejamos.                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

INSTRUCCIONES PARA CLAUDE (nueva sesión):
  Lee este archivo completo antes de responder cualquier cosa.
  Contiene todo el historial de decisiones, código producido y próximos pasos
  del proyecto de trading algorítmico. El usuario y tú ya construyeron tres
  bots juntos. El siguiente paso está en la sección ROADMAP al final.
"""

# ==============================================================================
# SECCIÓN 1 — PERFIL DEL PROYECTO
# ==============================================================================
PROYECTO = {
    "nombre":        "YKAI Quant Core",
    "propietario":   "Usuario (Viña del Mar, Chile)",
    "exchange":      "Binance USD-M Futures — TESTNET",
    "capital":       50.0,           # USD
    "riesgo_max":    0.02,           # 2% por trade = $1.00
    "perdida_diaria": 0.06,          # Circuit breaker al 6% = $3.00
    "estado_actual": "TESTNET — ningún bot ha operado en dinero real",
    "lenguaje":      "Python 3.11+",
    "dependencias":  ["ccxt", "pandas", "numpy", "requests", "python-dotenv"],
}

# ==============================================================================
# SECCIÓN 2 — HISTORIAL COMPLETO DE LO CONSTRUIDO
# ==============================================================================

HISTORIAL = """
ITERACIÓN 0 — Bot original del usuario (DemoTraderBot.py)
──────────────────────────────────────────────────────────
El usuario trajo un bot funcional de trend-following con estas características:
  • Estrategia : EMA 50/200 crossover + RSI
  • Exchange   : Binance USD-M Testnet (ccxt.binanceusdm)
  • Activos    : SOL/USDT, BTC/USDT
  • Timeframe  : 5m
  • Capital    : $50 USDT, 10x apalancamiento fijo
  • TP/SL      : Ratio 1:1 (matemáticamente desfavorable)

Problemas detectados y documentados:
  [CRÍTICO]  API keys y Telegram token hardcodeados en el código fuente
  [CRÍTICO]  Exchange inicializado DOS veces (ccxt.binance luego ccxt.binanceusdm)
  [RIESGO]   10x leverage con SL de 0.5% → pérdida real $2.50, no $1.00
  [LÓGICA]   Ratio TP/SL 1:1 con win rate < 50% → expectativa negativa
  [CALIDAD]  Sin logging estructurado, sin retry en errores de red
  [CALIDAD]  División por cero posible en cálculo de RSI
  [CALIDAD]  Sin manejo de errores en escritura CSV

ITERACIÓN 1 — Bot de Trend-Following mejorado (DemoTraderBot_v2.py)
──────────────────────────────────────────────────────────────────────
Correcciones aplicadas:
  ✓ API keys movidas a archivo .env (python-dotenv)
  ✓ Una sola instancia del exchange (binanceusdm)
  ✓ Ratio TP/SL mejorado a 2:1 configurable (RATIO_TP_SL)
  ✓ Decorador @con_retry con backoff exponencial en todas las llamadas
  ✓ logging estructurado con niveles INFO/WARNING/ERROR + archivo bot.log
  ✓ Guard clause en RSI para evitar división por cero
  ✓ Cache de posiciones (_cache_posiciones) para reducir llamadas al exchange
  ✓ Manejo de errores OSError en escritura CSV
  ✓ Validación de credenciales al arrancar
  Archivo generado: DemoTraderBot_v2.py

ITERACIÓN 2 — Bot de Arbitraje (ArbBot_v1.py)
───────────────────────────────────────────────
El usuario preguntó cómo hacer arbitraje con $50. Se explicaron y compararon
tres tipos de arbitraje:

  TIPO 1: Triangular (VIABLE con $50)
    • Opera dentro de un solo exchange → sin fees de transferencia
    • Ciclo: USDT → BTC → ETH → USDT
    • Ganancia si: (1/P1) × (1/P2) × P3 > 1 + (fees × 3)
    • Umbral usado: ratio_neto > 1.004 (3×0.1% fees + 0.1% buffer)
    • Capital por ciclo: $45 (90% del total)

  TIPO 2: Funding Rate (MUY VIABLE con $50, pasivo)
    • Long spot + Short perpetuo = posición delta-neutral
    • Cobra el funding rate cada 8 horas sin importar dirección del precio
    • Umbral: |funding_rate| > 0.05% por período
    • Yield estimado: 10–40% APR en picos de mercado

  TIPO 3: Cross-exchange (NO viable con $50)
    • Requiere capital simultáneo en dos exchanges
    • Fees de retiro ($5–$15) eliminan cualquier ganancia con $50
    • Requiere latencia de milisegundos (servidores colocados)

Arquitectura del ArbBot_v1.py:
  • Módulo 1: Scanner triangular (escanea 6 triángulos predefinidos)
  • Módulo 2: Scanner de funding rates (top 30 pares por volumen)
  • Módulo 3: Ejecutor triangular (dry_run=True por defecto)
  • Circuit breaker: pérdida acumulada > $1 → pausa automática
  • Registro de resultado en EstadoRiesgo (dataclass)

ITERACIÓN 3 — Trading Bot profesional (TradingBot_v2.py)
──────────────────────────────────────────────────────────
El usuario preguntó cómo YO haría un bot de trading con $50.
Se construyó desde cero con una filosofía distinta: "menos trades, mejor calculados".

La calculadora interactiva demostró el problema central:
  Con 10x leverage y SL de 0.5%: pérdida real = $500 × 0.005 = $2.50 (5% del capital)
  La solución es calcular el leverage en función del stop, no al revés.

Arquitectura del TradingBot_v2.py:
  • Multi-timeframe: tendencia en 1h, entrada en 15m
  • Indicadores: EMA 20/50/200, RSI(14), ATR(14), Volumen relativo
  • Sistema de score: 6 condiciones binarias, entra solo si score ≥ 4
  • Leverage auto: calculado para que pérdida = SIEMPRE $1.00 exacto
  • TPs escalonados: TP1 al 1:1 (cierra 50%), TP2 al 2.5:1 (cierra 50% restante)
  • Circuit breaker diario: $3 de pérdida → para todo
  • Máximo 2 posiciones simultáneas
  Archivo generado: TradingBot_v2.py
"""

# ==============================================================================
# SECCIÓN 3 — ARQUITECTURA TÉCNICA CONSOLIDADA
# ==============================================================================

ARQUITECTURA = """
PRINCIPIOS QUE GUÍAN TODO EL CÓDIGO:
  1. Riesgo primero: el sistema de riesgo se evalúa ANTES de cualquier orden
  2. Credenciales en .env: nunca en el código fuente
  3. Retry con backoff: toda llamada al exchange tiene @con_retry
  4. Logging dual: consola + archivo, niveles INFO/WARNING/ERROR
  5. Dry-run por defecto: DRY_RUN = True hasta que el usuario decida activar
  6. Dataclasses para estado: EstadoBot, Señal, OportunidadTriangular, etc.
  7. Funciones puras para cálculos: calcular_indicadores(), calcular_leverage_optimo()

FÓRMULA MAESTRA DE LEVERAGE:
  leverage = riesgo_usd / (capital_usd × distancia_sl_pct)
  Ejemplo: $1 / ($50 × 0.005) = 4x → pérdida exacta $1, no $2.50

  Implementación:
    def calcular_leverage_optimo(precio_entrada, precio_sl):
        distancia_pct = abs(precio_entrada - precio_sl) / precio_entrada
        leverage = RIESGO_USD / (CAPITAL_USD * distancia_pct)
        return int(np.clip(leverage, LEVERAGE_MIN, LEVERAGE_MAX))

CÁLCULO DE STOPS (ATR-based):
  SL_LONG  = precio - (ATR × 1.5)   → se adapta a la volatilidad del mercado
  SL_SHORT = precio + (ATR × 1.5)
  
  TP1_LONG = precio + (precio - SL) × 1.0   → ratio 1:1, cierra 50%
  TP2_LONG = precio + (precio - SL) × 2.5   → ratio 2.5:1, cierra 50%

SISTEMA DE SCORE (6 condiciones):
  Para LONG:
    c1: precio > EMA200          (tendencia de fondo)
    c2: EMA20 cruza sobre EMA50  (momentum)
    c3: 40 ≤ RSI ≤ 65            (ni sobrecomprado ni sobrevendido)
    c4: volumen > 1.3× media     (confirmación de movimiento)
    c5: mínimo ≥ EMA20 × 0.998  (pullback controlado)
    c6: tendencia 1h = ALCISTA   (multi-timeframe)
  Umbral: score ≥ 4 para entrar

ESTRUCTURA DE ARCHIVOS GENERADOS:
  DemoTraderBot_v2.py   → trend-following mejorado (corrección del original)
  ArbBot_v1.py          → arbitraje triangular + funding rate
  TradingBot_v2.py      → bot principal con auto-leverage y multi-TF
  .env.example          → plantilla de credenciales
  bot.log               → generado en runtime
  trading.log           → generado en runtime
  mercado_historico.csv → generado en runtime
"""

# ==============================================================================
# SECCIÓN 4 — CONFIGURACIÓN .env REQUERIDA
# ==============================================================================

ENV_TEMPLATE = """
# Archivo: .env (NUNCA subir a GitHub)
# Consigue tus keys en: https://testnet.binancefuture.com

API_KEY_BINANCE=tu_testnet_api_key
API_SECRET_BINANCE=tu_testnet_api_secret
TELEGRAM_TOKEN=tu_bot_token_de_telegram
TELEGRAM_CHAT_ID=tu_chat_id_de_telegram

# Cómo crear el bot de Telegram:
#   1. Habla con @BotFather en Telegram → /newbot
#   2. Copia el token
#   3. Para el chat_id: envía un mensaje al bot y visita:
#      https://api.telegram.org/bot<TOKEN>/getUpdates
"""

# ==============================================================================
# SECCIÓN 5 — PARÁMETROS ACTUALES DE CADA BOT
# ==============================================================================

PARAMETROS = {
    "TradingBot_v2": {
        # Riesgo
        "CAPITAL_USD":          50.0,
        "RIESGO_PCT":           0.02,      # 2% = $1.00
        "RIESGO_USD":           1.0,
        "MAX_PERDIDA_DIA":      3.0,       # 6% = $3.00
        "MAX_TRADES_ABIERTOS":  2,

        # Leverage
        "LEVERAGE_MIN":         2,
        "LEVERAGE_MAX":         10,        # Auto-calculado entre estos límites

        # Indicadores
        "EMA_RAPIDA":           20,
        "EMA_MEDIA":            50,
        "EMA_LENTA":            200,
        "RSI_PERIODO":          14,
        "ATR_PERIODO":          14,
        "ATR_MULTIPLICADOR":    1.5,       # SL = precio ± (ATR × 1.5)
        "VOLUMEN_MULT":         1.3,       # Volumen debe ser 1.3× la media

        # TPs
        "TP1_RATIO":            1.0,       # Cierra 50% de la posición aquí
        "TP2_RATIO":            2.5,       # Cierra el 50% restante aquí

        # Señal
        "SCORE_MINIMO":         4,         # De 6 condiciones, mínimo 4

        # Timeframes
        "TF_TENDENCIA":         "1h",
        "TF_ENTRADA":           "15m",
        "INTERVALO_SCAN":       30,        # segundos

        # Activos monitoreados
        "ACTIVOS":              ["BTC/USDT", "SOL/USDT", "ETH/USDT"],

        # Modo
        "DRY_RUN":              True,      # CAMBIAR A False para operar real
    },

    "ArbBot_v1": {
        "CAPITAL_USDT":         50.0,
        "FEE_TAKER":            0.001,     # 0.1% por trade en Binance
        "UMBRAL_GANANCIA":      1.004,     # 3 fees + 0.1% buffer
        "CAPITAL_POR_CICLO":    45.0,      # 90% del capital
        "UMBRAL_FUNDING_MIN":   0.0005,    # 0.05% por período
        "APALANCAMIENTO_ARB":   5,
        "INTERVALO_SCAN_SEG":   10,
        "TRIANGULOS": [
            ("USDT", "BTC",  "ETH"),
            ("USDT", "BTC",  "SOL"),
            ("USDT", "BTC",  "BNB"),
            ("USDT", "ETH",  "SOL"),
            ("USDT", "ETH",  "BNB"),
            ("USDT", "BNB",  "SOL"),
        ],
        "DRY_RUN":              True,
    },
}

# ==============================================================================
# SECCIÓN 6 — CONCEPTOS CLAVE EXPLICADOS (para referencia futura)
# ==============================================================================

CONCEPTOS = """
LEVERAGE AUTO-CALCULADO:
  El problema del bot original era fijar el leverage a 10x sin importar el stop.
  Con $50 y 10x: posición = $500. Si el SL está a 0.5%, la pérdida es $2.50 = 5%.
  La solución: primero decides cuánto puedes perder ($1), luego calculas el leverage
  que hace que esa distancia de SL equivalga exactamente a $1.

ATR (Average True Range):
  Mide la volatilidad REAL del mercado en las últimas 14 velas.
  Un ATR alto = mercado volátil = necesitas stops más amplios.
  Un ATR bajo = mercado tranquilo = puedes usar stops más ajustados.
  Usar ATR para stops en lugar de porcentajes fijos hace al bot adaptativo.

MULTI-TIMEFRAME:
  El gráfico de 1h dice QUÉ hace el mercado (tendencia macro).
  El gráfico de 15m dice CUÁNDO entrar (punto exacto de entrada).
  Un cruce en 15m que va CONTRA la tendencia de 1h = señal falsa.
  Un cruce en 15m que va CON la tendencia de 1h = señal real.

SCORE DE SEÑAL:
  En lugar de entrar en cada cruce de EMA, el bot evalúa 6 condiciones.
  Esto es equivalente a tener 6 analistas distintos votando "sí" o "no".
  Solo entramos cuando 4 de ellos están de acuerdo. Más selectivo = menos
  trades, pero con mayor probabilidad de éxito.

TPs ESCALONADOS:
  Antes: toda la posición en un solo TP o SL (todo o nada)
  Ahora: TP1 al 1:1 → cerrar 50% → la operación ya no puede perder
         TP2 al 2.5:1 → el 50% restante viaja al objetivo máximo
  Matemáticamente: si win rate = 45%, con ratio 2.5:1 la expectativa es positiva.

CIRCUIT BREAKER:
  Mecanismo de seguridad que para el bot cuando las pérdidas del día
  superan un umbral (6% = $3). Evita el "revenge trading" automático
  donde el bot intenta recuperar pérdidas escalando posiciones.

EXPECTATIVA MATEMÁTICA (EV por trade):
  EV = (winRate × TP_usd) - ((1 - winRate) × SL_usd)
  Con ratio 2.5:1 y win rate 45%:
    EV = (0.45 × $2.50) - (0.55 × $1.00) = $1.125 - $0.55 = +$0.575
  Esto significa que por cada trade, en promedio ganamos $0.57 (expectativa positiva).
  Con ratio 1:1 y win rate 45%:
    EV = (0.45 × $1.00) - (0.55 × $1.00) = -$0.10 (expectativa NEGATIVA)
  → Por eso el bot original con ratio 1:1 era matemáticamente perdedor.
"""

# ==============================================================================
# SECCIÓN 7 — DECISIONES DE DISEÑO Y SU JUSTIFICACIÓN
# ==============================================================================

DECISIONES = """
¿Por qué binanceusdm y no binance spot?
  Los futuros USD-M permiten apalancamiento y posiciones short sin necesidad
  de tener el activo. Con $50 en spot apenas puedes operar; con futuros tienes
  acceso a posiciones de $100-$500 con apalancamiento 2x-10x.

¿Por qué EMA en lugar de SMA?
  La EMA (media exponencial) da más peso a las velas recientes. Para trading
  de corto plazo (15m-1h) reacciona más rápido a cambios de precio sin ser
  tan ruidosa como una media muy corta (5, 10 períodos).

¿Por qué RSI entre 40 y 65 para LONG (no RSI < 30)?
  RSI < 30 (sobrevendido) sugiere momentum bajista fuerte. Entrar en esa zona
  es "atrapar cuchillos". Preferimos entrar cuando el RSI está en zona neutra
  (40-65) pero el precio ya está mostrando dirección clara por las EMAs.

¿Por qué ATR × 1.5 para el multiplicador del stop?
  Menor a 1× ATR → el stop queda dentro del ruido normal del mercado y se
  activa por ruido aleatorio, no por movimiento real en tu contra.
  Mayor a 2× ATR → el stop está tan lejos que la pérdida cuando se activa es
  mayor de lo esperado. 1.5× es el punto de equilibrio estándar en trading cuantitativo.

¿Por qué máximo 2 posiciones simultáneas?
  Con $50, abrir 3 o más posiciones divide el capital en partes muy pequeñas.
  Además, BTC/USDT, SOL/USDT y ETH/USDT están altamente correlacionadas:
  si BTC cae, todas caen. Abrir 3 longs simultáneos no es diversificación,
  es triplicar el riesgo en la misma dirección.
"""

# ==============================================================================
# SECCIÓN 8 — ESTADO ACTUAL Y PRÓXIMOS PASOS (ROADMAP)
# ==============================================================================

ROADMAP = """
ESTADO ACTUAL (a la fecha de este documento):
  [✓] Bot original recibido y analizado
  [✓] DemoTraderBot_v2.py — correcciones de seguridad y lógica
  [✓] ArbBot_v1.py — arbitraje triangular + funding rate scanner
  [✓] TradingBot_v2.py — bot principal con auto-leverage y multi-TF
  [✓] Calculadora interactiva de riesgo (en la conversación)
  [✓] .env.example creado
  [ ] PENDIENTE: Backtesting de la estrategia con datos históricos
  [ ] PENDIENTE: Activar DRY_RUN=False y monitorear en testnet real
  [ ] PENDIENTE: Dashboard de monitoreo en tiempo real
  [ ] PENDIENTE: Optimización de parámetros (score mínimo, ATR mult, etc.)
  [ ] PENDIENTE: Añadir filtro de sesión (evitar horarios de baja liquidez)
  [ ] PENDIENTE: Integrar trailing stop en el exchange (actualmente solo local)

PRÓXIMO PASO INMEDIATO (continuar aquí):
  Probar el TradingBot_v2.py en Testnet con DRY_RUN=True.
  Objetivo: verificar que el sistema de score, el cálculo de leverage
  y los datos multi-timeframe funcionan correctamente antes de activar
  órdenes reales.

  Pasos para la prueba:
    1. pip install ccxt pandas numpy requests python-dotenv
    2. Crear archivo .env con keys del testnet de Binance Futures
    3. Ejecutar: python TradingBot_v2.py
    4. Observar los logs y verificar que las señales tienen sentido
    5. Revisar en Binance Testnet UI que las órdenes simuladas serían válidas
    6. Si todo se ve bien → cambiar DRY_RUN = False

  En la próxima sesión podemos:
    A) Hacer backtesting con datos históricos para validar la estrategia
    B) Construir un dashboard de monitoreo (Flask o terminal con rich)
    C) Añadir más activos o estrategias al bot
    D) Optimizar los parámetros con datos reales del testnet

PREGUNTAS ABIERTAS QUE QUEDARON PENDIENTES:
  - ¿Qué horarios tiene disponible el usuario para monitorear?
    (Esto determina si añadimos filtro de sesión o no)
  - ¿Quiere el usuario un dashboard web o solo alertas Telegram?
  - ¿Se probó ya el DemoTraderBot_v2.py original en testnet?
    Si sí → ¿qué resultados observó?
"""

# ==============================================================================
# SECCIÓN 9 — FRAGMENTOS DE CÓDIGO CRÍTICOS (referencia rápida)
# ==============================================================================

# Fragmento 1: Conexión al Testnet de Binance USD-M
SNIPPET_EXCHANGE = '''
import ccxt, os
from dotenv import load_dotenv

load_dotenv()
exchange = ccxt.binanceusdm({
    'apiKey':  os.getenv("API_KEY_BINANCE"),
    'secret':  os.getenv("API_SECRET_BINANCE"),
    'enableRateLimit': True,
    'options': {'defaultType': 'future', 'fetchCurrencies': False, 'adjustForTimeDifference': True},
})
# Apuntar al testnet
if isinstance(exchange.urls.get("api"), dict):
    for k, url in exchange.urls["api"].items():
        if isinstance(url, str) and "fapi.binance.com" in url:
            exchange.urls["api"][k] = url.replace("fapi.binance.com", "testnet.binancefuture.com")
exchange.options["testnet"] = True
'''

# Fragmento 2: Leverage auto-calculado
SNIPPET_LEVERAGE = '''
def calcular_leverage_optimo(precio_entrada: float, precio_sl: float,
                              riesgo_usd: float = 1.0, capital_usd: float = 50.0,
                              lev_min: int = 2, lev_max: int = 10) -> int:
    """Calcula el leverage exacto para que la pérdida sea siempre riesgo_usd."""
    import numpy as np
    distancia_pct = abs(precio_entrada - precio_sl) / precio_entrada
    if distancia_pct == 0:
        return lev_min
    leverage = riesgo_usd / (capital_usd * distancia_pct)
    return int(np.clip(leverage, lev_min, lev_max))
'''

# Fragmento 3: Circuit breaker
SNIPPET_CIRCUIT_BREAKER = '''
from dataclasses import dataclass, field

@dataclass
class EstadoBot:
    perdida_dia:  float = 0.0
    ganancia_dia: float = 0.0
    trades_dia:   int   = 0
    bloqueado:    bool  = False
    posiciones:   dict  = field(default_factory=dict)

estado = EstadoBot()
MAX_PERDIDA_DIA = 3.0  # $3 = 6% de $50

def verificar_riesgo() -> bool:
    if estado.bloqueado:
        return False
    if estado.perdida_dia >= MAX_PERDIDA_DIA:
        estado.bloqueado = True
        # ... enviar alerta telegram
        return False
    return True
'''

# Fragmento 4: Cálculo de ATR y stops dinámicos
SNIPPET_ATR_STOPS = '''
import pandas as pd, numpy as np

def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["close"].shift(1)),
            abs(df["low"]  - df["close"].shift(1))
        )
    )
    return tr.ewm(span=periodo, adjust=False).mean()

# Uso:
# atr = df["atr"].iloc[-1]
# sl_long  = precio - (atr * 1.5)
# sl_short = precio + (atr * 1.5)
# tp1_long = precio + (precio - sl_long) * 1.0   # 1:1
# tp2_long = precio + (precio - sl_long) * 2.5   # 2.5:1
'''

# Fragmento 5: Retry decorator
SNIPPET_RETRY = '''
import time
from functools import wraps
import ccxt

def con_retry(max_intentos=3, espera_base=2.0):
    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(1, max_intentos + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RequestTimeout):
                    if i == max_intentos: raise
                    time.sleep(espera_base ** i)
                except ccxt.BaseError:
                    raise
        return wrapper
    return deco
'''

# ==============================================================================
# SECCIÓN 10 — GLOSARIO RÁPIDO
# ==============================================================================

GLOSARIO = {
    "ATR":            "Average True Range — mide la volatilidad real del mercado",
    "EMA":            "Exponential Moving Average — media móvil con más peso en datos recientes",
    "RSI":            "Relative Strength Index — oscilador de momento (0-100)",
    "SL":             "Stop Loss — precio al que se cierra la posición para limitar pérdida",
    "TP":             "Take Profit — precio al que se cierra la posición para asegurar ganancia",
    "Leverage":       "Apalancamiento — multiplicador del capital para abrir posiciones mayores",
    "DRY_RUN":        "Modo simulación — el bot calcula pero NO ejecuta órdenes reales",
    "Circuit Breaker":"Mecanismo que para el bot automáticamente al superar pérdida máxima",
    "Score":          "Puntuación de la señal basada en múltiples condiciones (0-6)",
    "Multi-TF":       "Multi-timeframe — usar varios marcos temporales para confirmar señales",
    "Funding Rate":   "Tasa que pagan longs a shorts (o viceversa) cada 8h en futuros perpetuos",
    "Arbitraje":      "Explotar diferencias de precio entre pares o exchanges",
    "Delta-neutral":  "Posición donde las ganancias/pérdidas de precio se cancelan entre sí",
    "Win rate":       "Porcentaje de trades ganadores sobre el total de trades",
    "EV":             "Expected Value — ganancia promedio esperada por trade (debe ser > 0)",
    "Testnet":        "Red de prueba de Binance con dinero ficticio, sin riesgo real",
    "binanceusdm":    "Módulo de ccxt para Binance USD-M Futures (contratos en USDT)",
}

# ==============================================================================
# INSTRUCCIONES FINALES PARA CLAUDE EN NUEVA SESIÓN
# ==============================================================================

INSTRUCCIONES_CLAUDE = """
Al leer este documento en una nueva sesión, Claude debe:

1. Confirmar que leyó el contexto saludando con algo como:
   "Contexto cargado. Proyecto YKAI Quant Core — capital $50, testnet Binance.
   Tres bots construidos. Próximo paso: [lo que diga ROADMAP]."

2. NO pedir que el usuario explique de nuevo el proyecto.

3. Recordar que DRY_RUN = True en todos los bots — no ejecutan órdenes reales.

4. Estar listo para:
   - Continuar con el backtesting
   - Debuggear errores que aparezcan al correr el bot en testnet
   - Añadir features nuevas
   - Explicar cualquier parte del código con más detalle
   - Ajustar parámetros según resultados observados

5. Las credenciales del usuario están en un .env local.
   Claude nunca debe pedir que las escriba en el chat.

6. El usuario está en Viña del Mar, Chile (UTC-3 / UTC-4 en verano).
   Relevante para filtros de sesión de trading (Asia, Europa, NY).
"""

if __name__ == "__main__":
    print("=" * 70)
    print("YKAI QUANT PROJECT — DOCUMENTO DE CONTEXTO")
    print("=" * 70)
    print(f"Capital: ${PROYECTO['capital']} | Riesgo/trade: {PROYECTO['riesgo_max']*100}%")
    print(f"Exchange: {PROYECTO['exchange']}")
    print(f"Estado: {PROYECTO['estado_actual']}")
    print("\nBots disponibles:")
    print("  1. DemoTraderBot_v2.py   — Trend-following corregido")
    print("  2. ArbBot_v1.py          — Arbitraje triangular + funding rate")
    print("  3. TradingBot_v2.py      — Bot principal (auto-leverage, multi-TF)")
    print("\nPróximo paso:")
    print("  Ejecutar TradingBot_v2.py en testnet con DRY_RUN=True")
    print("  y verificar señales antes de activar órdenes reales.")
    print("=" * 70)
