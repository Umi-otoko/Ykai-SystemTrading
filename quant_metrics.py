"""
YKAI Quant Metrics — métricas honestas de rendimiento y riesgo.

Implementa las fórmulas extraídas del "Manual de Arquitectura Cuantitativa del
Trading" + papers (López de Prado, Pan-Pang-Zhao, Roll). Todo verificado contra
las imágenes de fórmulas del .docx.

Propósito: dejar de mentirnos con PnL bruto y Sharpe inflado. Mide el rendimiento
NETO de costos y penaliza el sobreajuste (Deflated Sharpe).
"""
from __future__ import annotations
import math
import numpy as np
from scipy import stats

# ──────────────────────────────────────────────────────────────────────────────
# COSTOS DE TRANSACCIÓN  (el #1 destructor de alfa según ambas fuentes)
# ──────────────────────────────────────────────────────────────────────────────
COMISION_TAKER_PCT = 0.0005   # Binance Futures USDT-M taker: 0.05% por lado
SLIPPAGE_PCT       = 0.0002   # estimado pares líquidos (BTC/ETH/DOGE/BNB): 0.02%
FUNDING_8H_PCT     = 0.0001   # funding promedio ~0.01% cada 8h (variable)

def costo_round_trip(notional_usd: float) -> float:
    """Costo total de abrir+cerrar una posición de tamaño notional_usd.
    Comisión 2 lados + slippage 2 lados. NO incluye market impact
    (confirmado irrelevante para órdenes retail por la Square-Root Law)."""
    comision  = notional_usd * COMISION_TAKER_PCT * 2     # entrada + salida
    slippage  = notional_usd * SLIPPAGE_PCT * 2
    return comision + slippage

def costo_funding(notional_usd: float, horas_abierto: float) -> float:
    """Funding acumulado: se cobra cada 8h. Aproximación lineal."""
    periodos_8h = horas_abierto / 8.0
    return notional_usd * FUNDING_8H_PCT * periodos_8h

def costo_total_trade(notional_usd: float, horas_abierto: float = 0.0) -> float:
    return costo_round_trip(notional_usd) + costo_funding(notional_usd, horas_abierto)

# ──────────────────────────────────────────────────────────────────────────────
# ROLL (1984) — spread efectivo solo con precios de cierre
# ──────────────────────────────────────────────────────────────────────────────
def roll_spread(precios: list[float] | np.ndarray) -> float:
    """Spread efectivo implícito de Roll: 2·√(−cov(Δpₜ, Δpₜ₋₁)).
    Si la covarianza es positiva (chop/HFT), usa la Medida Absoluta de Roll
    para evitar la raíz de un negativo: 2·√(|cov|)."""
    p = np.asarray(precios, dtype=float)
    if len(p) < 3:
        return 0.0
    dp = np.diff(p)
    if len(dp) < 2:
        return 0.0
    cov = np.cov(dp[:-1], dp[1:])[0, 1]
    return 2.0 * math.sqrt(abs(cov))   # Absolute Roll (estable siempre)

# ──────────────────────────────────────────────────────────────────────────────
# SHARPE PROBABILÍSTICO Y DEFLACTADO  (Bailey & López de Prado)
# La fórmula de varianza viene de la imagen79 del .docx:
#   σ²(SR) = (1/(n−1))·(1 + ½SR² − γ₃·SR + ((γ₄−3)/4)·SR²)
#         = (1/(n−1))·(1 − γ₃·SR + ((γ₄−1)/4)·SR²)   [γ₄ = kurtosis no-excess]
# ──────────────────────────────────────────────────────────────────────────────
def _sharpe_y_momentos(retornos: np.ndarray):
    r = np.asarray(retornos, dtype=float)
    n = len(r)
    mu, sd = r.mean(), r.std(ddof=1)
    if sd == 0:
        return 0.0, 0.0, 3.0, n
    sr = mu / sd                                   # Sharpe por período (no anualizado)
    skew = stats.skew(r)                           # γ₃
    kurt = stats.kurtosis(r, fisher=False)         # γ₄ (no-excess: normal = 3)
    return sr, skew, kurt, n

