"""
Sprint 4: forecasts up to 12 months ahead, 80% prediction intervals and the 12-month / winter outlook.

Reuses forecast.py unchanged (same features, model, rules). forecast.py is part of the
Sprint 3B cache fingerprint, so instead of editing its HORIZONS constant we widen it
temporarily with the `horizons` context manager below.
"""

from contextlib import contextmanager

import numpy as np
import pandas as pd

import forecast as fc

HORIZONS_LONG = range(1, 13)
OUTLOOK_ORIGIN = pd.Timestamp("2026-07-01")          # last month with nights for all 57 series
WINTER = (pd.Timestamp("2026-12-01"), pd.Timestamp("2027-03-01"))   # winter season 2026/27
CALIB_END = pd.Timestamp("2024-12-01")               # intervals fitted on 2023-2024 targets ...
EVAL_START = pd.Timestamp("2025-01-01")              # ... and checked on Jan 2025 - Jul 2026
LEVEL = 0.80
Q_LO, Q_HI = (1 - LEVEL) / 2, 1 - (1 - LEVEL) / 2
INTERVAL_COLS = ["gb_fx", "combo_fx"]


@contextmanager
def horizons(hs):
    """Temporarily set forecast.HORIZONS (e.g. to 1-12) and restore it afterwards.

    Why: forecast.py checks every horizon against HORIZONS (= 1-6). Editing that file
    would change the fingerprint of the Sprint 3B experiment cache (~1 h 45 min to
    rebuild) although nothing it computes changes; a scoped override keeps the file,
    and therefore the cache, valid. Not thread-safe: use it in one process at a time
    (joblib's default process workers are fine).
    """
    original = fc.HORIZONS
    fc.HORIZONS = range(min(hs), max(hs) + 1)
    try:
        yield fc.HORIZONS
    finally:
        fc.HORIZONS = original
    assert fc.HORIZONS is original, "forecast.HORIZONS was not restored"


# --- Forecast from one origin ------------------------------------------------
def forecast_from_origin(panel: pd.DataFrame, fx_yoy: pd.DataFrame, origin: pd.Timestamp = OUTLOOK_ORIGIN,
                         hs=HORIZONS_LONG) -> dict[int, tuple]:
    """Fit the model with FX for each horizon on all targets <= origin.

    Returns {h: (model, rows forecast at the origin)}; used for the outlook and the FX scenarios.
    """
    out = {}
    with horizons(hs):
        for h in hs:
            feats = fc.build_features(panel, fx_yoy, h)
            cols = fc.feature_list(use_fx=True)
            train = feats[(feats["target_date"] <= origin) & feats["target"].notna()]
            test = feats[(feats["origin_date"] == origin) & feats["y_base"].notna()].copy()
            assert train["origin_date"].max() < origin and train["target_date"].max() <= origin
            assert test["series_id"].nunique() == panel["series_id"].nunique()
            out[h] = (fc.make_model().fit(train[cols], train["target"]), test)
    return out


def predict(model, test: pd.DataFrame, fx_shift: float = 0.0, currencies=None) -> np.ndarray:
    """Nights forecast; optionally with the FX feature at the origin moved by log(1 + fx_shift)."""
    x = test[fc.feature_list(use_fx=True)].copy()
    if fx_shift:
        hit = test["currency"].isin(currencies).to_numpy()
        x.loc[hit, fc.FX_FEATURE] += np.log1p(fx_shift)
    return np.clip(np.expm1(test["y_base"].to_numpy() + model.predict(x)), 0, None)


# --- Prediction intervals ----------------------------------------------------
def log_error(actual, forecast):
    """Multiplicative error, comparable across series of very different size."""
    return np.log1p(actual) - np.log1p(forecast)


def fit_quantiles(res: pd.DataFrame, col: str) -> pd.DataFrame:
    """q10 / q90 of the log error per horizon x market."""
    e = res.assign(e=log_error(res["actual"], res[col]))
    q = e.groupby(["h", "market"])["e"].quantile([Q_LO, Q_HI]).unstack()
    q.columns = ["q_lo", "q_hi"]
    q["n"] = e.groupby(["h", "market"]).size()
    assert (q["q_lo"] < q["q_hi"]).all() and q.notna().all().all()
    return q.reset_index()


def apply_interval(df: pd.DataFrame, q: pd.DataFrame, col: str, prefix: str = "") -> pd.DataFrame:
    """Add lower/upper bounds for forecast column `col` (rows need h and market)."""
    m = df.merge(q[["h", "market", "q_lo", "q_hi"]], on=["h", "market"], how="left", validate="many_to_one")
    assert m["q_lo"].notna().all(), "no interval for some horizon x market"
    m[f"{prefix}lower_80"] = np.clip(np.expm1(np.log1p(m[col]) + m["q_lo"]), 0, None)
    m[f"{prefix}upper_80"] = np.expm1(np.log1p(m[col]) + m["q_hi"])
    return m.drop(columns=["q_lo", "q_hi"])


def coverage(df: pd.DataFrame, by: list[str], lo: str = "lower_80", hi: str = "upper_80") -> pd.DataFrame:
    """Share of actuals inside the interval, in %."""
    inside = df["actual"].between(df[lo], df[hi])
    g = df.assign(inside=inside).groupby(by, observed=True) if by else [((), df.assign(inside=inside))]
    rows = [dict(zip(by, k if isinstance(k, tuple) else (k,)), coverage=100 * x["inside"].mean(), n=len(x))
            for k, x in g]
    return pd.DataFrame(rows)


# --- Totals over several months from one origin --------------------------------
def window_totals(df: pd.DataFrame, origin_col: str, months: pd.DatetimeIndex, by: list[str],
                  cols: list[str]) -> pd.DataFrame:
    """Sum forecasts, bounds and actuals over target months made from the same origin.

    Bounds are summed month by month: this assumes the months' errors move together,
    a conservative (wide) choice for a total.
    """
    sub = df[df["target_date"].isin(months)]
    n_months = sub.groupby([origin_col, "series_id"])["target_date"].nunique()
    assert (n_months == len(months)).all(), "a total must cover every month of the window"
    return sub.groupby([origin_col, *by], as_index=False)[cols].sum()
