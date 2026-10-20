"""
FX-effect analyses that design the forecasting features (notebook 02):
trend regimes (change points), which FX lags matter, and whether the FX
effect is symmetric.

All rules (model, penalty, minimum segment, decision thresholds) are fixed
here, before looking at results, so they cannot be tuned to the answer.
"""

import numpy as np
import pandas as pd
import ruptures as rpt
import statsmodels.api as sm

from features import assert_monthly, yoy_uses_covid

# --- Change points ---------------------------------------------------------
MIN_SEGMENT = 12            # months: a single odd month cannot create a regime
PARAMS_PER_SEGMENT = 3      # level + slope + break date -> BIC-style penalty
EDGE_MONTHS = 2 * MIN_SEGMENT   # breaks this close to either end are edge effects, not regimes
LEVEL_TOLERANCE = 0.05      # |post-covid level vs 2016-2019| below 5% = "level recovered" (primary)
PATH_TOLERANCE = 0.05       # |gap| below 5% = "back to the pre-covid path" (secondary, fragile)

# --- FX regressions --------------------------------------------------------
HAC_LAGS = 12               # YoY changes overlap for 12 months -> autocorrelated errors
ALPHA = 0.05


def _signal(y: np.ndarray) -> np.ndarray:
    """ruptures 'linear' cost: column 0 = series, other columns = regressors (constant, time)."""
    t = np.arange(len(y)) / 12                       # time in years
    return np.column_stack([y, np.ones(len(y)), t])


def noise_sigma(y: np.ndarray) -> float:
    """Robust noise level: MAD of month-to-month changes / sqrt(2).

    Taken from the data's short-run noise, not from a first fit, so the
    penalty does not depend on the breaks it is meant to select.
    """
    d = np.diff(y)
    mad = 1.4826 * np.median(np.abs(d - np.median(d)))
    return mad / np.sqrt(2)


def bic_penalty(y: np.ndarray) -> float:
    """Cost of one extra segment: params x sigma^2 x ln(n) (BIC for Gaussian residuals)."""
    return PARAMS_PER_SEGMENT * noise_sigma(y) ** 2 * np.log(len(y))


def detect_breaks(y: pd.Series) -> list[pd.Timestamp]:
    """PELT with a piecewise-linear trend: each regime has its own level and slope.

    Returns the first month of each new regime.
    """
    assert_monthly(y)
    values = y.to_numpy()
    algo = rpt.Pelt(model="linear", min_size=MIN_SEGMENT, jump=1).fit(_signal(values))
    ends = algo.predict(pen=bic_penalty(values))
    assert ends[-1] == len(values)
    return [y.index[i] for i in ends[:-1]]


def forced_breaks(y: pd.Series, n_max: int = 5) -> pd.Series:
    """Sensitivity: break dates when Binseg is forced to find exactly 1..n_max breaks."""
    assert_monthly(y)
    algo = rpt.Binseg(model="linear", min_size=MIN_SEGMENT, jump=1).fit(_signal(y.to_numpy()))
    out = {}
    for k in range(1, n_max + 1):
        ends = algo.predict(n_bkps=k)
        out[k] = ", ".join(f"{y.index[i]:%Y-%m}" for i in sorted(ends[:-1]))
    return pd.Series(out, name=y.name).rename_axis("n_breaks")