def probabilistic_sharpe(retornos, sr_benchmark: float = 0.0) -> float:
    """PSR(SR*) = Φ[ (SR − SR*) / σ(SR) ].
    Probabilidad de que el Sharpe REAL supere sr_benchmark, corregido por
    asimetría y colas gruesas. PSR > 0.95 = confianza estadística."""
    sr, skew, kurt, n = _sharpe_y_momentos(retornos)
    if n < 3:
        return float("nan")
    var_sr = (1 - skew * sr + ((kurt - 1) / 4.0) * sr**2) / (n - 1)
    if var_sr <= 0:
        return float("nan")
    return float(stats.norm.cdf((sr - sr_benchmark) / math.sqrt(var_sr)))

def sharpe_benchmark_deflactado(n_trials: int, var_sharpes: float = 1.0) -> float:
    """SR* esperado del MEJOR de n_trials backtests bajo H0 (sin skill).
    SR* = √V·[(1−γ)·Z⁻¹(1−1/N) + γ·Z⁻¹(1−1/(N·e))], γ = Euler-Mascheroni."""
    if n_trials < 1:
        return 0.0
    gamma_em = 0.5772156649
    e = math.e
    z1 = stats.norm.ppf(1 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1 - 1.0 / (n_trials * e))
    return math.sqrt(var_sharpes) * ((1 - gamma_em) * z1 + gamma_em * z2)

def deflated_sharpe(retornos, n_trials: int) -> float:
    """Deflated Sharpe Ratio: PSR contra el benchmark inflado por haber probado
    n_trials configuraciones. DSR > 0.95 = el resultado NO es sobreajuste.
    Penaliza exactamente lo que hicimos: probar v2.9→v2.14 sobre el mismo log."""
    sr, _, _, n = _sharpe_y_momentos(retornos)
    if n < 3:
        return float("nan")
    # varianza de los Sharpe entre trials: sin el dato real, se aproxima con
    # la varianza del estimador del Sharpe del propio track record (conservador).
    var_sr_estimador = 1.0 / (n - 1)
    sr_star = sharpe_benchmark_deflactado(n_trials, var_sr_estimador)
    return probabilistic_sharpe(retornos, sr_benchmark=sr_star)

# ──────────────────────────────────────────────────────────────────────────────
# EXPECTED SHORTFALL / CVaR  (riesgo de cola coherente — mejor que max-drawdown)
# ──────────────────────────────────────────────────────────────────────────────
def expected_shortfall_historico(retornos, alpha: float = 0.95) -> float:
    """ES por el estimador de promedio aritmético (Pan-Pang-Zhao §5.1), válido
    para MUESTRAS PEQUEÑAS (nuestro caso, 16 días).
    ES_β = mean(pérdidas que superan el percentil β). Devuelve pérdida positiva."""
    r = np.asarray(retornos, dtype=float)
    perdidas = np.sort(-r)                 # pérdidas ascendente (positivas = malo)
    n = len(perdidas)
    if n == 0:
        return 0.0
    k = math.ceil(n * alpha)
    cola = perdidas[k - 1:]                # las (1−α) peores
    if len(cola) == 0:
        return float(perdidas[-1])
    return float(cola.mean())

