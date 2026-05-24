"""
YKAI Quant Core — TradingBot v2
Binance USD-M Futures Testnet | Capital: $50 | Riesgo: $1/trade
DRY_RUN = True por defecto — no ejecuta órdenes hasta que lo cambies
"""

import os
import json
import time
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, date, timezone
from dataclasses import dataclass, field
from functools import wraps
from dotenv import load_dotenv
import ccxt

load_dotenv()

# ==============================================================================
# CONFIGURACIÓN — edita solo esta sección
# ==============================================================================

DRY_RUN             = True       # ← cambiar a False para órdenes reales en testnet

CAPITAL_USD         = 50.0       # capital inicial de referencia
RIESGO_PCT          = 0.02       # 2% del capital actual por trade — COMPOUNDING automático
RIESGO_MIN_USD      = 0.50       # piso: nunca arriesgar menos de $0.50
RIESGO_MAX_USD      = 5.00       # techo: máximo $5.00/trade (limita exposición hasta $250 capital)
MAX_PERDIDA_DIA     = 4.4        # CB — con score 5/6 y filtro 4h, 3 SLs = mercado adverso
MAX_TRADES_ABIERTOS = 3          # 3 posiciones — más oportunidades con anti-correlación Tier S

LEVERAGE_MIN        = 1          # 1x mínimo — respeta el $1 de riesgo en pares volátiles
LEVERAGE_MAX        = 15         # 15x máximo — captura el leverage óptimo en pares de bajo ATR%
TAMANO_MINIMO_USD   = 15.0       # descarta trades con posición < $15 (evita polvo)

EMA_RAPIDA          = 20
EMA_MEDIA           = 50
EMA_LENTA           = 200
RSI_PERIODO         = 14
ATR_PERIODO         = 14
ATR_MULT            = 1.5        # SL más amplio — 1.5× ATR filtra ruido de mercado
VOLUMEN_MULT        = 1.5        # volumen debe ser 1.5× la media (más estricto = menos falsos positivos)
ATR_MIN_PCT         = 0.0012     # ATR mínimo 0.12% del precio — descarta mercados planos/chop

TP1_RATIO           = 1.0        # ratio TP1 (1:1) — cierra TP1_CIERRE_PCT del trade
TP2_RATIO           = 3.0        # ratio TP2 (3:1) — cierra el resto o trailing stop
TP1_CIERRE_PCT      = 0.20       # 20% en TP1, 80% sigue al TP2 3:1 — maximiza ganancia por trade
TRAIL_FACTOR        = 0.4        # trailing legacy (fallback si pos no tiene ATR)
TRAIL_MULT          = 1.5        # trailing dinámico: SL a 1.5× ATR desde mejor precio (doc: 2.0-3.0)
SCORE_MINIMO        = 5          # 5/6 condiciones — solo setups de alta convicción

FAT_FINGER_MAX_PCT  = 0.005      # 0.5% — bloquea si precio señal vs actual difiere más de esto
FLASH_CRASH_PCT     = 0.030      # 3% en 1 vela 15m de BTC = pánico → pausa entradas
FLASH_CRASH_PAUSA_MIN = 30       # minutos de pausa tras flash crash
MAX_DRAWDOWN_PCT    = 0.15       # 15% desde capital pico → circuit breaker total

# BTC Momentum Filter (Holly AI concept: bloquear señales cuando el mercado líder se mueve en contra)
# Si BTC subió >1.5% en la última vela 1h → bloquear SHORTs en todos los activos
# Si BTC bajó >1.5% en la última vela 1h → bloquear LONGs en todos los activos
BTC_MOMENTUM_PCT    = 0.015      # 1.5% en 1h — movimiento fuerte de BTC que arrastra a los alts
CACHE_BTC_MOM_SECS  = 60         # refrescar momentum BTC cada 60s

RR_MINIMO           = 1.8        # ratio R:R mínimo TP2/SL — rechaza trades con potencial insuficiente

TF_TENDENCIA        = "1h"
TF_MACRO            = "4h"       # filtro macro — 4h y 1h deben coincidir en dirección
TF_ENTRADA          = "15m"
CACHE_MACRO_SECS    = 240        # refrescar tendencia 4h cada 4 minutos
INTERVALO_SCAN      = 20         # segundos entre ciclos

SL_GLOBALES_VENTANA = 30         # minutos — ventana para detectar múltiples SLs
SL_GLOBALES_MAX     = 2          # si ≥2 SLs en la ventana → pausa global de nueva entrada
COOLDOWN_SL_SEGUNDOS = 7200      # 2h sin re-entrar al mismo símbolo tras SL (antes 1h)

# Tier S: alta correlación entre sí — máx 1 en la misma dirección simultáneamente
# Tier A: menor correlación con Tier S — pueden coexistir con cualquier Tier S
TIER_S  = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
ACTIVOS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "BNB/USDT"]

# ==============================================================================
# LOGGING
# ==============================================================================

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_file_handler = logging.FileHandler("trading.log", encoding="utf-8")
_file_handler.setLevel(logging.INFO)   # archivo: solo INFO+
_file_handler.setFormatter(_fmt)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.DEBUG)  # consola: DEBUG también (near-misses)
_console_handler.setFormatter(_fmt)

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
log.addHandler(_file_handler)
log.addHandler(_console_handler)

# ==============================================================================
# EXCHANGE — testnet Binance USD-M Futures
# ==============================================================================

def crear_exchange() -> ccxt.binanceusdm:
    api_key    = os.getenv("API_KEY_BINANCE")
    api_secret = os.getenv("API_SECRET_BINANCE")

    if not api_key or not api_secret:
        raise EnvironmentError("Faltan API_KEY_BINANCE o API_SECRET_BINANCE en el .env")

    ex = ccxt.binanceusdm({
        "apiKey":  api_key,
        "secret":  api_secret,
        "enableRateLimit": True,
        "options": {
            "defaultType":             "future",
            "fetchCurrencies":         False,
            "adjustForTimeDifference": True,
        },
    })

    # Redirigir al testnet
    if isinstance(ex.urls.get("api"), dict):
        for k, url in ex.urls["api"].items():
            if isinstance(url, str) and "fapi.binance.com" in url:
                ex.urls["api"][k] = url.replace("fapi.binance.com", "testnet.binancefuture.com")
    ex.options["testnet"] = True

    return ex

exchange = crear_exchange()

# ==============================================================================
# TELEGRAM
# ==============================================================================

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def enviar_telegram(mensaje: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}, timeout=5)
    except Exception:
        pass  # nunca romper el bot por fallo de Telegram

# ==============================================================================
# RETRY DECORATOR
# ==============================================================================

def con_retry(max_intentos: int = 3, espera_base: float = 2.0):
    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for intento in range(1, max_intentos + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RequestTimeout) as e:
                    if intento == max_intentos:
                        raise
                    log.warning("Red: %s — reintento %d/%d en %.0fs", e, intento, max_intentos, espera_base ** intento)
                    time.sleep(espera_base ** intento)
                except ccxt.BaseError:
                    raise
        return wrapper
    return deco

