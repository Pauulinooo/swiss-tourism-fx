"""
Build the DuckDB database used for the SQL layer.

Loads the processed tidy tables (tourism_long.csv, fx_long.csv) into
data/processed/tourism.duckdb, creates every view in sql/ in numbered order,
runs the quality checks and prints a short summary of each view.

Run after `python src/load_data.py`.
"""

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
SQL = ROOT / "sql"
DB_PATH = PROCESSED / "tourism.duckdb"

# Tolerance for "shares add up to 100%" (floating point sums)
TOL = 1e-9

SUMMARIES = {
    "monthly_nights": """
        SELECT level, COUNT(*) AS rows, COUNT(DISTINCT geo) AS geos,
               MIN(date) AS first_month, MAX(date) AS last_month,
               SUM(is_covid::INT) AS covid_rows
        FROM monthly_nights GROUP BY level ORDER BY level""",
    "yoy_change": """
        -- 2015 = year of the franc shock (EUR floor removed on 15 Jan 2015)
        SELECT origin, ROUND(MEDIAN(yoy_pct), 1) AS median_yoy_pct_2015
        FROM yoy_change
        WHERE level = 'canton' AND year(date) = 2015
        GROUP BY origin ORDER BY median_yoy_pct_2015""",
    "market_share": """
        PIVOT (SELECT geo, origin, ROUND(share_of_tracked_pct, 1) AS share
               FROM market_share WHERE level = 'canton' AND year = 2019)
        ON origin USING first(share) ORDER BY geo""",
    "seasonal_profile": """
        SELECT level, geo, arg_max(month, avg_share_pct) AS peak_month,
               ROUND(MAX(avg_share_pct), 1) AS peak_share_pct, MIN(n_years) AS n_years
        FROM seasonal_profile GROUP BY level, geo ORDER BY level, peak_share_pct DESC""",
    "length_of_stay": """
        PIVOT (SELECT geo, origin, avg_stay_nights FROM length_of_stay WHERE NOT is_covid)
        ON origin USING ROUND(MEDIAN(avg_stay_nights), 2) ORDER BY geo""",
    "canton_segment": """
        -- winter_peak > 0.40, balanced 0.30-0.40, summer_or_flat < 0.30 (Dec-Mar share, 2010-2019)
        SELECT geo, ROUND(winter_share, 3) AS winter_share, segment
        FROM canton_segment ORDER BY winter_share DESC""",
}


def load_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Load the processed CSVs as tables and check that no row was lost."""
    tourism = pd.read_csv(PROCESSED / "tourism_long.csv", parse_dates=["date"])
    fx = pd.read_csv(PROCESSED / "fx_long.csv", parse_dates=["date"])
    tourism["date"] = tourism["date"].dt.date      # DATE, not TIMESTAMP, in DuckDB
    fx["date"] = fx["date"].dt.date
    con.execute("CREATE OR REPLACE TABLE tourism AS SELECT * FROM tourism")
    con.execute("CREATE OR REPLACE TABLE fx AS SELECT * FROM fx")

    for name, df in [("tourism", tourism), ("fx", fx)]:
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert n == len(df), f"{name}: {n} rows in DuckDB vs {len(df)} in CSV"


def create_views(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Run sql/*.sql in numbered order (later views build on earlier ones)."""
    files = sorted(SQL.glob("[0-9][0-9]_*.sql"))
    assert files, "no SQL view files found in sql/"
    for path in files:
        con.execute(path.read_text())
    return [p.stem[3:] for p in files]      # "01_monthly_nights" -> "monthly_nights"


def scalar(con: duckdb.DuckDBPyConnection, query: str):
    return con.execute(query).fetchone()[0]


def quality_checks(con: duckdb.DuckDBPyConnection) -> None:
    """Fail loudly if a table or view contains impossible values."""
    negatives = {
        "tourism.value": "SELECT COUNT(*) FROM tourism WHERE value < 0",
        "fx.chf_per_unit": "SELECT COUNT(*) FROM fx WHERE chf_per_unit <= 0",
        "monthly_nights.nights": "SELECT COUNT(*) FROM monthly_nights WHERE nights < 0",
        "market_share.share_of_tracked_pct":
            "SELECT COUNT(*) FROM market_share WHERE share_of_tracked_pct < 0",
        "seasonal_profile.avg_share_pct":
            "SELECT COUNT(*) FROM seasonal_profile WHERE avg_share_pct < 0",
        "length_of_stay.arrivals": "SELECT COUNT(*) FROM length_of_stay WHERE arrivals < 0",
        "canton_segment.winter_share":
            "SELECT COUNT(*) FROM canton_segment WHERE winter_share NOT BETWEEN 0 AND 1",
    }
    for col, query in negatives.items():
        assert scalar(con, query) == 0, f"negative or out-of-range values in {col}"

    # Shares must add up to 100% per geo-year (market share) and per geo (seasonal profile)
    off = scalar(con, f"""
        SELECT COUNT(*) FROM (
            SELECT SUM(share_of_tracked_pct) AS s FROM market_share GROUP BY level, geo, year)
        WHERE abs(s - 100) > {TOL}""")
    assert off == 0, f"market_share: {off} geo-years do not sum to 100%"
    off = scalar(con, f"""
        SELECT COUNT(*) FROM (
            SELECT SUM(avg_share_pct) AS s, COUNT(*) AS n
            FROM seasonal_profile GROUP BY level, geo)
        WHERE abs(s - 100) > {TOL} OR n <> 12""")
    assert off == 0, f"seasonal_profile: {off} geos do not sum to 100% over 12 months"

    # Every arriving guest stays at least one night
    assert scalar(con, "SELECT COUNT(*) FROM length_of_stay WHERE avg_stay_nights < 1") == 0, \
        "length_of_stay: average stay below 1 night"

    # Each canton gets exactly one segment
    n_cantons = scalar(con, "SELECT COUNT(DISTINCT geo) FROM tourism WHERE level = 'canton'")
    assert scalar(con, "SELECT COUNT(*) FROM canton_segment") == n_cantons, \
        "canton_segment: not one row per canton"
    bad = scalar(con, """SELECT COUNT(*) FROM canton_segment
                         WHERE segment NOT IN ('winter_peak', 'balanced', 'summer_or_flat')""")
    assert bad == 0, "canton_segment: unexpected segment label"

    print("OK - no negative values, shares sum to 100%, stays >= 1 night, one segment per canton")


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    load_tables(con)
    views = create_views(con)
    quality_checks(con)

    print(f"\n{DB_PATH.relative_to(ROOT)}")
    for name in ["tourism", "fx", *views]:
        print(f"  {name:<18} {scalar(con, f'SELECT COUNT(*) FROM {name}'):>8,} rows")

    for name in views:
        print(f"\n=== {name} ===")
        print(con.sql(SUMMARIES[name]))
    con.close()
