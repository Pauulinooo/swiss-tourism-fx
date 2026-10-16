"""
Loaders for the raw BFS (HESTA) tourism tables and SNB exchange rates.

Every loader returns a tidy (long) DataFrame:
    one row = one date x one geography x one origin market x one indicator.

Raw files in data/raw/ are never modified. Run this module directly to
build the processed files in data/processed/ and run the quality checks.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

# BFS writes July as "Juli" (German) in the commune table -> explicit mapping
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
MONTHS["Juli"] = 7

# Out of scope: no exchange-rate series (India) or series too short / too small (UAE)
EXCLUDED_ORIGINS = ["India", "United Arab Emirates"]

# Origin market -> currency that drives its price of a Swiss holiday
CURRENCY = {
    "Switzerland": "CHF",
    "Germany": "EUR", "France": "EUR", "Italy": "EUR",
    "United Kingdom": "GBP",
    "United States": "USD",
    "China": "CNY",
}


def _read_hesta(path: Path, geo_col: str) -> pd.DataFrame:
    """Read a BFS PxWeb export (semicolon, cp1252, '...' = not available) into long format."""
    df = pd.read_csv(path, sep=";", encoding="cp1252", na_values=["...", "…"])

    # Annual totals are mixed with monthly rows: drop them to avoid double counting
    df = df[df["Month"] != "Total of the year"].copy()
    df["date"] = pd.to_datetime(dict(year=df["Year"], month=df["Month"].map(MONTHS), day=1))

    long = df.drop(columns=["Year", "Month"]).melt(
        id_vars=["date", geo_col], var_name="series", value_name="value")

    # Column names look like "Germany Overnight stays" / "Germany Arrivals"
    pattern = r"^(?P<origin>.+?) (?P<indicator>Overnight stays|Arrivals)$"
    long = long.join(long["series"].str.extract(pattern)).drop(columns="series")
    long["indicator"] = long["indicator"].map({"Overnight stays": "nights", "Arrivals": "arrivals"})

    long = long[~long["origin"].isin(EXCLUDED_ORIGINS)]
    long = long.rename(columns={geo_col: "geo"})
    return long.dropna(subset=["value"])          # drops future months and suppressed cells


def load_canton() -> pd.DataFrame:
    df = _read_hesta(RAW / "bfs_hesta_canton_monthly_2005_2026.csv", "Canton")
    df["level"] = "canton"
    return df


def load_commune() -> pd.DataFrame:
    df = _read_hesta(RAW / "bfs_hesta_commune_monthly_2013_2026.csv", "Commune")
    df["level"] = "commune"
    return df


def load_fx() -> pd.DataFrame:
    """SNB monthly rates, expressed as CHF per 1 unit of foreign currency.

    Higher value = weaker franc. A FALL in the series = franc appreciation.
    """
    fx = pd.read_csv(RAW / "snb_fx_monthly_2005_2026.csv", sep=";", skiprows=3)
    fx["currency"] = fx["D1"].str.extract(r"^([A-Z]{3})")
    fx["units"] = fx["D1"].str.extract(r"(\d+)$").astype(int)
    fx["chf_per_unit"] = fx["Value"] / fx["units"]          # CNY is quoted per 100
    fx["date"] = pd.to_datetime(fx["Date"], format="%Y-%m")
    return fx[["date", "currency", "chf_per_unit"]].sort_values(["currency", "date"])


def quality_checks(canton_raw: Path, commune_raw: Path) -> None:
    """Monthly rows must add up to the published annual totals (except suppressed months)."""
    for path, geo in [(canton_raw, "Canton"), (commune_raw, "Commune")]:
        raw = pd.read_csv(path, sep=";", encoding="cp1252", na_values=["...", "…"])
        cols = [c for c in raw.columns if c.endswith(("Overnight stays", "Arrivals"))]
        monthly = raw[raw["Month"] != "Total of the year"]
        complete = monthly.groupby(["Year", geo])[cols].apply(lambda d: d.notna().all())
        sums = monthly.groupby(["Year", geo])[cols].sum(min_count=1)
        annual = raw[raw["Month"] == "Total of the year"].set_index(["Year", geo])[cols]
        diff = (sums - annual).where(complete).abs().max().max()
        assert diff == 0, f"{path.name}: monthly rows do not add up to annual totals"
    print("OK - monthly data adds up to annual totals wherever no month is suppressed")


if __name__ == "__main__":
    PROCESSED.mkdir(parents=True, exist_ok=True)
    quality_checks(RAW / "bfs_hesta_canton_monthly_2005_2026.csv",
                   RAW / "bfs_hesta_commune_monthly_2013_2026.csv")

    tourism = pd.concat([load_canton(), load_commune()], ignore_index=True)
    tourism["currency"] = tourism["origin"].map(CURRENCY)
    tourism.to_csv(PROCESSED / "tourism_long.csv", index=False)

    fx = load_fx()
    fx.to_csv(PROCESSED / "fx_long.csv", index=False)

    print(f"tourism_long.csv: {len(tourism):,} rows | "
          f"{tourism['date'].min():%Y-%m} -> {tourism['date'].max():%Y-%m}")
    print(f"fx_long.csv: {len(fx):,} rows | currencies: {sorted(fx['currency'].unique())}")