# ==============================================================================
# ESTADO Y DATACLASSES
# ==============================================================================

@dataclass
class Posicion:
    simbolo:    str
    direccion:  str          # "LONG" | "SHORT"
    precio_entrada: float
    precio_sl:  float
    precio_tp1: float
    precio_tp2: float
    leverage:   int
    tamano_usd: float
    tp1_cerrado:  bool  = False
    mejor_precio: float = 0.0   # mejor precio visto tras TP1 (para trailing stop)
    atr:          float = 0.0   # ATR en entrada — usado por trailing stop dinámico
    timestamp:    datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

@dataclass
class Senal:
    simbolo:    str
    direccion:  str
    score:      int
    precio:     float
    sl:         float
    tp1:        float
    tp2:        float
    leverage:   int
    atr:        float

@dataclass
class EstadoBot:
    perdida_dia:    float = 0.0
    ganancia_dia:   float = 0.0
    trades_dia:     int   = 0
    bloqueado:      bool  = False
    fecha:          date  = field(default_factory=date.today)
    posiciones:     dict  = field(default_factory=dict)   # simbolo → Posicion
    cooldowns:      dict  = field(default_factory=dict)   # simbolo → datetime fin cooldown
    capital_actual: float = CAPITAL_USD  # capital real acumulado — se actualiza con cada trade
    capital_pico:   float = CAPITAL_USD  # máximo capital histórico — base para calcular drawdown

ESTADO_ARCHIVO       = "estado_bot.json"

def calcular_riesgo_actual() -> float:
    """Retorna el riesgo en USD para el próximo trade según el capital actual.
    Usa RIESGO_PCT (2%) del capital real acumulado, con piso y techo.
    Ejemplo: $50 capital → $1.00 riesgo | $100 capital → $2.00 riesgo."""
    riesgo = estado.capital_actual * RIESGO_PCT
    return round(max(RIESGO_MIN_USD, min(riesgo, RIESGO_MAX_USD)), 2)

# Caché de tendencia 4h (no llamar a la API en cada ciclo de 20s)
_cache_macro: dict = {}   # simbolo → (datetime, "ALCISTA"|"BAJISTA"|"NEUTRAL")

# Registro de SLs recientes para pausa global
_sl_recientes: list = []  # lista de datetime de SLs

# Control spam log CB
_ultimo_aviso_cb: datetime = datetime(2000, 1, 1)

# Flash Crash Pauser — entradas bloqueadas hasta este timestamp
_flash_crash_hasta: datetime = datetime(2000, 1, 1)

# Caché de momentum BTC 1h (cuánto se movió BTC en la última vela de 1h)
_cache_btc_mom: dict = {}   # "btc_1h" → (datetime, float % cambio)

# ==============================================================================
# PERSISTENCIA DE ESTADO
# ==============================================================================

