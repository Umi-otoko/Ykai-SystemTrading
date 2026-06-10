"""
Backtest del filtro de régimen ADX contra el historial real (trading.log).

Para cada ENTRADA del log:
  1. Descarga velas H1 reales de Binance alrededor de esa fecha
  2. Calcula el ADX(14) Wilder de la vela H1 cerrada antes de la entrada
  3. Cruza ADX-en-entrada vs resultado (SL / WIN)

Reporta el trade-off honesto: SLs evitados vs wins sacrificados si bloqueáramos ADX<20.
"""
import re
import time
import numpy as np
import pandas as pd
import ccxt
from datetime import datetime, timezone

LOG_PATH = "/home/ubuntu/BotTrader/trading.log"
ADX_PERIODO       = 14
ADX_MIN_TENDENCIA = 25.0
ADX_MIN_DEBIL     = 20.0

ex = ccxt.binance({"options": {"defaultType": "future"}})

# ── 1. Parsear log: emparejar ENTRADA con su cierre final ───────────────────
re_abrir = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*ABRIR (LONG|SHORT) ([A-Z]+/USDT) .*precio=([0-9.]+)")
re_sl    = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*❌ SL ([A-Z]+/USDT) @ [0-9.]+ \| PnL \$([+-][0-9.]+)")
re_tp2   = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*✅ TP2 ([A-Z]+/USDT) @ [0-9.]+ \| PnL \$([+-][0-9.]+)")
re_trail = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*✅ Trail-SL ([A-Z]+/USDT) @ [0-9.]+ \| PnL \$([+-][0-9.]+)")

trades = []          # {entry_ts, dir, sym, precio, result}
abiertos = {}        # sym -> {entry_ts, dir, precio}
seen = set()

with open(LOG_PATH) as f:
    for line in f:
        key = line.strip()
        if key in seen:   # dedupe líneas idénticas (bug double-log de días iniciales)
            continue
        seen.add(key)

        m = re_abrir.search(line)
        if m:
            ts, direc, sym, precio = m.group(1), m.group(2), m.group(3), float(m.group(4))
            abiertos[sym] = {"entry_ts": ts, "dir": direc, "sym": sym, "precio": precio}
            continue

        m = re_sl.search(line)
        if m:
            ts, sym, pnl = m.group(1), m.group(2), float(m.group(3))
            if sym in abiertos:
                t = abiertos.pop(sym)
                t["result"] = "SL"
                t["pnl"] = pnl
                trades.append(t)
            continue

        m = re_tp2.search(line)
        if m:
            ts, sym, pnl = m.group(1), m.group(2), float(m.group(3))
            if sym in abiertos:
                t = abiertos.pop(sym)
                t["result"] = "WIN"
                t["pnl"] = pnl
                trades.append(t)
            continue

        m = re_trail.search(line)
        if m:
            ts, sym, pnl = m.group(1), m.group(2), float(m.group(3))
            if sym in abiertos:
                t = abiertos.pop(sym)
                t["result"] = "WIN" if pnl >= 0 else "SL"
                t["pnl"] = pnl
                trades.append(t)
            continue

print(f"Trades emparejados: {len(trades)}")

# ── 2. ADX Wilder ───────────────────────────────────────────────────────────
def calcular_adx(df, periodo=14):
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff(); down = -low.diff()
    plus_dm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = np.maximum(high - low, np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs()))
    a = 1.0 / periodo
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean().fillna(0)

# ── 3. Descargar H1 por símbolo (una vez) y calcular ADX de toda la serie ────
simbolos = sorted(set(t["sym"] for t in trades))
adx_series = {}
for sym in simbolos:
    since = ex.parse8601("2026-05-23T00:00:00Z")
    ohlcv = ex.fetch_ohlcv(sym, "1h", since=since, limit=600)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("dt")
    df["adx"] = calcular_adx(df, ADX_PERIODO)
    adx_series[sym] = df
    print(f"  {sym}: {len(df)} velas H1, ADX rango {df['adx'].min():.0f}-{df['adx'].max():.0f}")
    time.sleep(0.3)

# ── 4. Para cada trade, ADX de la vela H1 cerrada antes de la entrada ────────
def adx_en(sym, ts_str):
    df = adx_series[sym]
    ts = pd.to_datetime(ts_str)
    prev = df[df.index <= ts]
    if len(prev) < 2:
        return None
    return float(prev["adx"].iloc[-2])   # vela cerrada anterior

for t in trades:
    t["adx"] = adx_en(t["sym"], t["entry_ts"])

trades = [t for t in trades if t["adx"] is not None]

# ── 5. Tabla cruzada ADX vs resultado ───────────────────────────────────────
def bucket(adx):
    if adx < ADX_MIN_DEBIL:     return "RANGO (<20)"
    if adx < ADX_MIN_TENDENCIA: return "DEBIL (20-25)"
    return "FUERTE (>=25)"

print("\n" + "="*60)
print("CRUCE: ADX en entrada  vs  resultado del trade")
print("="*60)
print(f"{'Régimen':<16} {'SL':>5} {'WIN':>5} {'Total':>6} {'WinRate':>8} {'PnL neto':>10}")
print("-"*60)
for b in ["RANGO (<20)", "DEBIL (20-25)", "FUERTE (>=25)"]:
    grp = [t for t in trades if bucket(t["adx"]) == b]
    sl  = sum(1 for t in grp if t["result"] == "SL")
    win = sum(1 for t in grp if t["result"] == "WIN")
    tot = len(grp)
    wr  = win / tot * 100 if tot else 0
    pnl = sum(t.get("pnl", 0) for t in grp)
    print(f"{b:<16} {sl:>5} {win:>5} {tot:>6} {wr:>7.0f}% {pnl:>+9.2f}")

# ── 6. Veredicto: ¿qué pasa si bloqueamos la banda 20-25 (zona de muerte)? ───
def veredicto(nombre, cond):
    grp = [t for t in trades if cond(t["adx"])]
    sl  = sum(1 for t in grp if t["result"] == "SL")
    win = sum(1 for t in grp if t["result"] == "WIN")
    pnl = sum(t.get("pnl", 0) for t in grp)
    print(f"\n{nombre}")
    print(f"  Entradas bloqueadas: {len(grp)}/{len(trades)} ({len(grp)/len(trades)*100:.0f}%)")
    print(f"  SLs evitados:        {sl}")
    print(f"  WINs sacrificados:   {win}")
    print(f"  PnL que se elimina:  {pnl:+.2f}  →  {'MEJORA' if pnl < 0 else 'EMPEORA'} el resultado")

print("\n" + "="*60)
print("VEREDICTO DE CADA FILTRO POSIBLE")
print("="*60)
veredicto("[A] Bloquear ADX < 20 (mi hipótesis original):",
          lambda a: a < ADX_MIN_DEBIL)
veredicto("[B] Bloquear ADX 20-25 (zona de muerte real):",
          lambda a: ADX_MIN_DEBIL <= a < ADX_MIN_TENDENCIA)

total_pnl = sum(t.get("pnl", 0) for t in trades)
print(f"\nPnL total de todos los trades cerrados: {total_pnl:+.2f}")
