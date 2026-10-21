"""
Forecasting monthly hotel nights 1-6 months ahead (Sprint 3).

Direct strategy: one global gradient-boosting model per horizon h, trained on
all 57 series (49 canton x origin + 8 paired-resort totals). The model predicts
the seasonal log change log1p(y[t+h]) - log1p(y[t+h-12]), i.e. a correction to
the seasonal-naive forecast. Every feature is known at the forecast origin t.

Backend: scikit-learn's HistGradientBoostingRegressor by default, because
LightGBM could not be installed on the development machine (no libomp);
"lightgbm" is used only if requested and importable.
"""

import numpy as np
import pandas as pd

from features import COVID_END, COVID_START, assert_monthly

HORIZONS = range(1, 7)
TEST_START, TEST_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2026-07-01")
POST_COVID_START = pd.Timestamp("2022-01-01")      # calendar rule, known at every origin
PEAK_YEARS = (2013, 2019)                           # pre-covid window common to all series
N_PEAK_MONTHS = 3

RESORTS = {"St. Moritz": "luxury", "Klosters": "luxury", "Zermatt": "luxury", "Saanen": "luxury",
           "Scuol": "mid-range", "Tujetsch": "mid-range", "Saas-Grund": "mid-range", "Lenk": "mid-range"}
ORIGIN_CURRENCY = {"Switzerland": None, "Germany": "EUR", "France": "EUR", "Italy": "EUR",
                   "United Kingdom": "GBP", "United States": "USD", "China": "CNY"}
RESORT_CURRENCY = "EUR"     # Germany is the largest foreign market in the resorts

# Fixed, modest hyperparameters: nothing is tuned on the test period
PARAMS = {"n_trees": 400, "learning_rate": 0.03, "leaves": 15, "min_leaf": 20,
          "col_sample": 0.8, "row_sample": 0.8, "seed": 42}

CATEGORICAL = ["level", "geo", "origin"]
BASE_FEATURES = ["y_t", "y_t1", "y_t2", "y_base", "y_base2", "roll3", "roll12", "yoy_t",
                 "target_month", "covid_target", "covid_base", "covid_origin", "post_covid",
                 *CATEGORICAL]
FX_FEATURE = "fx_yoy"
NOT_FEATURES = {"target", "actual", "y_target", "base_nights", "target_date", "origin_date"}


def _in_covid(d: pd.Series) -> pd.Series:
    return (d >= COVID_START) & (d <= COVID_END)