def guardar_estado(est: "EstadoBot") -> None:
    try:
        data = {
            "fecha":          est.fecha.isoformat(),
            "perdida_dia":    est.perdida_dia,
            "ganancia_dia":   est.ganancia_dia,
            "trades_dia":     est.trades_dia,
            "bloqueado":      est.bloqueado,
            "capital_actual": est.capital_actual,
            "capital_pico":   est.capital_pico,
            "posiciones": {
                sym: {
                    "simbolo":       p.simbolo,
                    "direccion":     p.direccion,
                    "precio_entrada":p.precio_entrada,
                    "precio_sl":     p.precio_sl,
                    "precio_tp1":    p.precio_tp1,
                    "precio_tp2":    p.precio_tp2,
                    "leverage":      p.leverage,
                    "tamano_usd":    p.tamano_usd,
                    "tp1_cerrado":   p.tp1_cerrado,
                    "mejor_precio":  p.mejor_precio,
                    "atr":           p.atr,
                    "timestamp":     p.timestamp.isoformat(),
                }
                for sym, p in est.posiciones.items()
            },
            "cooldowns": {
                sym: dt.isoformat()
                for sym, dt in est.cooldowns.items()
            },
        }
        with open(ESTADO_ARCHIVO, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning("No se pudo guardar estado: %s", e)

def cargar_estado() -> "EstadoBot":
    if not os.path.exists(ESTADO_ARCHIVO):
        return EstadoBot()
    try:
        with open(ESTADO_ARCHIVO) as f:
            data = json.load(f)

        fecha_guardada = date.fromisoformat(data["fecha"])
        hoy = date.today()

        # Si el archivo es de otro día, empezar contadores limpios pero conservar posiciones
        est = EstadoBot()
        est.fecha = hoy
        # capital_actual y capital_pico se cargan siempre (sobreviven al cambio de día)
        est.capital_actual = data.get("capital_actual", CAPITAL_USD)
        est.capital_pico   = data.get("capital_pico",   est.capital_actual)

        if fecha_guardada == hoy:
            est.perdida_dia  = data.get("perdida_dia", 0.0)
            est.ganancia_dia = data.get("ganancia_dia", 0.0)
            est.trades_dia   = data.get("trades_dia", 0)
            est.bloqueado    = data.get("bloqueado", False)

        for sym, pd_ in data.get("posiciones", {}).items():
            est.posiciones[sym] = Posicion(
                simbolo        = pd_["simbolo"],
                direccion      = pd_["direccion"],
                precio_entrada = pd_["precio_entrada"],
                precio_sl      = pd_["precio_sl"],
                precio_tp1     = pd_["precio_tp1"],
                precio_tp2     = pd_["precio_tp2"],
                leverage       = pd_["leverage"],
                tamano_usd     = pd_["tamano_usd"],
                tp1_cerrado    = pd_["tp1_cerrado"],
                mejor_precio   = pd_.get("mejor_precio", 0.0),
                atr            = pd_.get("atr", 0.0),
                timestamp      = datetime.fromisoformat(pd_["timestamp"]),
            )

        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        for sym, dt_str in data.get("cooldowns", {}).items():
            fin = datetime.fromisoformat(dt_str)
            if fin > ahora:
                est.cooldowns[sym] = fin

        # Validación: si el estado guardado tenía más posiciones que el límite actual,
        # conservar solo las más recientes (evita el bug de "5 posiciones con MAX=2")
        if len(est.posiciones) > MAX_TRADES_ABIERTOS:
            todas = sorted(est.posiciones.items(), key=lambda x: x[1].timestamp, reverse=True)
            descartadas = [s for s, _ in todas[MAX_TRADES_ABIERTOS:]]
            est.posiciones = dict(todas[:MAX_TRADES_ABIERTOS])
            log.warning("Estado cargado con %d posiciones (máximo %d) — descartadas: %s",
                        len(todas), MAX_TRADES_ABIERTOS, ", ".join(descartadas))

        if est.posiciones:
            log.info("Estado recuperado: %d posiciones abiertas | pérdida día: $%.2f",
                     len(est.posiciones), est.perdida_dia)
            for sym, p in est.posiciones.items():
                log.info("  Posición recuperada: %s %s @ %.4f | SL %.4f | TP2 %.4f | TP1 cerrado: %s",
                         p.direccion, sym, p.precio_entrada, p.precio_sl, p.precio_tp2, p.tp1_cerrado)
        return est

    except Exception as e:
        log.warning("No se pudo cargar estado anterior: %s — iniciando limpio", e)
        return EstadoBot()

estado = EstadoBot()  # se reemplaza en main() con cargar_estado()

def resetear_si_nuevo_dia() -> None:
    hoy = date.today()
    if estado.fecha != hoy:
        # Guardar resumen del día antes de resetear
        _guardar_historial_dia()
        estado.perdida_dia  = 0.0
        estado.ganancia_dia = 0.0
        estado.trades_dia   = 0
        estado.bloqueado    = False
        estado.fecha        = hoy
        log.info("Nuevo día — contadores reseteados")

def _guardar_historial_dia() -> None:
    historial_archivo = "historial_pnl.json"
    registro = {
        "fecha":           estado.fecha.isoformat(),
        "ganancia":        round(estado.ganancia_dia, 2),
        "perdida":         round(estado.perdida_dia, 2),
        "neto":            round(estado.ganancia_dia - estado.perdida_dia, 2),
        "trades":          estado.trades_dia,
        "capital_cierre":  round(estado.capital_actual, 2),  # capital al cierre del día
        "capital_pico":    round(estado.capital_pico, 2),    # máximo alcanzado ese día
    }
    try:
        historial = []
        if os.path.exists(historial_archivo):
            with open(historial_archivo) as f:
                historial = json.load(f)
        historial.append(registro)
        with open(historial_archivo, "w") as f:
            json.dump(historial, f, indent=2)
        log.info("Resumen día %s → ganancia: +$%.2f | pérdida: -$%.2f | neto: $%.2f | trades: %d",
                 registro["fecha"], registro["ganancia"], registro["perdida"],
                 registro["neto"], registro["trades"])
        enviar_telegram(
            f"📅 Cierre día {registro['fecha']}\n"
            f"Ganancia: +${registro['ganancia']:.2f}\n"
            f"Pérdida:  -${registro['perdida']:.2f}\n"
            f"Neto:      ${registro['neto']:+.2f}\n"
            f"Trades:    {registro['trades']}"
        )
    except Exception as e:
        log.warning("No se pudo guardar historial: %s", e)

def calcular_kelly_empirico() -> float:
    """Kelly Criterion empírico basado en el historial diario de P&L.
    f* = WR - (1-WR)/RR  donde WR=win rate y RR=ganancia_media/perdida_media.
    Requiere mínimo 5 días de historial para ser estadísticamente relevante."""
    historial_archivo = "historial_pnl.json"
    if not os.path.exists(historial_archivo):
        return RIESGO_PCT
    try:
        with open(historial_archivo) as f:
            historial = json.load(f)
        if len(historial) < 5:
            return RIESGO_PCT   # dataset insuficiente — mantener 2% conservador
        dias_gan = sum(1 for d in historial if d["neto"] > 0)
        wr       = dias_gan / len(historial)
        ganancias = [d["ganancia"] for d in historial if d["ganancia"] > 0]
        perdidas  = [d["perdida"]  for d in historial if d["perdida"]  > 0]
        if not ganancias or not perdidas:
            return RIESGO_PCT
        rr    = (sum(ganancias)/len(ganancias)) / (sum(perdidas)/len(perdidas))
        kelly = wr - (1 - wr) / rr
        # Usar Quarter-Kelly (más conservador) — práctica institucional estándar
        return round(max(0.005, min(kelly * 0.25, 0.10)), 4)
    except Exception:
        return RIESGO_PCT

def obtener_momentum_btc_1h() -> float:
    """% de cambio de BTC en la última vela cerrada de 1h (cacheado 60s).
    Positivo = BTC subiendo | Negativo = BTC bajando.
    Concepto Holly AI: bloquear señales cuando el mercado líder se mueve en contra."""
    from datetime import timedelta
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    cached = _cache_btc_mom.get("btc_1h")
    if cached:
        ts, valor = cached
        if (ahora - ts).total_seconds() < CACHE_BTC_MOM_SECS:
            return valor
    try:
        df     = obtener_velas("BTC/USDT", TF_TENDENCIA, 3)
        curr   = df.iloc[-1]
        prev   = df.iloc[-2]
        cambio = (float(curr["close"]) - float(prev["close"])) / float(prev["close"])
    except Exception:
        cambio = 0.0
    _cache_btc_mom["btc_1h"] = (ahora, cambio)
    return cambio

def calcular_metricas_historial() -> dict:
    """Sharpe, Sortino y win rate desde el historial diario de P&L.
    Sharpe = retorno_medio / std × sqrt(365) — mide calidad ajustada al riesgo.
    Sortino = retorno_medio / std_downside × sqrt(365) — solo penaliza días negativos.
    Requiere mínimo 5 días de historial."""
    historial_archivo = "historial_pnl.json"
    if not os.path.exists(historial_archivo):
        return {}
    try:
        with open(historial_archivo) as f:
            historial = json.load(f)
        if len(historial) < 5:
            return {"dias": len(historial)}
        cap_ref  = historial[0].get("capital_cierre", CAPITAL_USD) or CAPITAL_USD
        retornos = np.array([d["neto"] / cap_ref for d in historial])
        media    = float(np.mean(retornos))
        std      = float(np.std(retornos))
        sharpe   = round(media / std * np.sqrt(365), 2) if std > 0 else 0.0
        downside = retornos[retornos < 0]
        std_down = float(np.std(downside)) if len(downside) > 0 else std
        sortino  = round(media / std_down * np.sqrt(365), 2) if std_down > 0 else 0.0
        wr       = sum(1 for r in retornos if r > 0) / len(retornos)
        return {
            "dias":             len(historial),
            "win_rate":         round(wr, 3),
            "retorno_dia_pct":  round(media * 100, 3),
            "sharpe":           sharpe,
            "sortino":          sortino,
            "mejor_dia_pct":    round(float(np.max(retornos)) * 100, 2),
            "peor_dia_pct":     round(float(np.min(retornos)) * 100, 2),
        }
    except Exception as e:
        log.debug("Error métricas historial: %s", e)
        return {}

def _actualizar_flash_crash() -> None:
    """Detecta pánico en BTC (>3% en 1 vela 15m) y activa pausa de entradas."""
    global _flash_crash_hasta
    from datetime import timedelta
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    if ahora < _flash_crash_hasta:
        return  # ya estamos en pausa — no re-verificar hasta que expire
    try:
        df   = obtener_velas("BTC/USDT", TF_ENTRADA, 3)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        cambio_pct = abs(float(curr["close"]) - float(prev["close"])) / float(prev["close"])
        if cambio_pct >= FLASH_CRASH_PCT:
            _flash_crash_hasta = ahora + timedelta(minutes=FLASH_CRASH_PAUSA_MIN)
            direccion = "🚀 PUMP" if float(curr["close"]) > float(prev["close"]) else "💥 DUMP"
            msg = (f"⚡ Flash Crash BTC — {direccion} {cambio_pct*100:.1f}% en 15m\n"
                   f"Entradas pausadas {FLASH_CRASH_PAUSA_MIN}min hasta {_flash_crash_hasta.strftime('%H:%M UTC')}")
            log.warning(msg)
            enviar_telegram(msg)
    except Exception as e:
        log.debug("Error verificando flash crash BTC: %s", e)

def verificar_riesgo() -> bool:
    global _ultimo_aviso_cb
    resetear_si_nuevo_dia()

    if estado.bloqueado:
        # Anti-spam: logear el aviso solo 1 vez cada 30 minutos
        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        if (ahora - _ultimo_aviso_cb).total_seconds() > 1800:
            log.warning("Bot bloqueado — circuit breaker activo (pérdida: $%.2f)", estado.perdida_dia)
            _ultimo_aviso_cb = ahora
        return False

    if estado.perdida_dia >= MAX_PERDIDA_DIA:
        estado.bloqueado = True
        msg = f"⛔ CIRCUIT BREAKER — pérdida diaria ${estado.perdida_dia:.2f} ≥ ${MAX_PERDIDA_DIA}. Bot pausado hasta mañana."
        log.warning(msg)
        enviar_telegram(msg)
        _ultimo_aviso_cb = datetime.now(timezone.utc).replace(tzinfo=None)
        return False

    # Max Drawdown: si el capital cayó >15% desde su pico histórico → CB total
    if estado.capital_pico > 0:
        drawdown = (estado.capital_pico - estado.capital_actual) / estado.capital_pico
        if drawdown >= MAX_DRAWDOWN_PCT:
            estado.bloqueado = True
            msg = (f"⛔ MAX DRAWDOWN — capital ${estado.capital_actual:.2f} cayó "
                   f"{drawdown*100:.1f}% desde pico ${estado.capital_pico:.2f}. "
                   f"Bot pausado para proteger el capital restante.")
            log.warning(msg)
            enviar_telegram(msg)
            _ultimo_aviso_cb = datetime.now(timezone.utc).replace(tzinfo=None)
            return False

    if len(estado.posiciones) >= MAX_TRADES_ABIERTOS:
        return False  # silencioso

    # Flash Crash Pauser: pausar nuevas entradas si BTC tuvo un movimiento brusco
    ahora_check = datetime.now(timezone.utc).replace(tzinfo=None)
    if ahora_check < _flash_crash_hasta:
        log.debug("Flash Crash Pauser activo — nuevas entradas bloqueadas hasta %s",
                  _flash_crash_hasta.strftime("%H:%M UTC"))
        return False

    # Pausa global: si hay ≥ SL_GLOBALES_MAX SLs en los últimos SL_GLOBALES_VENTANA min
    if _pausa_global_activa():
        log.debug("Pausa global activa — %d SLs en los últimos %dmin", len(_sl_recientes), SL_GLOBALES_VENTANA)
        return False

    return True

def _pausa_global_activa() -> bool:
    """True si se detectaron múltiples SLs recientes — señal de mercado adverso."""
    from datetime import timedelta
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    ventana = ahora - timedelta(minutes=SL_GLOBALES_VENTANA)
    recientes = [t for t in _sl_recientes if t > ventana]
    return len(recientes) >= SL_GLOBALES_MAX

def _registrar_sl_global() -> None:
    """Registrar un SL para el detector de múltiples pérdidas."""
    _sl_recientes.append(datetime.now(timezone.utc).replace(tzinfo=None))
    # Mantener solo últimas 24h para no crecer indefinidamente
    from datetime import timedelta
    corte = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    while _sl_recientes and _sl_recientes[0] < corte:
        _sl_recientes.pop(0)

def en_cooldown(simbolo: str) -> bool:
    fin = estado.cooldowns.get(simbolo)
    if fin and datetime.now(timezone.utc).replace(tzinfo=None) < fin:
        return True
    return False

def activar_cooldown(simbolo: str) -> None:
    from datetime import timedelta
    fin = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=COOLDOWN_SL_SEGUNDOS)
    estado.cooldowns[simbolo] = fin
    log.info("Cooldown activado en %s por %dh — no re-entra hasta %s",
             simbolo, COOLDOWN_SL_SEGUNDOS // 3600, fin.strftime("%H:%M"))

# ==============================================================================
# CÁLCULOS DE INDICADORES
# ==============================================================================

@con_retry()
def obtener_velas(simbolo: str, timeframe: str, limite: int = 250) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(simbolo, timeframe, limit=limite)
    df  = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("ts")

def calcular_ema(serie: pd.Series, periodo: int) -> pd.Series:
    return serie.ewm(span=periodo, adjust=False).mean()

def calcular_rsi(serie: pd.Series, periodo: int = 14) -> pd.Series:
    delta = serie.diff()
    ganancia = delta.clip(lower=0)
    perdida  = (-delta).clip(lower=0)
    media_gan = ganancia.ewm(span=periodo, adjust=False).mean()
    media_per = perdida.ewm(span=periodo, adjust=False).mean()
    denominador = media_per.replace(0, np.nan)
    rs  = media_gan / denominador
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"]  - df["close"].shift(1)).abs(),
        ),
    )
    return tr.ewm(span=periodo, adjust=False).mean()

