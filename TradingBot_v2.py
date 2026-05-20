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

CAPITAL_USD         = 50.0
RIESGO_USD          = 1.0        # $1 por trade = 2% del capital
MAX_PERDIDA_DIA     = 4.0        # $4 = 8% — circuit breaker (3 posiciones × $1 + margen)
MAX_TRADES_ABIERTOS = 3          # hasta 3 posiciones simultáneas

LEVERAGE_MIN        = 1          # 1x mínimo — respeta el $1 de riesgo en pares volátiles
LEVERAGE_MAX        = 15         # 15x máximo — captura el leverage óptimo en pares de bajo ATR%
TAMANO_MINIMO_USD   = 15.0       # descarta trades con posición < $15 (evita polvo)

EMA_RAPIDA          = 20
EMA_MEDIA           = 50
EMA_LENTA           = 200
RSI_PERIODO         = 14
ATR_PERIODO         = 14
ATR_MULT            = 1.3        # SL = precio ± (ATR × 1.3)
VOLUMEN_MULT        = 1.3        # volumen debe ser 1.3× la media

TP1_RATIO           = 1.0        # ratio TP1 (1:1) — cierra TP1_CIERRE_PCT del trade
TP2_RATIO           = 3.0        # ratio TP2 (3:1) — cierra el resto o trailing stop
TP1_CIERRE_PCT      = 0.25       # 25% en TP1, 75% sigue con trailing — más capital en el movimiento
TRAIL_FACTOR        = 0.4        # trailing más ajustado: SL a 0.4× distancia TP1 del mejor precio
SCORE_MINIMO        = 4          # de 6 condiciones

TF_TENDENCIA        = "1h"
TF_ENTRADA          = "15m"
INTERVALO_SCAN      = 20         # 20s — detecta cruces de SL/TP 33% más rápido que antes

# Tier S: BTC, ETH, SOL | Tier A: XRP, DOGE, BNB — los 6 con mejor liquidez y volatilidad
ACTIVOS             = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "BNB/USDT"]

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
    perdida_dia:  float = 0.0
    ganancia_dia: float = 0.0
    trades_dia:   int   = 0
    bloqueado:    bool  = False
    fecha:        date  = field(default_factory=date.today)
    posiciones:   dict  = field(default_factory=dict)   # simbolo → Posicion
    cooldowns:    dict  = field(default_factory=dict)   # simbolo → datetime fin cooldown

COOLDOWN_SL_SEGUNDOS = 3600  # 1h sin re-entrar al mismo símbolo tras un SL
ESTADO_ARCHIVO       = "estado_bot.json"

# ==============================================================================
# PERSISTENCIA DE ESTADO
# ==============================================================================

def guardar_estado(est: "EstadoBot") -> None:
    try:
        data = {
            "fecha":        est.fecha.isoformat(),
            "perdida_dia":  est.perdida_dia,
            "ganancia_dia": est.ganancia_dia,
            "trades_dia":   est.trades_dia,
            "bloqueado":    est.bloqueado,
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
                timestamp      = datetime.fromisoformat(pd_["timestamp"]),
            )

        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        for sym, dt_str in data.get("cooldowns", {}).items():
            fin = datetime.fromisoformat(dt_str)
            if fin > ahora:
                est.cooldowns[sym] = fin

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
        "fecha":        estado.fecha.isoformat(),
        "ganancia":     round(estado.ganancia_dia, 2),
        "perdida":      round(estado.perdida_dia, 2),
        "neto":         round(estado.ganancia_dia - estado.perdida_dia, 2),
        "trades":       estado.trades_dia,
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

def verificar_riesgo() -> bool:
    resetear_si_nuevo_dia()
    if estado.bloqueado:
        log.warning("Bot bloqueado — circuit breaker activo")
        return False
    if estado.perdida_dia >= MAX_PERDIDA_DIA:
        estado.bloqueado = True
        msg = f"⛔ CIRCUIT BREAKER — pérdida diaria ${estado.perdida_dia:.2f} ≥ ${MAX_PERDIDA_DIA}. Bot pausado."
        log.warning(msg)
        enviar_telegram(msg)
        return False
    if len(estado.posiciones) >= MAX_TRADES_ABIERTOS:
        return False  # silencioso — no spamear el log
    return True

