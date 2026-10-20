"""
Feature helpers shared by notebooks and models.
"""

import numpy as np
import pandas as pd

COVID_START, COVID_END = pd.Timestamp("2020-03-01"), pd.Timestamp("2021-12-01")


def rolling_12m_sum(df: pd.DataFrame, value: str, by: list[str]) -> pd.DataFrame:
    """Trailing 12-month sum of `value` per group, one row per month.

    Rolling over rows is only a 12-month window if no month is missing:
    a gap would silently turn it into a 13+ month window. So every window
    is asserted to span exactly 12 consecutive months.
    """
    df = df.sort_values([*by, "date"]).copy()
    month_idx = df["date"].dt.year * 12 + df["date"].dt.month
    grouped = df.groupby(by, sort=False)

    df["rolling_12m"] = grouped[value].transform(lambda s: s.rolling(12, min_periods=12).sum())
    # Distance (in months) between the last and the first month of each window
    span = month_idx - month_idx.groupby([df[c] for c in by], sort=False).shift(11)

    full = df["rolling_12m"].notna()
    assert (span[full] == 11).all(), "a rolling window does not cover 12 consecutive months"
    assert full.any(), "no complete 12-month window"
    return df[full].reset_index(drop=True)


def assert_monthly(s: pd.Series) -> None:
    """The index must be consecutive month starts: shift(12) then means 'same month last year'."""
    idx = pd.DatetimeIndex(s.index)
    expected = pd.date_range(idx.min(), idx.max(), freq="MS")
    assert idx.equals(expected), f"{s.name}: index is not a gap-free monthly series"


def deseasonalized_log(s: pd.Series) -> pd.Series:
    """log(s) minus its month-of-year mean, so trend breaks are not just winter vs summer."""
    assert_monthly(s)
    assert (s > 0).all(), f"{s.name}: log needs positive values"
    log = np.log(s)
    return log - log.groupby(log.index.month).transform("mean")


def yoy_log_change(s: pd.Series) -> pd.Series:
    """log(s_t) - log(s_t-12): year-over-year change, which also removes seasonality."""
    assert_monthly(s)
    return np.log(s) - np.log(s.shift(12))


def yoy_uses_covid(index: pd.DatetimeIndex) -> np.ndarray:
    """True where a year-over-year change touches a covid month, in t or in t-12.

    This extends the covid exclusion to 2022, whose base months (2021) are covid months.
    """
    idx = pd.DatetimeIndex(index)
    base = idx - pd.DateOffset(years=1)
    in_covid = lambda d: (d >= COVID_START) & (d <= COVID_END)
    return np.asarray(in_covid(idx) | in_covid(base))