def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"]  = calcular_ema(df["close"], EMA_RAPIDA)
    df["ema50"]  = calcular_ema(df["close"], EMA_MEDIA)
    df["ema200"] = calcular_ema(df["close"], EMA_LENTA)
    df["rsi"]    = calcular_rsi(df["close"], RSI_PERIODO)
    df["atr"]    = calcular_atr(df, ATR_PERIODO)
    df["vol_med"]= df["volume"].rolling(20).mean()
    return df

# ==============================================================================
# TENDENCIA EN TIMEFRAME ALTO (1h)
# ==============================================================================

def obtener_tendencia_1h(simbolo: str) -> str:
    """Retorna 'ALCISTA', 'BAJISTA' o 'NEUTRAL' según EMA20/50/200 en 1h."""
    try:
        df = calcular_indicadores(obtener_velas(simbolo, TF_TENDENCIA, 250))
        u  = df.iloc[-1]
        if u["ema20"] > u["ema50"] > u["ema200"]:
            return "ALCISTA"
        if u["ema20"] < u["ema50"] < u["ema200"]:
            return "BAJISTA"
        return "NEUTRAL"
    except Exception as e:
        log.warning("Error tendencia 1h %s: %s", simbolo, e)
        return "NEUTRAL"

def obtener_tendencia_macro(simbolo: str) -> str:
    """Tendencia en 4h con caché — no llama a la API en cada ciclo de 20s."""
    from datetime import timedelta
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    cached = _cache_macro.get(simbolo)
    if cached:
        ts, valor = cached
        if (ahora - ts).total_seconds() < CACHE_MACRO_SECS:
            return valor
    try:
        df = calcular_indicadores(obtener_velas(simbolo, TF_MACRO, 100))
        u  = df.iloc[-1]
        if u["ema20"] > u["ema50"] > u["ema200"]:
            tendencia = "ALCISTA"
        elif u["ema20"] < u["ema50"] < u["ema200"]:
            tendencia = "BAJISTA"
        else:
            tendencia = "NEUTRAL"
    except Exception as e:
        log.warning("Error tendencia 4h %s: %s", simbolo, e)
        tendencia = "NEUTRAL"
    _cache_macro[simbolo] = (ahora, tendencia)
    return tendencia

