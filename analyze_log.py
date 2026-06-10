"""Analiza trading.log y muestra P&L diario + métricas clave"""
import re
from collections import defaultdict

LOG_PATH = "/home/ubuntu/BotTrader/trading.log"

days   = defaultdict(lambda: [0.0, 0.0])   # [gain, loss]
wins   = []
losses = []

with open(LOG_PATH) as f:
    for line in f:
        # Daily P&L acumulado
        m = re.search(r"(\d{4}-\d{2}-\d{2}).+D[ií]a.+\+\$([0-9.]+) / -\$([0-9.]+)", line)
        if m:
            d, g, l = m.group(1), float(m.group(2)), float(m.group(3))
            if g > days[d][0]: days[d][0] = g
            if l > days[d][1]: days[d][1] = l

        # PnL individual de trades cerrados
        m2 = re.search(r"PnL \$([+-][0-9.]+)", line)
        if m2:
            pnl = float(m2.group(1))
            if pnl > 0.01:  wins.append(pnl)
            elif pnl < -0.01: losses.append(pnl)

# ── Daily table ──────────────────────────────────────────────────────────
cap = 50.0
total_g, total_l = 0.0, 0.0
print("Fecha        Ganancia   Perdida    NET        Capital   Res")
print("-" * 68)
for d in sorted(days):
    g, l = days[d]
    net = g - l
    cap += net
    total_g += g
    total_l += l
    arrow = "✅ UP" if net >= 0 else "❌ DN"
    print(f"{d}  +{g:7.2f}   -{l:7.2f}   {net:+8.2f}  ${cap:8.2f}  {arrow}")

print("-" * 68)
print(f"TOTAL        +{total_g:.2f}   -{total_l:.2f}   {total_g - total_l:+.2f}")

# ── Trade metrics ─────────────────────────────────────────────────────────
total_trades = len(wins) + len(losses)
wr = len(wins) / total_trades * 100 if total_trades else 0
avg_w = sum(wins) / len(wins) if wins else 0
avg_l = abs(sum(losses) / len(losses)) if losses else 0
pf = sum(wins) / abs(sum(losses)) if losses else float("inf")
rr = avg_w / avg_l if avg_l else float("inf")

print()
print("=== METRICAS DE TRADING ===")
print(f"Total trades:    {total_trades}")
print(f"Win rate:        {wr:.1f}%")
print(f"Profit factor:   {pf:.2f}")
print(f"Avg win:        +${avg_w:.2f}")
print(f"Avg loss:       -${avg_l:.2f}")
print(f"W/L ratio:       {rr:.2f}")
print(f"Capital inicial: $50.00")
print(f"Capital final:   ${cap:.2f}")
print(f"Retorno total:   {(cap/50-1)*100:.1f}%")