def expected_shortfall_t(retornos, alpha: float = 0.95) -> float:
    """ES paramétrico con distribución t de Student (fórmula cerrada, imagen124):
       ES_α = μ + σ·[g_ν(t⁻¹(1−α))/(1−α)]·[(ν + t⁻¹(1−α)²)/(ν−1)]
    Captura las colas gruesas que el max-drawdown gaussiano ignora."""
    r = np.asarray(retornos, dtype=float)
    if len(r) < 4:
        return float("nan")
    nu, mu, sigma = stats.t.fit(r)         # ajusta grados de libertad, loc, scale
    if nu <= 1:
        return float("inf")                # varianza infinita
    q = stats.t.ppf(1 - alpha, nu)         # cuantil t (negativo)
    pdf = stats.t.pdf(q, nu)
    es_std = (pdf / (1 - alpha)) * ((nu + q**2) / (nu - 1))
    return float(-(mu - sigma * es_std))   # como pérdida positiva

# ──────────────────────────────────────────────────────────────────────────────
# CALMAR  (rendimiento contra el peor drawdown materializado)
# ──────────────────────────────────────────────────────────────────────────────
def max_drawdown(equity: list[float] | np.ndarray) -> float:
    eq = np.asarray(equity, dtype=float)
    if len(eq) < 2:
        return 0.0
    pico = np.maximum.accumulate(eq)
    dd = (eq - pico) / pico
    return float(-dd.min())

def calmar_ratio(retornos, equity) -> float:
    """Calmar = retorno total / max drawdown. Penaliza el desangrado persistente."""
    r = np.asarray(retornos, dtype=float)
    mdd = max_drawdown(equity)
    if mdd == 0:
        return float("inf")
    return float(r.sum() / mdd)

# ──────────────────────────────────────────────────────────────────────────────
# BVC — order flow imbalance solo con OHLCV (Shohfi et al.) → semilla de VPIN
# ──────────────────────────────────────────────────────────────────────────────
def bvc_buy_fraction(delta_p: float, sigma_dp: float, df: float = 0.25) -> float:
    """Fracción del volumen clasificada como COMPRA: Z(ΔP/σ_ΔP) con CDF t-Student.
    V_buy = V·frac, V_sell = V·(1−frac). df=0.25 es el valor de ELO."""
    if sigma_dp <= 0:
        return 0.5
    return float(stats.t.cdf(delta_p / sigma_dp, df))

def vpin(deltas_precio: list[float], volumenes: list[float], n_buckets: int = 50,
         df: float = 0.25) -> float:
    """VPIN aproximado vía BVC: Σ|Vbuy−Vsell| / Σ V sobre n_buckets recientes.
    Lectura alta = flujo tóxico / pre-evento de volatilidad → filtro de riesgo."""
    dp = np.asarray(deltas_precio, dtype=float)
    vol = np.asarray(volumenes, dtype=float)
    if len(dp) < n_buckets or len(dp) != len(vol):
        return float("nan")
    sigma = dp.std(ddof=1)
    if sigma <= 0:
        return 0.0
    dp, vol = dp[-n_buckets:], vol[-n_buckets:]
    desbalance = 0.0
    for d, v in zip(dp, vol):
        frac = bvc_buy_fraction(d, sigma, df)
        desbalance += abs(v * frac - v * (1 - frac))
    total = vol.sum()
    return float(desbalance / total) if total > 0 else 0.0


if __name__ == "__main__":
    # auto-test rápido con datos sintéticos
    rng = np.random.default_rng(42)
    r = rng.normal(0.01, 0.03, 200)
    eq = 50 * np.cumprod(1 + r)
    print("=== AUTOTEST quant_metrics ===")
    print(f"Costo round-trip $200 notional: ${costo_round_trip(200):.3f}")
    print(f"PSR (vs 0):           {probabilistic_sharpe(r):.3f}")
    print(f"Deflated SR (6 trials): {deflated_sharpe(r, 6):.3f}")
    print(f"Expected Shortfall 95% (hist): {expected_shortfall_historico(r)*100:.2f}%")
    print(f"Expected Shortfall 95% (t):    {expected_shortfall_t(r)*100:.2f}%")
    print(f"Calmar: {calmar_ratio(r, eq):.2f} | MaxDD: {max_drawdown(eq)*100:.1f}%")