# ==============================================================================
# CÁLCULO DE LEVERAGE Y STOPS
# ==============================================================================

def calcular_leverage_optimo(precio_entrada: float, precio_sl: float) -> int:
    """Leverage que hace PnL(SL) = riesgo_actual exactamente."""
    distancia_pct = abs(precio_entrada - precio_sl) / precio_entrada
    if distancia_pct == 0:
        return LEVERAGE_MIN
    riesgo = calcular_riesgo_actual()
    leverage = riesgo / (estado.capital_actual * distancia_pct)
    return int(np.clip(leverage, LEVERAGE_MIN, LEVERAGE_MAX))

# ==============================================================================
# GENERACIÓN DE SEÑAL EN 15m
# ==============================================================================

def evaluar_senal(simbolo: str) -> Senal | None:
    tendencia_1h = obtener_tendencia_1h(simbolo)

    try:
        df = calcular_indicadores(obtener_velas(simbolo, TF_ENTRADA, 250))
    except Exception as e:
        log.warning("Error velas 15m %s: %s", simbolo, e)
        return None

    if len(df) < EMA_LENTA + 5:
        return None

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    precio = float(curr["close"])
    atr    = float(curr["atr"])

    # ── FILTRO ATR MÍNIMO ────────────────────────────────────────────────────
    # Mercados con ATR < 0.12% del precio son demasiado planos — las señales
    # no tienen momentum real y el SL se toca por ruido aleatorio
    atr_pct = atr / precio
    if atr_pct < ATR_MIN_PCT:
        log.debug("ATR plano %s (%.3f%%) < %.3f%% mínimo — mercado sin momentum, señal descartada",
                  simbolo, atr_pct * 100, ATR_MIN_PCT * 100)
        return None

    # Tendencia macro (4h) — con caché para no sobrecargar la API
    tendencia_4h = obtener_tendencia_macro(simbolo)

    # BTC Momentum Filter (Holly AI concept) — cacheado 60s
    # Si BTC se mueve fuerte en 1h, los alts lo siguen → no ir en contra del líder
    momentum_btc = obtener_momentum_btc_1h() if simbolo != "BTC/USDT" else 0.0
    btc_pump     = momentum_btc >  BTC_MOMENTUM_PCT   # BTC subiendo fuerte → no SHORTs
    btc_dump     = momentum_btc < -BTC_MOMENTUM_PCT   # BTC bajando fuerte → no LONGs
    if btc_pump:
        log.debug("BTC momentum PUMP +%.2f%% — SHORTs en %s bloqueados", momentum_btc*100, simbolo)
    if btc_dump:
        log.debug("BTC momentum DUMP %.2f%% — LONGs en %s bloqueados", momentum_btc*100, simbolo)

    # ── LONG ────────────────────────────────────────────────────────────────
    sl_long  = precio - atr * ATR_MULT
    tp1_long = precio + (precio - sl_long) * TP1_RATIO
    tp2_long = precio + (precio - sl_long) * TP2_RATIO

    # gap EMA para c2: cruce válido solo si hay separación real (evita cruces de ruido)
    ema_gap_long = (curr["ema20"] - curr["ema50"]) / curr["ema50"]

    c1 = precio > curr["ema200"]
    # c2: cruce EMA20 sobre EMA50 + separación mínima 0.02% (filtra cruces "de roce")
    c2 = (prev["ema20"] <= prev["ema50"]) and (curr["ema20"] > curr["ema50"]) and (ema_gap_long >= 0.0002)
    # c3: RSI en zona neutral-alcista — evita entrar cerca de sobrecompra (antes 40-65)
    c3 = 42 <= curr["rsi"] <= 60
    c4 = curr["volume"] > curr["vol_med"] * VOLUMEN_MULT
    # c5: pullback controlado + vela alcista (close > open) — confirma dirección
    c5 = (curr["low"] >= curr["ema20"] * 0.998) and (curr["close"] > curr["open"])
    # c6: doble confirmación — 1h Y 4h alcistas (evita operar contra la macro)
    c6 = tendencia_1h == "ALCISTA" and tendencia_4h == "ALCISTA"

    score_long = sum([c1, c2, c3, c4, c5, c6])

    if score_long >= SCORE_MINIMO:
        if btc_dump:
            log.debug("LONG %s score %d/6 bloqueado — BTC dump %.2f%% en 1h", simbolo, score_long, momentum_btc*100)
        else:
            rr_long = (tp2_long - precio) / (precio - sl_long) if (precio - sl_long) > 0 else 0
            if rr_long < RR_MINIMO:
                log.debug("R:R insuficiente LONG %s (%.1f:1 < %.1f:1 mínimo) — señal rechazada",
                          simbolo, rr_long, RR_MINIMO)
            else:
                lev = calcular_leverage_optimo(precio, sl_long)
                log.info("SEÑAL LONG %s | score %d/6 | 1h:%s 4h:%s | BTC mom:%.1f%% | precio %.4f | SL %.4f | TP1 %.4f | R:R %.1f:1 | lev %dx",
                         simbolo, score_long, tendencia_1h, tendencia_4h, momentum_btc*100, precio, sl_long, tp1_long, rr_long, lev)
                return Senal(simbolo, "LONG", score_long, precio, sl_long, tp1_long, tp2_long, lev, atr)
    elif score_long == SCORE_MINIMO - 1:
        log.debug("Cerca LONG %s | score %d/6 | 1h:%s 4h:%s | RSI %.1f",
                  simbolo, score_long, tendencia_1h, tendencia_4h, curr["rsi"])

    # ── SHORT ───────────────────────────────────────────────────────────────
    sl_short  = precio + atr * ATR_MULT
    tp1_short = precio - (sl_short - precio) * TP1_RATIO
    tp2_short = precio - (sl_short - precio) * TP2_RATIO

    # gap EMA para d2: cruce válido solo si hay separación real
    ema_gap_short = (curr["ema50"] - curr["ema20"]) / curr["ema50"]

    d1 = precio < curr["ema200"]
    # d2: cruce EMA20 bajo EMA50 + separación mínima 0.02% (filtra cruces de ruido en chop)
    d2 = (prev["ema20"] >= prev["ema50"]) and (curr["ema20"] < curr["ema50"]) and (ema_gap_short >= 0.0002)
    # d3: RSI en zona neutral-bajista — RSI > 55 indica momentum aún alcista, evitar SHORT
    d3 = 38 <= curr["rsi"] <= 55
    d4 = curr["volume"] > curr["vol_med"] * VOLUMEN_MULT
    # d5: precio pegado a EMA20 + vela bajista (close < open) — confirma dirección
    d5 = (curr["high"] <= curr["ema20"] * 1.002) and (curr["close"] < curr["open"])
    # d6: doble confirmación — 1h Y 4h bajistas (evita shorts en tendencia macro alcista)
    d6 = tendencia_1h == "BAJISTA" and tendencia_4h == "BAJISTA"

    score_short = sum([d1, d2, d3, d4, d5, d6])

    if score_short >= SCORE_MINIMO:
        if btc_pump:
            log.debug("SHORT %s score %d/6 bloqueado — BTC pump +%.2f%% en 1h", simbolo, score_short, momentum_btc*100)
        else:
            rr_short = (precio - tp2_short) / (sl_short - precio) if (sl_short - precio) > 0 else 0
            if rr_short < RR_MINIMO:
                log.debug("R:R insuficiente SHORT %s (%.1f:1 < %.1f:1 mínimo) — señal rechazada",
                          simbolo, rr_short, RR_MINIMO)
            else:
                lev = calcular_leverage_optimo(precio, sl_short)
                log.info("SEÑAL SHORT %s | score %d/6 | 1h:%s 4h:%s | BTC mom:%.1f%% | precio %.4f | SL %.4f | TP1 %.4f | R:R %.1f:1 | lev %dx",
                         simbolo, score_short, tendencia_1h, tendencia_4h, momentum_btc*100, precio, sl_short, tp1_short, rr_short, lev)
                return Senal(simbolo, "SHORT", score_short, precio, sl_short, tp1_short, tp2_short, lev, atr)
    elif score_short == SCORE_MINIMO - 1:
        log.debug("Cerca SHORT %s | score %d/6 | 1h:%s 4h:%s | RSI %.1f",
                  simbolo, score_short, tendencia_1h, tendencia_4h, curr["rsi"])

    return None

