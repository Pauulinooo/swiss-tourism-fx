"""Small synthetic data shared by the tests (no raw files, no database)."""

import numpy as np
import pandas as pd
import pytest

DATES = pd.date_range("2014-01-01", "2019-12-01", freq="MS")
ORIGINS = ["Germany", "France", "Switzerland", "United States"]


@pytest.fixture
def panel() -> pd.DataFrame:
    """4 canton x origin series, 6 years, seasonal pattern plus noise."""
    rng = np.random.default_rng(0)
    season = 1 + 0.4 * np.sin(2 * np.pi * DATES.month / 12)
    rows = []
    for i, origin in enumerate(ORIGINS):
        nights = (1000 * (i + 1) * season * rng.lognormal(0, 0.05, len(DATES))).round()
        rows.append(pd.DataFrame({"date": DATES, "level": "canton", "geo": "Testkanton", "origin": origin,
                                  "nights": nights, "series_id": f"Testkanton | {origin}",
                                  "resort_type": None}))
    return pd.concat(rows, ignore_index=True)


@pytest.fixture
def fx_yoy() -> pd.DataFrame:
    """YoY FX change for EUR and USD over the panel's months (random walk, distinct per currency)."""
    rng = np.random.default_rng(1)
    return pd.concat([pd.DataFrame({"date": DATES, "currency": cur,
                                    "fx_yoy": np.cumsum(rng.normal(0, 0.01, len(DATES)))})
                      for cur in ["EUR", "USD"]], ignore_index=True)
