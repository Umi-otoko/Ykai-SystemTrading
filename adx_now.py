"""Muestra el ADX 1h actual de cada activo y la decisión del filtro v2.14."""
import numpy as np
import pandas as pd
import ccxt

ex = ccxt.binance({"options": {"defaultType": "future"}})

def adx(df, p=14):
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff(); dn = -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
    a = 1.0 / p
    at = tr.ewm(alpha=a, adjust=False).mean()
    pi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / at
    mi = 100 * mdm.ewm(alpha=a, adjust=False).mean() / at
    dx = 100 * (pi - mi).abs() / (pi + mi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean().fillna(0)

print(f"{'Activo':<12}{'ADX 1h':>8}  Decision del filtro")
print("-" * 50)
for s in ["BTC/USDT", "ETH/USDT", "DOGE/USDT", "BNB/USDT"]:
    o = ex.fetch_ohlcv(s, "1h", limit=200)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    v = float(adx(df).iloc[-2])
    if 20 <= v < 25:
        d = "BLOQUEADO (zona muerte 20-25)"
    elif v < 20:
        d = "opera (rango)"
    else:
        d = "opera (tendencia)"
    print(f"{s:<12}{v:>8.1f}  {d}")