# ==============================================================================
# EJECUTAR ENTRADA
# ==============================================================================

@con_retry()
def _set_leverage(simbolo: str, leverage: int) -> None:
    exchange.set_leverage(leverage, simbolo)

@con_retry()
def _crear_orden_market(simbolo: str, lado: str, cantidad: float) -> dict:
    return exchange.create_order(simbolo, "market", lado, cantidad)

def _puede_abrir_por_correlacion(simbolo: str, direccion: str) -> bool:
    """Anti-correlación Tier S: máximo 1 trade de BTC/ETH/SOL en la misma dirección.
    Evita el desastre de 3 Tier S correlacionados que se van al SL juntos."""
    if simbolo not in TIER_S:
        return True  # Tier A: sin restricción de correlación
    tier_s_activos = sum(
        1 for sym, pos in estado.posiciones.items()
        if sym in TIER_S and pos.direccion == direccion
    )
    if tier_s_activos >= 1:
        log.debug("Anti-correlación: ya hay %d Tier S en %s — %s descartado",
                  tier_s_activos, direccion, simbolo)
        return False
    return True

def abrir_posicion(senal: Senal) -> None:
    if simbolo_ya_abierto(senal.simbolo):
        return
    if en_cooldown(senal.simbolo):
        log.info("Cooldown activo en %s — señal ignorada", senal.simbolo)
        return
    if not _puede_abrir_por_correlacion(senal.simbolo, senal.direccion):
        return

    # Fat Finger Constraint: verificar que el precio no se movió >0.5% desde la señal
    # Evita fills en precios malos por delay entre señal y ejecución
    try:
        precio_ahora  = precio_actual(senal.simbolo)
        desvio_pct    = abs(precio_ahora - senal.precio) / senal.precio
        if desvio_pct > FAT_FINGER_MAX_PCT:
            log.warning("🫰 Fat Finger bloqueado %s — señal %.4f vs actual %.4f (%.2f%% > %.1f%% máx)",
                        senal.simbolo, senal.precio, precio_ahora,
                        desvio_pct * 100, FAT_FINGER_MAX_PCT * 100)
            return
    except Exception as e:
        log.debug("Error Fat Finger check %s: %s — continuando", senal.simbolo, e)

    # Tamaño exacto que hace PnL(SL) = riesgo_actual (compounding)
    # tamano = riesgo / distancia_sl_pct  →  SL hit = distancia_sl_pct × tamano = riesgo_actual
    riesgo_usd       = calcular_riesgo_actual()
    distancia_sl_pct = abs(senal.precio - senal.sl) / senal.precio
    tamano_usd       = riesgo_usd / distancia_sl_pct if distancia_sl_pct > 0 else 0.0
    # No exceder el capital real disponible apalancado
    tamano_usd       = min(tamano_usd, estado.capital_actual * senal.leverage)

    if tamano_usd < TAMANO_MINIMO_USD:
        log.debug("Posición demasiado pequeña en %s (%.2f USD) — señal ignorada", senal.simbolo, tamano_usd)
        return

    cantidad = tamano_usd / senal.precio
    lado     = "buy" if senal.direccion == "LONG" else "sell"

    if DRY_RUN:
        log.info("[DRY-RUN] ABRIR %s %s | qty=%.4f | precio=%.4f | lev=%dx | SL=%.4f | TP1=%.4f | TP2=%.4f | riesgo=$%.2f",
                 senal.direccion, senal.simbolo, cantidad, senal.precio, senal.leverage,
                 senal.sl, senal.tp1, senal.tp2, riesgo_usd)
        ganancia_tp1   = tamano_usd * abs(senal.tp1 - senal.precio) / senal.precio * TP1_CIERRE_PCT
        ganancia_tp2   = tamano_usd * abs(senal.tp2 - senal.precio) / senal.precio * (1 - TP1_CIERRE_PCT)
        msg = (
            f"📊 [DRY-RUN] {senal.direccion} {senal.simbolo}\n"
            f"Precio: {senal.precio:.4f} | Lev: {senal.leverage}x | Score: {senal.score}/6\n"
            f"Capital: ${estado.capital_actual:.2f} | Riesgo: ${riesgo_usd:.2f} ({RIESGO_PCT*100:.0f}%)\n"
            f"SL:  {senal.sl:.4f}  → máx -${riesgo_usd:.2f}\n"
            f"TP1 ({int(TP1_CIERRE_PCT*100)}%): {senal.tp1:.4f} → +${ganancia_tp1:.2f}\n"
            f"TP2 ({int((1-TP1_CIERRE_PCT)*100)}%): {senal.tp2:.4f} → +${ganancia_tp2:.2f}\n"
            f"Posición: ${tamano_usd:.0f} | Ganancia completa esperada: +${ganancia_tp1+ganancia_tp2:.2f}"
        )
        enviar_telegram(msg)
    else:
        try:
            _set_leverage(senal.simbolo, senal.leverage)
            orden = _crear_orden_market(senal.simbolo, lado, round(cantidad, 3))
            log.info("Orden ejecutada: %s", orden.get("id", "?"))
        except ccxt.BaseError as e:
            log.error("Error al abrir posición %s: %s", senal.simbolo, e)
            return

    posicion = Posicion(
        simbolo        = senal.simbolo,
        direccion      = senal.direccion,
        precio_entrada = senal.precio,
        precio_sl      = senal.sl,
        precio_tp1     = senal.tp1,
        precio_tp2     = senal.tp2,
        leverage       = senal.leverage,
        tamano_usd     = tamano_usd,
        atr            = senal.atr,   # guardado para trailing dinámico
    )
    estado.posiciones[senal.simbolo] = posicion
    estado.trades_dia += 1
    guardar_estado(estado)

