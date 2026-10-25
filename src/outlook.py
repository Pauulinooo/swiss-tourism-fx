"""
Assemble the 12-month results used by notebook 05 and the BigQuery export:
the h = 1-12 post-covid backtest (from the two caches), 80% intervals and the outlook
from the Jul 2026 origin.
"""

import json

import numpy as np
import pandas as pd

import forecast as fc
import long_horizon as lh
import run_experiments as rx
import run_long_horizon as rl

FORWARD_FIT_START = pd.Timestamp("2024-01-01")       # forward-looking intervals: 2024 onwards (see below)
WINDOWS_OUTLOOK = {"next_12m": "Next 12 months (Aug 2026 - Jul 2027)",
                   "winter": "Winter 2026/27 (Dec 2026 - Mar 2027)"}


def load_backtest(panel: pd.DataFrame) -> pd.DataFrame:
    """Post-covid backtest for h = 1-12: h = 1-6 from Sprint 3B, h = 7-12 from run_long_horizon.

    Both caches must match the current code and data (fingerprints).
    """
    m3b = json.loads((rx.OUT / "fingerprint.json").read_text())
    assert m3b["fingerprint"] == rx.fingerprint(), "Sprint 3B cache is stale: python src/run_experiments.py"
    mlh = json.loads(rl.META.read_text())
    assert mlh["fingerprint"] == rl.fingerprint(), "h = 7-12 cache is stale: python src/run_long_horizon.py"
    short = pd.read_csv(rx.OUT / "base_post_covid.csv", parse_dates=["target_date", "origin_date"])
    long = pd.read_csv(rl.CACHE, parse_dates=["target_date", "origin_date"])
    res = fc.add_combinations(pd.concat([short, long], ignore_index=True))
    res["market"] = np.where(res["level"] == "resort", "Resort totals", res["origin"])
    res["month"] = res["target_date"].dt.month
    res = res.merge(fc.peak_months(panel), on=["series_id", "month"], how="left")
    res["peak"] = res["peak"].fillna(False).astype(bool)
    assert sorted(res["h"].unique()) == list(lh.HORIZONS_LONG)
    assert len(res) == 57 * 43 * 12 and not res.duplicated(["series_id", "h", "target_date"]).any()
    return res


# Target months each interval rule fits its q10/q90 on. "preset" and "check_preset" are the rules fixed
# before the results; the 2024+ rules were added AFTER seeing them (notebook 05): 2023 was the tail of
# covid (post-covid rebound, actuals far above forecasts), so, like the covid exclusion in the
# change-point analysis, it is left out of the intervals used for forward-looking numbers.
INTERVAL_RULES = {
    "preset": (fc.TEST_START, None),                         # all 43 months (pre-set rule for the outlook)
    "forward": (FORWARD_FIT_START, None),                    # 2024 - Jul 2026: outlook and fx_scenarios
    "check_preset": (fc.TEST_START, lh.CALIB_END),           # coverage check, pre-set: fit 2023-2024
    "check_2024": (FORWARD_FIT_START, lh.CALIB_END),         # coverage check, 2024+ rule: fit 2024 only
}


def interval_quantiles(res: pd.DataFrame, rule: str) -> dict[str, pd.DataFrame]:
    """q10/q90 per horizon x market for each interval column, fitted on the target months of `rule`."""
    start, end = INTERVAL_RULES[rule]
    fit = res[(res["target_date"] >= start) & (res["target_date"] <= (end or res["target_date"].max()))]
    assert fit["target_date"].nunique() == {"preset": 43, "forward": 31, "check_preset": 24, "check_2024": 12}[rule]
    return {col: lh.fit_quantiles(fit, col) for col in lh.INTERVAL_COLS}


def with_intervals(df: pd.DataFrame, q: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Bounds for the model with FX (lower_80/upper_80) and the combination (combo_lower_80/...)."""
    df = lh.apply_interval(df, q["gb_fx"], "gb_fx")
    return lh.apply_interval(df, q["combo_fx"], "combo_fx", prefix="combo_")


def coverage_table(res: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample coverage of the 80% intervals on Jan 2025 - Jul 2026, by horizon x market, for the
    model with FX and the combination, under the pre-set rule (fitted on 2023-2024) and the 2024+ rule
    (fitted on 2024 only)."""
    parts = []
    for rule, label in [("check_preset", "pre-set: fitted on 2023-2024"), ("check_2024", "2024+: fitted on 2024")]:
        ev = with_intervals(res[res["target_date"] >= lh.EVAL_START], interval_quantiles(res, rule))
        for col, lo, hi in [("gb_fx", "lower_80", "upper_80"), ("combo_fx", "combo_lower_80", "combo_upper_80")]:
            c = ev.assign(inside=ev["actual"].between(ev[lo], ev[hi]))
            g = c.groupby(["h", "market"], as_index=False).agg(n_inside=("inside", "sum"), n=("inside", "size"))
            parts.append(g.assign(model=col, model_label={**fc.MODELS, **fc.COMBOS}[col], rule=rule, rule_label=label))
    out = pd.concat(parts, ignore_index=True)
    out["coverage_pct"] = 100 * out["n_inside"] / out["n"]
    assert len(out) == 2 * 2 * 12 * 8
    return out


def build_outlook(panel: pd.DataFrame, fx_yoy: pd.DataFrame, q: dict[str, pd.DataFrame],
                  models: dict | None = None) -> pd.DataFrame:
    """Monthly forecasts Aug 2026 - Jul 2027 from the Jul 2026 origin, with 80% intervals."""
    models = models or lh.forecast_from_origin(panel, fx_yoy)
    rows = []
    for h, (model, test) in models.items():
        rows.append(test[["series_id", "level", "geo", "origin", "resort_type", "h", "origin_date",
                          "target_date", "base_nights", "currency"]].assign(gb_fx=lh.predict(model, test)))
    out = pd.concat(rows, ignore_index=True).rename(columns={"base_nights": "naive"})
    out["combo_fx"] = (out["naive"] + out["gb_fx"]) / 2
    out["market"] = np.where(out["level"] == "resort", "Resort totals", out["origin"])
    out["in_winter"] = out["target_date"].between(*lh.WINTER)
    out = with_intervals(out, q)
    assert len(out) == 57 * 12 and out["target_date"].min() == lh.OUTLOOK_ORIGIN + pd.DateOffset(months=1)
    assert out.groupby("series_id")["in_winter"].sum().eq(4).all()
    return out