# --- Data ------------------------------------------------------------------
def load_panel(con) -> pd.DataFrame:
    """57 monthly series in long format: canton x origin (49) + resort totals (8).

    Resort total = sum of the 7 tracked markets; a suppressed (small) market
    counts as 0 and the month is flagged `partial`.
    """
    canton = con.sql("""
        SELECT date, 'canton' AS level, geo, origin, nights, FALSE AS partial
        FROM monthly_nights WHERE level = 'canton'
    """).df()
    resort = con.sql(f"""
        SELECT date, 'resort' AS level, geo, 'Total' AS origin,
               SUM(nights) AS nights, COUNT(*) < 7 AS partial
        FROM monthly_nights
        WHERE level = 'commune' AND geo IN {tuple(RESORTS)}
        GROUP BY date, geo
    """).df()
    panel = pd.concat([canton, resort], ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["series_id"] = np.where(panel["level"] == "resort", panel["geo"] + " (resort)",
                                  panel["geo"] + " | " + panel["origin"])
    panel["resort_type"] = panel["geo"].map(RESORTS)
    panel = panel.sort_values(["series_id", "date"]).reset_index(drop=True)

    assert panel["series_id"].nunique() == 57, "expected 49 canton x origin + 8 resort series"
    assert (panel["nights"] >= 0).all() and panel["nights"].notna().all()
    for sid, g in panel.groupby("series_id"):
        assert_monthly(g.set_index("date")["nights"].rename(sid))
    return panel


def load_fx_yoy(con) -> pd.DataFrame:
    """YoY log change of CHF per unit of each currency, by month (x > 0 = weaker franc)."""
    fx = con.sql("SELECT date, currency, chf_per_unit FROM fx").df()
    fx["date"] = pd.to_datetime(fx["date"])
    out = []
    for cur, g in fx.groupby("currency"):
        s = g.set_index("date")["chf_per_unit"].sort_index().rename(cur)
        assert_monthly(s)
        out.append(np.log(s).diff(12).rename("fx_yoy").reset_index().assign(currency=cur))
    return pd.concat(out, ignore_index=True).dropna()


def peak_months(panel: pd.DataFrame, years: tuple[int, int] = PEAK_YEARS) -> pd.DataFrame:
    """Each series' N_PEAK_MONTHS highest months by average share of annual nights, 2013-2019.

    Only complete years count; the window must end before the test period
    (2013-2019 for the post-covid test, 2005-2010 for the shock windows).
    """
    p = panel[panel["date"].dt.year.between(*years)].copy()
    p["year"], p["month"] = p["date"].dt.year, p["date"].dt.month
    full = p.groupby(["series_id", "year"])["month"].transform("count") == 12
    p = p[full]
    p["share"] = p["nights"] / p.groupby(["series_id", "year"])["nights"].transform("sum")
    prof = p.groupby(["series_id", "month"])["share"].mean().reset_index()
    top = prof.sort_values("share", ascending=False).groupby("series_id").head(N_PEAK_MONTHS)
    assert top.groupby("series_id").size().eq(N_PEAK_MONTHS).all()
    assert top["series_id"].nunique() == panel["series_id"].nunique()
    return top[["series_id", "month"]].assign(peak=True)


# --- Features --------------------------------------------------------------
def build_features(panel: pd.DataFrame, fx_yoy: pd.DataFrame, h: int) -> pd.DataFrame:
    """One row per series x forecast origin t, for horizon h.

    Every feature uses data at month t or earlier (shifts >= 0); only the
    target columns look forward. The target is the seasonal log change
    log1p(y[t+h]) - log1p(y[t+h-12]).
    """
    assert h in HORIZONS
    parts = []
    for sid, g in panel.groupby("series_id", sort=False):
        g = g.set_index("date")
        ly = np.log1p(g["nights"])
        f = pd.DataFrame(index=g.index.rename("origin_date"))
        f["y_t"], f["y_t1"], f["y_t2"] = ly, ly.shift(1), ly.shift(2)
        f["y_base"] = ly.shift(12 - h)            # same month last year (month t+h-12 <= t)
        f["y_base2"] = ly.shift(24 - h)           # same month two years ago
        f["roll3"] = ly.rolling(3).mean()
        f["roll12"] = ly.rolling(12).mean()
        f["yoy_t"] = ly - ly.shift(12)
        f["y_target"] = ly.shift(-h)
        f["actual"] = g["nights"].shift(-h)
        f["base_nights"] = g["nights"].shift(12 - h)
        for col in ["level", "geo", "origin", "resort_type"]:
            f[col] = g[col].iloc[0]
        f["series_id"] = sid
        parts.append(f.reset_index())
    df = pd.concat(parts, ignore_index=True)

    df["target_date"] = df["origin_date"] + pd.DateOffset(months=h)
    df["target"] = df["y_target"] - df["y_base"]
    df["target_month"] = df["target_date"].dt.month
    df["covid_target"] = _in_covid(df["target_date"]).astype(int)
    df["covid_base"] = _in_covid(df["target_date"] - pd.DateOffset(years=1)).astype(int)
    df["covid_origin"] = _in_covid(df["origin_date"]).astype(int)
    df["post_covid"] = (df["target_date"] >= POST_COVID_START).astype(int)

    # FX: the market's own currency at the origin month (= lag h of the target); 0 for Swiss guests
    df["currency"] = np.where(df["level"] == "resort", RESORT_CURRENCY, df["origin"].map(ORIGIN_CURRENCY))
    df = df.merge(fx_yoy.rename(columns={"date": "origin_date"}), on=["origin_date", "currency"], how="left")
    df.loc[df["currency"].isna(), FX_FEATURE] = 0.0
    df["h"] = h

    for col in CATEGORICAL:
        df[col] = df[col].astype("category")
    assert not set(BASE_FEATURES + [FX_FEATURE]) & NOT_FEATURES
    return df


# --- Models ----------------------------------------------------------------
def make_model(backend: str = "sklearn"):
    """Gradient-boosted trees with fixed hyperparameters (see PARAMS)."""
    if backend == "sklearn":
        from sklearn.ensemble import HistGradientBoostingRegressor
        # No row subsampling in HGB; col_sample maps to max_features
        return HistGradientBoostingRegressor(
            max_iter=PARAMS["n_trees"], learning_rate=PARAMS["learning_rate"],
            max_leaf_nodes=PARAMS["leaves"], min_samples_leaf=PARAMS["min_leaf"],
            max_features=PARAMS["col_sample"], categorical_features="from_dtype",
            early_stopping=False, random_state=PARAMS["seed"])
    if backend == "lightgbm":
        try:
            from lightgbm import LGBMRegressor
        except (ImportError, OSError) as err:
            raise RuntimeError("LightGBM is not usable on this machine; use backend='sklearn'") from err
        return LGBMRegressor(
            n_estimators=PARAMS["n_trees"], learning_rate=PARAMS["learning_rate"],
            num_leaves=PARAMS["leaves"], min_child_samples=PARAMS["min_leaf"],
            colsample_bytree=PARAMS["col_sample"], subsample=PARAMS["row_sample"],
            subsample_freq=1, random_state=PARAMS["seed"], verbose=-1)
    raise ValueError(f"unknown backend: {backend}")


def feature_list(use_fx: bool) -> list[str]:
    return BASE_FEATURES + ([FX_FEATURE] if use_fx else [])


def fit_predict(feats: pd.DataFrame, origin: pd.Timestamp, use_fx: bool,
                backend: str = "sklearn") -> pd.DataFrame:
    # `origin` here is the forecast origin date; the market column is also called "origin"
    """Train on rows whose target month is <= origin, forecast the rows made at origin."""
    cols = feature_list(use_fx)
    train = feats[(feats["target_date"] <= origin) & feats["target"].notna()]
    test = feats[(feats["origin_date"] == origin) & feats["y_base"].notna()]
    # No look-ahead: nothing in training is dated after the origin
    assert train["target_date"].max() <= origin and train["origin_date"].max() < origin
    assert len(test) > 0
    model = make_model(backend).fit(train[cols], train["target"])
    log_pred = test["y_base"] + model.predict(test[cols])
    return test[["series_id", "level", "geo", "origin", "resort_type", "h", "origin_date", "target_date",
                 "actual", "base_nights"]].assign(forecast=np.clip(np.expm1(log_pred), 0, None))


def backtest(panel: pd.DataFrame, fx_yoy: pd.DataFrame, backend: str = "sklearn",
             targets: pd.DatetimeIndex | None = None, run_no_fx: bool = True,
             run_fx: bool = True) -> pd.DataFrame:
    """Rolling origin: the same target months for every horizon, origin = target - h.

    Default targets: the post-covid test (Jan 2023 - Jul 2026, 43 months). Other
    windows (e.g. the 2015 shock) pass their own `targets`; the panel passed in
    defines which series are trained and evaluated.

    Returns one row per series x horizon x target month with the actual value and
    the forecasts of the seasonal-naive baseline and of the model without / with FX.
    """
    if targets is None:
        targets = pd.date_range(TEST_START, TEST_END, freq="MS")
    assert run_no_fx or run_fx
    out = []
    for h in HORIZONS:
        feats = build_features(panel, fx_yoy, h)
        for target in targets:
            origin = target - pd.DateOffset(months=h)
            parts = []
            if run_no_fx:
                parts.append(fit_predict(feats, origin, use_fx=False, backend=backend)
                             .rename(columns={"forecast": "gb_no_fx"}))
            if run_fx:
                parts.append(fit_predict(feats, origin, use_fx=True, backend=backend)
                             .rename(columns={"forecast": "gb_fx"}))
            merged = parts[0]
            if len(parts) == 2:
                merged = merged.merge(parts[1][["series_id", "gb_fx"]], on="series_id")
            out.append(merged)
    res = pd.concat(out, ignore_index=True).rename(columns={"base_nights": "naive"})
    res = res[res["target_date"].between(targets.min(), targets.max())]

    assert not _in_covid(res["target_date"]).any(), "covid months must never be evaluated"
    assert res["actual"].notna().all() and res["naive"].notna().all()
    assert len(res) == panel["series_id"].nunique() * len(targets) * len(HORIZONS), "missing forecasts"
    return res.reset_index(drop=True)


def check_no_lookahead(panel: pd.DataFrame, fx_yoy: pd.DataFrame, h: int, origin: pd.Timestamp,
                       backend: str = "sklearn") -> float:
    """Scramble every value after the origin; forecasts made at the origin must not change."""
    fake = panel.copy()
    future = fake["date"] > origin
    fake.loc[future, "nights"] = fake.loc[future, "nights"] * 3 + 1000
    fx_fake = fx_yoy.copy()
    fx_fake.loc[fx_fake["date"] > origin, "fx_yoy"] += 0.5
    a = fit_predict(build_features(panel, fx_yoy, h), origin, use_fx=True, backend=backend)
    b = fit_predict(build_features(fake, fx_fake, h), origin, use_fx=True, backend=backend)
    diff = float(np.abs(a["forecast"].to_numpy() - b["forecast"].to_numpy()).max())
    assert diff == 0.0, f"forecast changed by {diff} when future data changed: look-ahead"
    return diff


# --- Metrics ---------------------------------------------------------------
MODELS = {"naive": "Seasonal naive", "gb_no_fx": "Model without FX", "gb_fx": "Model with FX"}
COMBOS = {"combo_no_fx": "Naive + model without FX", "combo_fx": "Naive + model with FX"}


def wape(actual: pd.Series, forecast: pd.Series) -> float:
    """Sum of absolute errors / sum of actuals, in %. Robust to small and near-zero months."""
    assert actual.sum() > 0
    return float(100 * (actual - forecast).abs().sum() / actual.sum())


def mape(actual: pd.Series, forecast: pd.Series) -> float:
    """Mean absolute % error over months with actual > 0 (secondary: explodes on small months)."""
    ok = actual > 0
    return float(100 * ((actual[ok] - forecast[ok]).abs() / actual[ok]).mean())


def wape_table(res: pd.DataFrame, by: list[str], cols: list[str] | None = None) -> pd.DataFrame:
    """WAPE per group for the given forecast columns (default: the three models),
    plus the FX gain (no FX minus with FX, in points) when both models are present."""
    cols = list(MODELS) if cols is None else cols
    rows = []
    for key, g in res.groupby(by, observed=True) if by else [((), res)]:
        row = dict(zip(by, key if isinstance(key, tuple) else (key,)))
        for col in cols:
            row[col] = wape(g["actual"], g[col])
        if {"gb_no_fx", "gb_fx"} <= set(cols):
            row["fx_gain"] = row["gb_no_fx"] - row["gb_fx"]
        row["n"] = len(g)
        rows.append(row)
    return pd.DataFrame(rows)


# --- Sprint 3B: noise floor, Diebold-Mariano, combinations -------------------
MIN_SHIFT = 24      # months: a circular shift must move FX at least 2 years away from its true date


def shift_fx(fx_yoy: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, int]:
    """Circularly shift the FX series in time by k months (same k for all currencies).

    Unlike a plain shuffle, a circular shift keeps FX's autocorrelation and the
    co-movement between currencies; it only breaks the link with the calendar.
    k is drawn between MIN_SHIFT and n - MIN_SHIFT.
    """
    wide = fx_yoy.pivot(index="date", columns="currency", values="fx_yoy").sort_index()
    assert wide.notna().all().all(), "currencies must cover the same months"
    assert_monthly(wide.iloc[:, 0])
    n = len(wide)
    k = int(np.random.default_rng(seed).integers(MIN_SHIFT, n - MIN_SHIFT + 1))
    rolled = pd.DataFrame(np.roll(wide.to_numpy(), k, axis=0), index=wide.index, columns=wide.columns)
    out = rolled.reset_index().melt(id_vars="date", var_name="currency", value_name="fx_yoy")
    assert len(out) == len(fx_yoy)
    return out, k


def dm_test(d: np.ndarray, h: int = max(HORIZONS)) -> tuple[float, float]:
    """Diebold-Mariano test that the mean loss differential d is 0 (two-sided).

    Newey-West variance with h-1 lags; Harvey-Leybourne-Newbold small-sample
    correction; Student t with T-1 degrees of freedom.
    """
    from scipy import stats
    d = np.asarray(d, dtype=float)
    T = len(d)
    assert T > 2 * h, "too few months for a DM test"
    dc = d - d.mean()
    var = dc @ dc / T
    for lag in range(1, h):
        var += 2 * (1 - lag / h) * (dc[lag:] @ dc[:-lag]) / T
    stat = d.mean() / np.sqrt(var / T)
    stat *= np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    p = 2 * stats.t.sf(abs(stat), df=T - 1)
    return float(stat), float(p)


def holm(pvalues: pd.Series) -> pd.Series:
    """Holm step-down adjustment of a set of p-values."""
    order = pvalues.sort_values()
    m = len(order)
    adj = np.maximum.accumulate([(m - i) * p for i, p in enumerate(order)])
    return pd.Series(np.minimum(adj, 1.0), index=order.index).reindex(pvalues.index)


def loss_differential(res: pd.DataFrame, a: str, b: str) -> pd.Series:
    """Monthly WAPE-scaled loss gap: sum(|err a| - |err b|) / sum(actual), over series and horizons."""
    g = res.assign(diff=(res["actual"] - res[a]).abs() - (res["actual"] - res[b]).abs())
    out = g.groupby("target_date").apply(lambda x: x["diff"].sum() / x["actual"].sum(), include_groups=False)
    return 100 * out.sort_index()


def add_combinations(res: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight averages of the seasonal naive and each model (no weights tuned)."""
    return res.assign(combo_no_fx=(res["naive"] + res["gb_no_fx"]) / 2,
                      combo_fx=(res["naive"] + res["gb_fx"]) / 2)
