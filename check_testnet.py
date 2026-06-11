"""Verifica que las API keys de testnet funcionan para trading y hay fondos."""
import os
import ccxt
from dotenv import load_dotenv

load_dotenv("/home/ubuntu/BotTrader/.env")
k = os.getenv("API_KEY_BINANCE")
s = os.getenv("API_SECRET_BINANCE")
print("Keys presentes:", bool(k), bool(s))

ex = ccxt.binanceusdm({
    "apiKey": k, "secret": s, "enableRateLimit": True,
    "options": {"defaultType": "future", "fetchCurrencies": False},
})
for key, url in ex.urls["api"].items():
    if isinstance(url, str) and "fapi.binance.com" in url:
        ex.urls["api"][key] = url.replace("fapi.binance.com", "testnet.binancefuture.com")
ex.options["testnet"] = True

try:
    bal = ex.fetch_balance()
    usdt = bal.get("USDT", {})
    print("CONEXION TESTNET OK")
    print("Balance USDT testnet | total:", usdt.get("total"), "| libre:", usdt.get("free"))
except Exception as e:
    print("ERROR:", type(e).__name__, str(e)[:150])