def simbolo_ya_abierto(simbolo: str) -> bool:
    return simbolo in estado.posiciones

# ==============================================================================
# MONITOREO DE POSICIONES ABIERTAS
# ==============================================================================

@con_retry()
def precio_actual(simbolo: str) -> float:
    ticker = exchange.fetch_ticker(simbolo)
    return float(ticker["last"])

def actualizar_trailing(pos: Posicion, precio: float) -> None:
    """Tras TP1: trailing stop dinámico basado en ATR (doc: Trailing_Stop = SIC ± Mult×ATR).
    Si la posición tiene ATR guardado, usa 1.5×ATR. Si no, fallback a distancia_tp1×TRAIL_FACTOR."""
    if pos.atr > 0:
        margen_trail = pos.atr * TRAIL_MULT   # dinámico — se adapta a la volatilidad real
    else:
        distancia_tp1 = abs(pos.precio_entrada - pos.precio_tp1)
        margen_trail  = distancia_tp1 * TRAIL_FACTOR  # fallback legacy

    if pos.direccion == "SHORT":
        # mejor precio = precio más bajo visto
        if pos.mejor_precio == 0.0 or precio < pos.mejor_precio:
            pos.mejor_precio = precio
        nuevo_sl = pos.mejor_precio + margen_trail
        # solo mover el SL si mejora (baja para SHORT = más protección)
        if nuevo_sl < pos.precio_sl:
            log.info("Trailing SL %s: %.4f → %.4f (mejor precio: %.4f)",
                     pos.simbolo, pos.precio_sl, nuevo_sl, pos.mejor_precio)
            pos.precio_sl = nuevo_sl
            guardar_estado(estado)
    else:  # LONG
        if pos.mejor_precio == 0.0 or precio > pos.mejor_precio:
            pos.mejor_precio = precio
        nuevo_sl = pos.mejor_precio - margen_trail
        if nuevo_sl > pos.precio_sl:
            log.info("Trailing SL %s: %.4f → %.4f (mejor precio: %.4f)",
                     pos.simbolo, pos.precio_sl, nuevo_sl, pos.mejor_precio)
            pos.precio_sl = nuevo_sl
            guardar_estado(estado)

def monitorear_posiciones() -> None:
    for simbolo, pos in list(estado.posiciones.items()):
        try:
            precio = precio_actual(simbolo)
        except Exception as e:
            log.warning("Error precio %s: %s", simbolo, e)
            continue

        # ── LONG monitoring ────────────────────────────────────────────────
        if pos.direccion == "LONG":
            if pos.tp1_cerrado:
                actualizar_trailing(pos, precio)
            if precio <= pos.precio_sl:
                motivo = "Trail-SL" if pos.tp1_cerrado else "SL"
                cerrar_posicion(pos, precio, motivo)
            elif not pos.tp1_cerrado and precio >= pos.precio_tp1:
                cerrar_parcial(pos, precio, "TP1")
            elif pos.tp1_cerrado and precio >= pos.precio_tp2:
                cerrar_posicion(pos, precio, "TP2")

        # ── SHORT monitoring ───────────────────────────────────────────────
        elif pos.direccion == "SHORT":
            if pos.tp1_cerrado:
                actualizar_trailing(pos, precio)
            if precio >= pos.precio_sl:
                motivo = "Trail-SL" if pos.tp1_cerrado else "SL"
                cerrar_posicion(pos, precio, motivo)
            elif not pos.tp1_cerrado and precio <= pos.precio_tp1:
                cerrar_parcial(pos, precio, "TP1")
            elif pos.tp1_cerrado and precio <= pos.precio_tp2:
                cerrar_posicion(pos, precio, "TP2")

def cerrar_parcial(pos: Posicion, precio_scan: float, motivo: str) -> None:
    # Usar precio exacto del TP1, no el precio del scan (puede ser mejor o peor)
    precio_calc = pos.precio_tp1
    ganancia = abs(precio_calc - pos.precio_entrada) / pos.precio_entrada * pos.tamano_usd * TP1_CIERRE_PCT
    pos.tp1_cerrado = True
    # Mover SL a breakeven — la operación ya no puede perder
    pos.precio_sl = pos.precio_entrada
    log.info("SL movido a breakeven @ %.4f", pos.precio_sl)

    if DRY_RUN:
        log.info("[DRY-RUN] CERRAR PARCIAL %.0f%% %s %s @ %.4f (%s) | ganancia estimada $%.2f | SL → breakeven",
                 TP1_CIERRE_PCT * 100, pos.direccion, pos.simbolo, precio_calc, motivo, ganancia)
    else:
        lado = "sell" if pos.direccion == "LONG" else "buy"
        cantidad_parcial = round((pos.tamano_usd / pos.precio_entrada) * TP1_CIERRE_PCT, 3)
        try:
            _crear_orden_market(pos.simbolo, lado, cantidad_parcial)
        except ccxt.BaseError as e:
            log.error("Error cierre parcial %s: %s", pos.simbolo, e)
            return

    estado.ganancia_dia    += ganancia
    estado.capital_actual  += ganancia
    if estado.capital_actual > estado.capital_pico:   # actualizar pico histórico
        estado.capital_pico = estado.capital_actual
    guardar_estado(estado)
    msg = (f"✅ {motivo} parcial {pos.simbolo} @ {precio_calc:.4f} | +${ganancia:.2f} | SL → breakeven"
           f" | Capital: ${estado.capital_actual:.2f} (pico: ${estado.capital_pico:.2f})")
    log.info(msg)
    enviar_telegram(msg)

def cerrar_posicion(pos: Posicion, precio_scan: float, motivo: str) -> None:
    # Usar precio exacto del nivel que se tocó — evita inflación por delay del scan
    if motivo in ("SL", "Trail-SL"):
        precio_calc = pos.precio_sl
    elif motivo == "TP2":
        precio_calc = pos.precio_tp2
    else:
        precio_calc = precio_scan

    pct    = abs(precio_calc - pos.precio_entrada) / pos.precio_entrada
    factor = (1.0 - TP1_CIERRE_PCT) if pos.tp1_cerrado else 1.0

    # Signo basado en dirección real del trade, no en el motivo
    if pos.direccion == "SHORT":
        signo = 1 if precio_calc < pos.precio_entrada else -1
    else:
        signo = 1 if precio_calc > pos.precio_entrada else -1

    pnl = pct * pos.tamano_usd * factor * signo

    if DRY_RUN:
        log.info("[DRY-RUN] CERRAR %s %s @ %.4f (%s) | PnL $%.2f",
                 pos.direccion, pos.simbolo, precio_calc, motivo, pnl)
    else:
        lado = "sell" if pos.direccion == "LONG" else "buy"
        cantidad = round((pos.tamano_usd / pos.precio_entrada) * factor, 3)
        try:
            _crear_orden_market(pos.simbolo, lado, cantidad)
        except ccxt.BaseError as e:
            log.error("Error cierre posición %s: %s", pos.simbolo, e)
            return

    if pnl >= 0:
        estado.ganancia_dia   += pnl
        estado.capital_actual += pnl
        if estado.capital_actual > estado.capital_pico:  # nuevo pico histórico
            estado.capital_pico = estado.capital_actual
    else:
        estado.perdida_dia    += abs(pnl)
        estado.capital_actual  = max(estado.capital_actual - abs(pnl), RIESGO_MIN_USD * 5)
        if motivo == "SL":
            activar_cooldown(pos.simbolo)
            _registrar_sl_global()  # detectar rachas de pérdidas para pausa global

    emoji    = "✅" if motivo != "SL" else "❌"
    drawdown = (estado.capital_pico - estado.capital_actual) / estado.capital_pico if estado.capital_pico > 0 else 0
    dd_str   = f" | DD: {drawdown*100:.1f}%" if drawdown > 0.01 else ""
    msg      = (f"{emoji} {motivo} {pos.simbolo} @ {precio_calc:.4f} | PnL ${pnl:+.2f}"
                f" | Capital: ${estado.capital_actual:.2f}{dd_str}"
                f" | Día: +${estado.ganancia_dia:.2f} / -${estado.perdida_dia:.2f}")
    log.info(msg)
    enviar_telegram(msg)

    del estado.posiciones[pos.simbolo]
    guardar_estado(estado)

