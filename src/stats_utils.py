"""Small statistics helpers (no statsmodels needed)."""
import numpy as np
from scipy import stats


def wilson(k, n, conf=0.95):
    """Wilson score interval for a proportion k/n."""
    if n == 0:
        return (np.nan, np.nan)
    z = stats.norm.ppf(1 - (1 - conf) / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate_vs_tolerance(k, n, tol):
    """GREEN / AMBER / RED using the Wilson interval (same rule as my loan-testing repo)."""
    lo, hi = wilson(k, n)
    p = k / n if n else np.nan
    if lo > tol:
        return "RED"
    if p > tol:
        return "AMBER"
    return "GREEN"


def chi_square_hotspots(table):
    """Chi-square test of homogeneity on a 2-column [late, on_time] table.
    Returns statistic, p-value, dof and the standardized residual of the 'late' column."""
    obs = np.asarray(table, dtype=float)
    chi2, p, dof, exp = stats.chi2_contingency(obs, correction=False)
    resid = (obs - exp) / np.sqrt(exp)
    return chi2, p, dof, resid[:, 0], exp


def p_chart_limits(p_bar, n):
    """3-sigma limits for a p-chart with subgroup size n."""
    s = np.sqrt(p_bar * (1 - p_bar) / n)
    return np.maximum(0, p_bar - 3 * s), p_bar + 3 * s


def bootstrap_ci(fn, n, B=2000, seed=0, conf=0.95):
    """Percentile bootstrap: fn(idx) -> statistic for resampled row indices."""
    rng = np.random.default_rng(seed)
    vals = np.array([fn(rng.integers(0, n, n)) for _ in range(B)])
    a = (1 - conf) / 2
    return np.nanquantile(vals, a), np.nanquantile(vals, 1 - a)