def en_cooldown(simbolo: str) -> bool:
    fin = estado.cooldowns.get(simbolo)
    if fin and datetime.now(timezone.utc).replace(tzinfo=None) < fin:
        return True
    return False

def activar_cooldown(simbolo: str) -> None:
    from datetime import timedelta
    fin = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=COOLDOWN_SL_SEGUNDOS)
    estado.cooldowns[simbolo] = fin
    log.info("Cooldown activado en %s por %dm — no re-entra hasta %s",
             simbolo, COOLDOWN_SL_SEGUNDOS // 60, fin.strftime("%H:%M"))

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

# ==============================================================================
# CÁLCULO DE LEVERAGE Y STOPS
# ==============================================================================

def calcular_leverage_optimo(precio_entrada: float, precio_sl: float) -> int:
    distancia_pct = abs(precio_entrada - precio_sl) / precio_entrada
    if distancia_pct == 0:
        return LEVERAGE_MIN
    leverage = RIESGO_USD / (CAPITAL_USD * distancia_pct)
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

    # ── LONG ────────────────────────────────────────────────────────────────
    sl_long  = precio - atr * ATR_MULT
    tp1_long = precio + (precio - sl_long) * TP1_RATIO
    tp2_long = precio + (precio - sl_long) * TP2_RATIO

    c1 = precio > curr["ema200"]
    c2 = (prev["ema20"] <= prev["ema50"]) and (curr["ema20"] > curr["ema50"])
    c3 = 40 <= curr["rsi"] <= 65
    c4 = curr["volume"] > curr["vol_med"] * VOLUMEN_MULT
    c5 = curr["low"] >= curr["ema20"] * 0.998
    c6 = tendencia_1h == "ALCISTA"

    score_long = sum([c1, c2, c3, c4, c5, c6])

    if score_long >= SCORE_MINIMO:
        lev = calcular_leverage_optimo(precio, sl_long)
        log.info("SEÑAL LONG %s | score %d/6 | precio %.4f | SL %.4f | TP1 %.4f | TP2 %.4f | lev %dx",
                 simbolo, score_long, precio, sl_long, tp1_long, tp2_long, lev)
        return Senal(simbolo, "LONG", score_long, precio, sl_long, tp1_long, tp2_long, lev, atr)
    elif score_long == SCORE_MINIMO - 1:
        log.debug("Cerca LONG %s | score %d/6 | RSI %.1f | tendencia 1h: %s",
                  simbolo, score_long, curr["rsi"], tendencia_1h)

    # ── SHORT ───────────────────────────────────────────────────────────────
    sl_short  = precio + atr * ATR_MULT
    tp1_short = precio - (sl_short - precio) * TP1_RATIO
    tp2_short = precio - (sl_short - precio) * TP2_RATIO

    d1 = precio < curr["ema200"]
    d2 = (prev["ema20"] >= prev["ema50"]) and (curr["ema20"] < curr["ema50"])
    d3 = 35 <= curr["rsi"] <= 60
    d4 = curr["volume"] > curr["vol_med"] * VOLUMEN_MULT
    d5 = curr["high"] <= curr["ema20"] * 1.002
    d6 = tendencia_1h == "BAJISTA"

    score_short = sum([d1, d2, d3, d4, d5, d6])

    if score_short >= SCORE_MINIMO:
        lev = calcular_leverage_optimo(precio, sl_short)
        log.info("SEÑAL SHORT %s | score %d/6 | precio %.4f | SL %.4f | TP1 %.4f | TP2 %.4f | lev %dx",
                 simbolo, score_short, precio, sl_short, tp1_short, tp2_short, lev)
        return Senal(simbolo, "SHORT", score_short, precio, sl_short, tp1_short, tp2_short, lev, atr)
    elif score_short == SCORE_MINIMO - 1:
        log.debug("Cerca SHORT %s | score %d/6 | RSI %.1f | tendencia 1h: %s",
                  simbolo, score_short, curr["rsi"], tendencia_1h)

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

def abrir_posicion(senal: Senal) -> None:
    if simbolo_ya_abierto(senal.simbolo):
        return
    if en_cooldown(senal.simbolo):
        log.info("Cooldown activo en %s — señal ignorada", senal.simbolo)
        return

    # Tamaño exacto que hace PnL(SL) = RIESGO_USD
    # tamano = riesgo / distancia_sl_pct  →  SL hit = distancia_sl_pct × tamano = $1
    distancia_sl_pct = abs(senal.precio - senal.sl) / senal.precio
    tamano_usd       = RIESGO_USD / distancia_sl_pct if distancia_sl_pct > 0 else 0.0
    # No exceder el capital disponible apalancado
    tamano_usd       = min(tamano_usd, CAPITAL_USD * senal.leverage)

    if tamano_usd < TAMANO_MINIMO_USD:
        log.debug("Posición demasiado pequeña en %s (%.2f USD) — señal ignorada", senal.simbolo, tamano_usd)
        return

    cantidad = tamano_usd / senal.precio
    lado     = "buy" if senal.direccion == "LONG" else "sell"

    if DRY_RUN:
        log.info("[DRY-RUN] ABRIR %s %s | qty=%.4f | precio=%.4f | lev=%dx | SL=%.4f | TP1=%.4f | TP2=%.4f",
                 senal.direccion, senal.simbolo, cantidad, senal.precio, senal.leverage,
                 senal.sl, senal.tp1, senal.tp2)
        ganancia_tp1   = tamano_usd * abs(senal.tp1 - senal.precio) / senal.precio * TP1_CIERRE_PCT
        ganancia_tp2   = tamano_usd * abs(senal.tp2 - senal.precio) / senal.precio * (1 - TP1_CIERRE_PCT)
        msg = (
            f"📊 [DRY-RUN] {senal.direccion} {senal.simbolo}\n"
            f"Precio: {senal.precio:.4f} | Lev: {senal.leverage}x | Score: {senal.score}/6\n"
            f"SL:  {senal.sl:.4f}  → máx -$1.00\n"
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
    """Tras TP1: rastrea el mejor precio y ajusta el SL para asegurar ganancia."""
    distancia_tp1 = abs(pos.precio_entrada - pos.precio_tp1)
    margen_trail  = distancia_tp1 * TRAIL_FACTOR

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

    estado.ganancia_dia += ganancia
    guardar_estado(estado)
    msg = f"✅ {motivo} parcial {pos.simbolo} @ {precio_calc:.4f} | +${ganancia:.2f} | SL → breakeven"
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
        estado.ganancia_dia += pnl
    else:
        estado.perdida_dia  += abs(pnl)
        if motivo == "SL":
            activar_cooldown(pos.simbolo)

    emoji = "✅" if motivo != "SL" else "❌"
    msg   = f"{emoji} {motivo} {pos.simbolo} @ {precio_calc:.4f} | PnL ${pnl:+.2f} | Día: +${estado.ganancia_dia:.2f} / -${estado.perdida_dia:.2f}"
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
        msg = (
            f"📈 Resumen YKAI — {ahora.strftime('%H:%M UTC')}\n"
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
    log.info("YKAI TradingBot v2.3 iniciado — modo: %s", modo)
    log.info("Capital: $%.2f | Riesgo/trade: $%.2f | CB: $%.2f", CAPITAL_USD, RIESGO_USD, MAX_PERDIDA_DIA)
    log.info("Activos (%d): %s", len(ACTIVOS), ", ".join(ACTIVOS))
    log.info("Max posiciones: %d | Score mínimo: %d/6 | Trail factor: %.1f",
             MAX_TRADES_ABIERTOS, SCORE_MINIMO, TRAIL_FACTOR)
    log.info("Scan cada %ds | TF tendencia: %s | TF entrada: %s", INTERVALO_SCAN, TF_TENDENCIA, TF_ENTRADA)
    log.info("=" * 60)

    enviar_telegram(
        f"🤖 YKAI Bot iniciado [{modo}]\n"
        f"Activos ({len(ACTIVOS)}): {', '.join(a.split('/')[0] for a in ACTIVOS)}\n"
        f"Max trades: {MAX_TRADES_ABIERTOS} | Riesgo/trade: $1.00 | CB: ${MAX_PERDIDA_DIA:.2f}"
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