def edge_breaks(y: pd.Series, breaks: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """Breaks within EDGE_MONTHS of the start or end of the series.

    With a 12-month minimum regime, the first and last regimes are fitted on
    very few points, so breaks there are labelled as edge effects and not read.
    """
    pos = {d: i for i, d in enumerate(y.index)}
    return [b for b in breaks if pos[b] <= EDGE_MONTHS or pos[b] >= len(y) - EDGE_MONTHS]


def level_jump(fit: pd.Series, b: pd.Timestamp) -> float:
    """% change of the fitted trend at a break: new regime's first month vs old regime's last."""
    i = fit.index.get_loc(b)
    return float(100 * np.expm1(fit.iloc[i] - fit.iloc[i - 1]))


def segment_table(y: pd.Series, breaks: list[pd.Timestamp]) -> tuple[pd.DataFrame, pd.Series]:
    """OLS level + slope per regime. Returns a summary table and the fitted trend line."""
    edges = [y.index[0], *breaks, y.index[-1] + pd.offsets.MonthBegin()]
    rows, fitted = [], []
    for start, end in zip(edges[:-1], edges[1:]):
        seg = y[(y.index >= start) & (y.index < end)]
        t = np.arange(len(seg)) / 12
        slope, intercept = np.polyfit(t, seg.to_numpy(), 1)
        fitted.append(pd.Series(intercept + slope * t, index=seg.index))
        rows.append({"start": f"{seg.index[0]:%Y-%m}", "end": f"{seg.index[-1]:%Y-%m}",
                     "months": len(seg), "slope_pct_per_year": 100 * np.expm1(slope)})
    fit = pd.concat(fitted)
    assert len(fit) == len(y)
    return pd.DataFrame(rows), fit


def post_covid_vs_path(y: pd.Series, breaks: list[pd.Timestamp]) -> dict:
    """Compare the post-covid regime with 2016-2019.

    Post-covid regime = the last regime found by PELT if it starts in 2021 or
    later; otherwise Jan 2023 onwards.
    Primary measure: LEVEL, mean of the post-covid regime vs mean of 2016-2019
    (within +/-5% = level recovered).
    Secondary measure, fragile: the 2016-2019 trend (4 years) extrapolated over
    the post-covid regime (up to 7 years later); within +/-5% = on the old path.
    """
    start = breaks[-1] if breaks and breaks[-1] >= pd.Timestamp("2021-01-01") \
        else pd.Timestamp("2023-01-01")
    t = (y.index - y.index[0]).days / 365.25
    ref = (y.index >= "2016-01-01") & (y.index <= "2019-12-01")
    post = y.index >= start

    ref_slope, ref_icpt = np.polyfit(t[ref], y[ref], 1)
    post_slope = np.polyfit(t[post], y[post], 1)[0]
    gap = np.expm1(np.mean(y[post] - (ref_icpt + ref_slope * t[post])))
    level = np.expm1(y[post].mean() - y[ref].mean())

    level_verdict = ("level recovered" if abs(level) < LEVEL_TOLERANCE
                     else f"level {'above' if level > 0 else 'below'} 2016-2019")
    path_verdict = ("on the 2016-2019 growth path" if abs(gap) < PATH_TOLERANCE
                    else f"{'above' if gap > 0 else 'below'} the 2016-2019 growth path")
    return {"market": y.name, "post_covid_from": f"{start:%Y-%m}",
            "level_vs_2016_19_pct": 100 * level, "level_verdict": level_verdict,
            "slope_2016_19_pct_yr": 100 * np.expm1(ref_slope),
            "slope_post_covid_pct_yr": 100 * np.expm1(post_slope),
            "gap_vs_2016_19_path_pct": 100 * gap, "path_verdict": path_verdict}


# --- FX lag regressions ----------------------------------------------------
def fx_lags(x: pd.Series, lags: range, split: bool) -> pd.DataFrame:
    """Lagged FX regressors; with split=True, depreciation (x>0) and appreciation (x<0) parts.

    x = YoY log change of CHF per EUR: x > 0 means the franc weakened.
    """
    cols = {}
    for k in lags:
        xk = x.shift(k)
        if split:
            cols[f"dep_{k}"] = xk.clip(lower=0)      # franc weakens
            cols[f"app_{k}"] = xk.clip(upper=0)      # franc strengthens
        else:
            cols[f"fx_{k}"] = xk
    return pd.DataFrame(cols)


def sample_mask(y: pd.Series, X: pd.DataFrame) -> pd.Series:
    """Months with complete data and no covid month in t or t-12."""
    ok = y.notna() & X.notna().all(axis=1) & ~yoy_uses_covid(y.index)
    return ok


def fit_hac(y: pd.Series, X: pd.DataFrame, mask: pd.Series):
    """OLS with Newey-West (HAC) standard errors."""
    return sm.OLS(y[mask], sm.add_constant(X[mask])).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})


def _sum_test(res, names: list[str]) -> tuple[float, float, float]:
    """Estimate, standard error and p-value of the sum of several coefficients."""
    r = np.array([[1.0 if p in names else 0.0 for p in res.params.index]])
    tt = res.t_test(r)
    return float(tt.effect[0]), float(tt.sd[0, 0]), float(tt.pvalue)


def asymmetry_test(y: pd.Series, x: pd.Series, lags: range, mask: pd.Series) -> dict:
    """Sum of depreciation vs sum of appreciation effects; Wald H0: the two sums are equal."""
    X = fx_lags(x, lags, split=True)
    res = fit_hac(y, X, mask)
    dep = [f"dep_{k}" for k in lags]
    app = [f"app_{k}" for k in lags]
    d_est, d_se, d_p = _sum_test(res, dep)
    a_est, a_se, a_p = _sum_test(res, app)
    r = np.array([[1.0 if p in dep else -1.0 if p in app else 0.0 for p in res.params.index]])
    wald = res.wald_test(r, scalar=True)
    return {"market": y.name, "lags": f"{lags.start}-{lags.stop - 1}", "N": int(res.nobs),
            "sum_appreciation": a_est, "se_app": a_se, "p_app": a_p,
            "sum_depreciation": d_est, "se_dep": d_se, "p_dep": d_p,
            "wald_stat": float(np.squeeze(wald.statistic)), "wald_p": float(wald.pvalue)}


def cumulative_effect(y: pd.Series, x: pd.Series, lags: range, mask: pd.Series) -> pd.DataFrame:
    """Symmetric model: cumulative FX elasticity up to each lag, with 95% CI."""
    X = fx_lags(x, lags, split=False)
    res = fit_hac(y, X, mask)
    rows = []
    for k in lags:
        est, se, p = _sum_test(res, [f"fx_{j}" for j in lags if j <= k])
        rows.append({"lag": k, "cum_effect": est, "lo": est - 1.96 * se, "hi": est + 1.96 * se,
                     "p": p})
    return pd.DataFrame(rows).assign(market=y.name, N=int(res.nobs))


def lag_window_bic(y: pd.Series, x: pd.Series, first: int, last_max: int,
                   mask: pd.Series) -> pd.DataFrame:
    """BIC of symmetric models using FX lags first..L, for L = first..last_max (same sample)."""
    rows = []
    for last in range(first, last_max + 1):
        X = fx_lags(x, range(first, last + 1), split=False)
        res = fit_hac(y, X, mask)
        est, se, p = _sum_test(res, list(X.columns))
        rows.append({"lags": f"{first}-{last}", "last_lag": last, "bic": res.bic,
                     "sum_effect": est, "se_sum": se, "p_sum": p, "N": int(res.nobs)})
    return pd.DataFrame(rows).assign(market=y.name)
