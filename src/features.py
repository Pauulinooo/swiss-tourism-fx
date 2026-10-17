"""
Feature helpers shared by notebooks and models.
"""

import pandas as pd


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