# ==============================================================================
# RESUMEN PERIÓDICO
# ==============================================================================

_ultimo_resumen: datetime = datetime.now(timezone.utc)

def enviar_resumen_si_corresponde() -> None:
    global _ultimo_resumen
    ahora = datetime.now(timezone.utc)
    if (ahora - _ultimo_resumen).seconds >= 3600:  # cada hora
        riesgo_vigente = calcular_riesgo_actual()
        msg = (
            f"📈 Resumen YKAI — {ahora.strftime('%H:%M UTC')}\n"
            f"💰 Capital: ${estado.capital_actual:.2f} | Riesgo/trade: ${riesgo_vigente:.2f}\n"
            f"Trades hoy: {estado.trades_dia}\n"
            f"Ganancia: +${estado.ganancia_dia:.2f} | Pérdida: -${estado.perdida_dia:.2f}\n"
            f"Posiciones abiertas: {len(estado.posiciones)}\n"
            f"Circuit breaker: {'⛔ ACTIVO' if estado.bloqueado else '✅ OK'}"
        )
        enviar_telegram(msg)
        _ultimo_resumen = ahora

# ==============================================================================
# LOOP PRINCIPAL
# ==============================================================================

def ciclo() -> None:
    if estado.posiciones:
        partes = []
        for sym, p in estado.posiciones.items():
            try:
                px = precio_actual(sym)
                fase = "→TP2" if p.tp1_cerrado else "→TP1"
                target = p.precio_tp2 if p.tp1_cerrado else p.precio_tp1
                dist = abs(px - target)
                partes.append(f"{sym.split('/')[0]} {p.direccion} @ {px:.1f} {fase}({dist:.1f})")
            except Exception:
                partes.append(sym)
        log.info("Escaneando... | %s | pérdida: $%.2f | ganancia: $%.2f",
                 " | ".join(partes), estado.perdida_dia, estado.ganancia_dia)
    else:
        log.info("Escaneando... | sin posiciones | pérdida: $%.2f | ganancia: $%.2f",
                 estado.perdida_dia, estado.ganancia_dia)
    monitorear_posiciones()

    if not verificar_riesgo():
        return

    # Verificar flash crash en BTC antes de escanear señales (evita entrar en pánico)
    _actualizar_flash_crash()

    for simbolo in ACTIVOS:
        if simbolo_ya_abierto(simbolo):
            continue
        senal = evaluar_senal(simbolo)
        if senal:
            abrir_posicion(senal)
            time.sleep(1)  # evitar rate limit al abrir varias posiciones seguidas

    enviar_resumen_si_corresponde()

def main() -> None:
    global estado
    estado = cargar_estado()
    modo = "DRY-RUN (simulación)" if DRY_RUN else "⚠️  REAL EN TESTNET"
    log.info("=" * 60)
    log.info("YKAI TradingBot v2.9 iniciado — modo: %s", modo)
    log.info("Capital actual: $%.2f | Pico: $%.2f | Riesgo/trade: $%.2f (%.0f%%) | CB diario: $%.2f | Max DD: %.0f%%",
             estado.capital_actual, estado.capital_pico, calcular_riesgo_actual(),
             RIESGO_PCT * 100, MAX_PERDIDA_DIA, MAX_DRAWDOWN_PCT * 100)
    kelly = calcular_kelly_empirico()
    if kelly != RIESGO_PCT:
        log.info("Kelly Criterion: %.2f%% (Quarter-Kelly) | Riesgo actual: %.2f%% — %s",
                 kelly * 100, RIESGO_PCT * 100,
                 "✅ alineado" if abs(kelly - RIESGO_PCT) < 0.005 else "⚠️ diferencia — más datos necesarios")
    metricas = calcular_metricas_historial()
    if metricas.get("dias", 0) >= 5:
        log.info("Métricas historial (%d días) | WR: %.0f%% | Retorno/día: %.2f%% | Sharpe: %.2f | Sortino: %.2f | Mejor: +%.1f%% | Peor: %.1f%%",
                 metricas["dias"], metricas["win_rate"]*100, metricas["retorno_dia_pct"],
                 metricas["sharpe"], metricas["sortino"],
                 metricas["mejor_dia_pct"], metricas["peor_dia_pct"])
    elif metricas.get("dias", 0) > 0:
        log.info("Historial: %d día(s) — necesita ≥5 días para calcular Sharpe/Sortino", metricas["dias"])
    log.info("Activos (%d): %s", len(ACTIVOS), ", ".join(ACTIVOS))
    log.info("Max posiciones: %d | Score mínimo: %d/6 | Trail factor: %.1f",
             MAX_TRADES_ABIERTOS, SCORE_MINIMO, TRAIL_FACTOR)
    log.info("Scan cada %ds | TF tendencia: %s | TF entrada: %s", INTERVALO_SCAN, TF_TENDENCIA, TF_ENTRADA)
    log.info("=" * 60)

    enviar_telegram(
        f"🤖 YKAI Bot iniciado [{modo}]\n"
        f"Activos ({len(ACTIVOS)}): {', '.join(a.split('/')[0] for a in ACTIVOS)}\n"
        f"💰 Capital: ${estado.capital_actual:.2f} | Riesgo: ${calcular_riesgo_actual():.2f} ({RIESGO_PCT*100:.0f}%)\n"
        f"Max trades: {MAX_TRADES_ABIERTOS} (anti-correlación Tier S) | CB: ${MAX_PERDIDA_DIA:.2f}"
    )

    while True:
        try:
            ciclo()
        except KeyboardInterrupt:
            log.info("Bot detenido por el usuario")
            enviar_telegram("🛑 Bot detenido manualmente")
            break
        except Exception as e:
            log.error("Error inesperado en ciclo principal: %s", e, exc_info=True)

        time.sleep(INTERVALO_SCAN)

if __name__ == "__main__":
    main()
