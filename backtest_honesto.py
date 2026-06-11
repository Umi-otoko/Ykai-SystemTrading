"""
Backtest HONESTO — aplica costos reales al historial de los 16 días y calcula las
métricas que el material académico exige (Deflated Sharpe, CVaR, Calmar).

Responde: ¿cuánto del +130% es real una vez descontados comisión, slippage y
funding? ¿y cuánto es sobreajuste de haber probado 6 configuraciones?
"""
import re
import sys
import numpy as np
from collections import defaultdict
from datetime import datetime
import quant_metrics as qm

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOG = "/home/ubuntu/BotTrader/trading.log"   # en el servidor; local: ajustar
if len(sys.argv) > 1:
    LOG = sys.argv[1]

CAPITAL_INICIAL = 50.0
N_TRIALS = 6   # v2.9, 2.10, 2.11, 2.12, 2.13, 2.14 — configs probadas sobre el mismo log

# ── Parseo: emparejar ABRIR (notional) con sus cierres (PnL bruto) ──────────────
re_abrir = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*ABRIR (LONG|SHORT) ([A-Z]+/USDT) \| qty=([0-9.]+) \| precio=([0-9.]+)")
re_cierre = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*(✅|❌) (TP1 parcial|TP2|Trail-SL|SL) ([A-Z]+/USDT) .*?(?:PnL \$|[+]\$)([+-]?[0-9.]+)")

abiertos = defaultdict(list)   # sym -> [(ts, notional)]
eventos = []                   # (ts, sym, pnl_bruto, notional_porcion, horas)
seen = set()

def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

with open(LOG, encoding="utf-8", errors="ignore") as f:
    for line in f:
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)

        m = re_abrir.search(line)
        if m:
            ts, _, sym, qty, precio = m.groups()
            notional = float(qty) * float(precio)
            abiertos[sym].append((parse_ts(ts), notional))
            continue

        m = re_cierre.search(line)
        if m:
            ts, _, tipo, sym, pnl = m.groups()
            pnl = float(pnl)
            t_cierre = parse_ts(ts)
            # buscar el ABRIR mas reciente de ese simbolo para notional y horas
            if abiertos[sym]:
                t_abrir, notional = abiertos[sym][-1]
                horas = max(0.0, (t_cierre - t_abrir).total_seconds() / 3600.0)
                if tipo == "TP1 parcial":
                    porcion = notional * 0.20
                elif tipo in ("TP2", "Trail-SL", "SL"):
                    porcion = notional * 0.80   # tras TP1, queda 80%
                    abiertos[sym].pop()          # cierre final libera la posicion
                else:
                    porcion = notional
            else:
                porcion, horas = 200.0, 4.0      # fallback
            eventos.append((t_cierre, sym, pnl, porcion, horas, tipo))

eventos.sort(key=lambda e: e[0])
print(f"Eventos de cierre parseados: {len(eventos)}")

# ── Construir PnL bruto vs neto, por día ────────────────────────────────────────
pnl_bruto_dia = defaultdict(float)
pnl_neto_dia  = defaultdict(float)
costo_total = 0.0

for t_cierre, sym, pnl, porcion, horas, tipo in eventos:
    salida = "maker" if tipo in ("TP1 parcial", "TP2") else "taker"  # TP=limit, SL=market
    costo = qm.costo_total_trade(porcion, horas, entrada_tipo="maker", salida_tipo=salida)
    costo_total += costo
    dia = t_cierre.date()
    pnl_bruto_dia[dia] += pnl
    pnl_neto_dia[dia]  += pnl - costo

dias = sorted(pnl_bruto_dia.keys())

def serie_equity_retornos(pnl_por_dia):
    cap = CAPITAL_INICIAL
    equity, retornos = [cap], []
    for d in dias:
        pnl = pnl_por_dia[d]
        ret = pnl / cap if cap > 0 else 0.0
        cap += pnl
        equity.append(cap)
        retornos.append(ret)
    return np.array(equity), np.array(retornos)

eq_b, ret_b = serie_equity_retornos(pnl_bruto_dia)
eq_n, ret_n = serie_equity_retornos(pnl_neto_dia)

pnl_bruto = sum(pnl_bruto_dia.values())
pnl_neto  = sum(pnl_neto_dia.values())

# ── Reporte ─────────────────────────────────────────────────────────────────────
print("\n" + "="*64)
print("  BACKTEST HONESTO — 16 días reales, costos aplicados")
print("="*64)
print(f"  Días operados:        {len(dias)}")
print(f"  Eventos de cierre:    {len(eventos)}")
print(f"\n  {'':22}{'BRUTO':>12}{'NETO (real)':>14}")
print(f"  {'-'*48}")
print(f"  {'PnL total':22}{pnl_bruto:>+11.2f}${pnl_neto:>+12.2f}$")
print(f"  {'Capital final':22}{eq_b[-1]:>11.2f}${eq_n[-1]:>12.2f}$")
print(f"  {'Retorno %':22}{(eq_b[-1]/CAPITAL_INICIAL-1)*100:>11.1f}%{(eq_n[-1]/CAPITAL_INICIAL-1)*100:>12.1f}%")
print(f"\n  Costos totales (comisión+slippage+funding): ${costo_total:.2f}")
print(f"  → los costos se comieron {(pnl_bruto-pnl_neto)/pnl_bruto*100:.1f}% del PnL bruto")

print(f"\n  {'MÉTRICAS DE RIESGO (sobre retornos NETOS diarios)':<48}")
print(f"  {'-'*48}")
sharpe_n = ret_n.mean()/ret_n.std(ddof=1) if ret_n.std(ddof=1) > 0 else 0
print(f"  Sharpe diario (neto):       {sharpe_n:>7.2f}")
print(f"  Sharpe anualizado (×√365):  {sharpe_n*np.sqrt(365):>7.2f}")
print(f"  Probabilistic Sharpe (>0):  {qm.probabilistic_sharpe(ret_n):>7.3f}")
print(f"  DEFLATED Sharpe ({N_TRIALS} trials): {qm.deflated_sharpe(ret_n, N_TRIALS):>7.3f}   <- ¿>0.95?")
print(f"  Expected Shortfall 95% (t): {qm.expected_shortfall_t(ret_n)*100:>6.2f}%  (pérdida diaria de cola)")
print(f"  Expected Shortfall 95% (h): {qm.expected_shortfall_historico(ret_n)*100:>6.2f}%")
print(f"  Max Drawdown:               {qm.max_drawdown(eq_n)*100:>6.1f}%")
print(f"  Calmar ratio:               {qm.calmar_ratio(ret_n, eq_n):>7.2f}")
print("="*64)
print("  Lectura: DSR < 0.95 = no podemos afirmar que el edge es real con")
print("  esta muestra; es consistente con sobreajuste. Necesitamos más días")
print("  out-of-sample (el material lo exige). NO arriesgar real aún.")
print("="*64)
