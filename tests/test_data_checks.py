"""Data-quality guards: rolling 12-month windows and the monthly-vs-annual totals check."""

import pandas as pd
import pytest

from features import rolling_12m_sum
from load_data import quality_checks


# --- rolling_12m_sum ---------------------------------------------------------
def _monthly(dates, value=1.0, group="A"):
    return pd.DataFrame({"date": dates, "g": group, "v": value})


def test_rolling_12m_sum_on_complete_months():
    df = _monthly(pd.date_range("2020-01-01", "2021-06-01", freq="MS"))
    df["v"] = range(1, len(df) + 1)
    out = rolling_12m_sum(df, "v", ["g"])
    assert len(out) == 18 - 11
    assert out["date"].iloc[0] == pd.Timestamp("2020-12-01") and out["rolling_12m"].iloc[0] == sum(range(1, 13))


def test_rolling_12m_sum_detects_a_missing_month():
    dates = pd.date_range("2020-01-01", "2021-06-01", freq="MS").delete(5)   # June 2020 missing
    with pytest.raises(AssertionError, match="12 consecutive months"):
        rolling_12m_sum(_monthly(dates), "v", ["g"])


def test_rolling_12m_sum_keeps_groups_apart():
    a = _monthly(pd.date_range("2020-01-01", "2020-12-01", freq="MS"), 1.0, "A")
    b = _monthly(pd.date_range("2020-01-01", "2020-12-01", freq="MS"), 10.0, "B")
    out = rolling_12m_sum(pd.concat([b, a]), "v", ["g"]).set_index("g")["rolling_12m"]
    assert out.to_dict() == {"A": 12.0, "B": 120.0}


# --- load_data.quality_checks ------------------------------------------------
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _hesta_csv(path, geo_col, monthly, annual):
    """A BFS-style export: semicolon, cp1252, '...' = suppressed, annual total rows mixed in.

    2018 is always complete and consistent; `monthly` and `annual` set 2019 (the year under test).
    """
    rows = []
    for year, months, total in [(2018, [50] * 12, 600), (2019, monthly, annual)]:
        rows += [{"Year": year, "Month": m, geo_col: "Graubünden", "Germany Overnight stays": v,
                  "Germany Arrivals": "..." if v == "..." else 1} for m, v in zip(MONTHS, months)]
        rows.append({"Year": year, "Month": "Total of the year", geo_col: "Graubünden",
                     "Germany Overnight stays": total, "Germany Arrivals": 12})
    pd.DataFrame(rows).to_csv(path, sep=";", index=False, encoding="cp1252")
    return path


def test_quality_checks_pass_when_months_add_up(tmp_path):
    canton = _hesta_csv(tmp_path / "c.csv", "Canton", [100] * 12, 1200)
    commune = _hesta_csv(tmp_path / "m.csv", "Commune", [10] * 12, 120)
    quality_checks(canton, commune)


def test_quality_checks_fail_when_months_do_not_add_up(tmp_path):
    canton = _hesta_csv(tmp_path / "c.csv", "Canton", [100] * 12, 1201)
    commune = _hesta_csv(tmp_path / "m.csv", "Commune", [10] * 12, 120)
    with pytest.raises(AssertionError, match="c.csv"):
        quality_checks(canton, commune)


def test_quality_checks_skip_years_with_a_suppressed_month(tmp_path):
    """A suppressed month cannot be checked: the published total includes it, the monthly sum cannot."""
    canton = _hesta_csv(tmp_path / "c.csv", "Canton", [100] * 11 + ["..."], 1250)
    commune = _hesta_csv(tmp_path / "m.csv", "Commune", [10] * 12, 120)
    quality_checks(canton, commune)
