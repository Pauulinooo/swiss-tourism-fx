"""
Export dashboard tables to BigQuery (dataset swiss_tourism_fx, europe-west6) for Looker Studio.

Tables (replaced on every run):
  nights_monthly      actual monthly nights per series (57 series)
  forecasts_backtest  backtest forecasts with actuals: post-covid and 2015-16 windows
  metrics             absolute-error and actual sums by window, model, horizon, market, peak season
  fx_scenarios        next 6 months from the latest origin, with the franc moved -10%..+10% now

Uses the bq CLI and the gcloud login of the machine: no credentials in code or repo.
Safety: every bq command is checked to target only PROJECT:DATASET; nothing is ever deleted.

Usage:  python src/export_bq.py --dry-run     # build and check the CSVs only
        python src/export_bq.py               # build, check and upload
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast as fc
import run_experiments as rx
from charts import connect
from features import COVID_END, COVID_START

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "bq"
PROJECT = "swiss-tourism-fx-2026"
DATASET = "swiss_tourism_fx"
LOCATION = "europe-west6"
DS_REF = f"{PROJECT}:{DATASET}"

RESORT_CANTON = {"St. Moritz": "Graubünden", "Scuol": "Graubünden", "Klosters": "Graubünden",
                 "Tujetsch": "Graubünden", "Zermatt": "Valais", "Saas-Grund": "Valais",
                 "Saanen": "Bern", "Lenk": "Bern"}
BACKTEST_WINDOWS = ["post_covid", "shock_2015"]
FORECAST_COLS = ["naive", "gb_no_fx", "gb_fx", "combo_no_fx", "combo_fx"]
SCENARIO_ORIGIN = pd.Timestamp("2026-07-01")      # last month with nights for all 57 series
SCENARIO_STEPS = list(range(-10, 11, 2))           # % change in CHF per unit of foreign currency
SCENARIO_TYPES = {"EUR only": {"EUR"}, "All currencies": {"EUR", "GBP", "USD", "CNY"}}

SCENARIO_NOTE = ("A scenario means: if the franc moves X% now. fx_change_pct is the change in CHF per unit of "
                 "foreign currency at the forecast origin (Jul 2026) vs its actual value; negative = stronger "
                 "franc. The model with FX re-forecasts the next 6 months with that FX value. Swiss guests have "
                 "no FX feature, so their forecast does not change. Associations learned from history, not causal "
                 "effects.")

# --- Schemas: (name, type, description) ------------------------------------
SERIES_COLS = [
    ("series_id", "STRING", "Canton | origin market, or resort name (resort)"),
    ("level", "STRING", "canton (canton x origin market) or resort (total of 7 markets in one resort)"),
    ("geo", "STRING", "Canton or resort name"),
    ("canton", "STRING", "Canton (for resorts: the canton the resort is in)"),
    ("origin", "STRING", "Origin market of the guests; Total for resort series"),
    ("market", "STRING", "Origin market, or 'Resort totals' for resort series"),
    ("segment", "STRING", "Canton seasonality segment: winter_peak / balanced / summer_or_flat"),
    ("resort_type", "STRING", "luxury or mid-range (resort series only)"),
]
SCHEMAS = {
    "nights_monthly": [("date", "DATE", "Month (first day)"), *SERIES_COLS,
                       ("nights", "FLOAT64", "Hotel overnight stays (BFS HESTA)"),
                       ("is_covid", "BOOL", "Mar 2020 - Dec 2021"),
                       ("partial", "BOOL", "Resort total with at least one suppressed market (counted as 0)")],
    "forecasts_backtest": [
        ("window", "STRING", "post_covid (targets Jan 2023 - Jul 2026, 57 series) or shock_2015 "
                             "(Jan 2015 - Dec 2016, 49 canton x origin series)"),
        ("h", "INT64", "Horizon: months between forecast origin and target month"),
        ("origin_date", "DATE", "Forecast origin (last month of data used)"),
        ("target_date", "DATE", "Month forecast"), *SERIES_COLS,
        ("peak_season", "BOOL", "Target month is one of the series' 3 highest months"),
        ("actual", "FLOAT64", "Actual nights"),
        ("naive", "FLOAT64", "Seasonal naive: same month last year"),
        ("gb_no_fx", "FLOAT64", "Gradient boosting without FX"),
        ("gb_fx", "FLOAT64", "Gradient boosting with FX (YoY change of the market's currency at the origin)"),
        ("combo_no_fx", "FLOAT64", "(naive + model without FX) / 2"),
        ("combo_fx", "FLOAT64", "(naive + model with FX) / 2")],
    "metrics": [
        ("window", "STRING", "post_covid or shock_2015"),
        ("model", "STRING", "naive / gb_no_fx / gb_fx / combo_no_fx / combo_fx"),
        ("model_label", "STRING", "Readable model name"),
        ("h", "INT64", "Horizon (months ahead)"),
        ("market", "STRING", "Origin market, or Resort totals"),
        ("peak_season", "BOOL", "Rows for peak-season target months (TRUE) or the other months (FALSE)"),
        ("sum_abs_error", "FLOAT64", "Sum of |actual - forecast|. WAPE = SUM(sum_abs_error) / SUM(sum_actual)"),
        ("sum_actual", "FLOAT64", "Sum of actual nights"),
        ("wape", "FLOAT64", "WAPE % of this row only; do not average it, re-aggregate the sums"),
        ("n", "INT64", "Number of forecasts")],
    "fx_scenarios": [
        ("scenario_type", "STRING", "EUR only, or All currencies (EUR, GBP, USD, CNY moved together)"),
        ("fx_change_pct", "INT64", "If the franc moves X% now: change in CHF per unit of foreign currency at "
                                   "the origin; negative = stronger franc"),
        ("scenario_label", "STRING", "Readable scenario name"),
        ("origin_date", "DATE", "Forecast origin (Jul 2026)"),
        ("h", "INT64", "Horizon (months ahead)"),
        ("target_date", "DATE", "Month forecast"), *SERIES_COLS,
        ("fx_feature", "STRING", "Currency of the series' FX feature, or none (Swiss guests)"),
        ("fx_sensitive", "BOOL", "FALSE if the scenario does not touch this series' FX feature "
                                 "(Swiss guests always; non-EUR markets in EUR only)"),
        ("naive", "FLOAT64", "Seasonal naive: same month last year (does not depend on the scenario)"),
        ("gb_fx_scenario", "FLOAT64", "Model with FX under the scenario"),
        ("combo_fx_scenario", "FLOAT64", "(naive + model with FX under the scenario) / 2"),
        ("gb_fx_central", "FLOAT64", "Model with FX at the actual FX value (0% scenario)")],
}
DESCRIPTIONS = {
    "nights_monthly": "Monthly hotel overnight stays per series (49 canton x origin + 8 resort totals). Source: BFS HESTA.",
    "forecasts_backtest": "Rolling-origin backtest forecasts with actuals, by series, horizon and target month "
                          "(notebooks 03-04).",
    "metrics": "Error sums for WAPE by window, model, horizon, market and peak season. "
               "WAPE = SUM(sum_abs_error) / SUM(sum_actual).",
    "fx_scenarios": SCENARIO_NOTE,
}


# --- Build tables ----------------------------------------------------------
def add_series_cols(df: pd.DataFrame, segments: pd.Series) -> pd.DataFrame:
    """Canton, market and segment columns shared by all tables."""
    df = df.copy()
    is_resort = df["level"] == "resort"
    df["canton"] = np.where(is_resort, df["geo"].map(RESORT_CANTON), df["geo"])
    df["market"] = np.where(is_resort, "Resort totals", df["origin"])
    df["segment"] = df["canton"].map(segments)
    assert df["canton"].notna().all() and df["segment"].notna().all(), "unmapped canton or segment"
    return df


def build_nights(panel, segments) -> pd.DataFrame:
    df = add_series_cols(panel, segments)
    df["is_covid"] = df["date"].between(COVID_START, COVID_END)
    assert len(df) == len(panel) and df["series_id"].nunique() == 57
    return df


def build_backtest(panel, segments) -> pd.DataFrame:
    meta = json.loads((rx.OUT / "fingerprint.json").read_text())
    assert meta["fingerprint"] == rx.fingerprint(), "experiment cache is stale: run python src/run_experiments.py"
    parts = []
    for w in BACKTEST_WINDOWS:
        b = fc.add_combinations(pd.read_csv(rx.OUT / f"base_{w}.csv", parse_dates=["target_date", "origin_date"]))
        wp = rx.window_panel(panel, w)
        peak = fc.peak_months(wp, years=tuple(rx.WINDOWS[w]["peak_years"]))
        b["month"] = b["target_date"].dt.month
        b = b.merge(peak, on=["series_id", "month"], how="left")
        b["peak_season"] = b["peak"].fillna(False).astype(bool)
        assert len(b) == wp["series_id"].nunique() * len(rx.targets(w)) * 6
        parts.append(b.assign(window=w))
    df = add_series_cols(pd.concat(parts, ignore_index=True), segments)
    assert df[["actual", *FORECAST_COLS]].notna().all().all()
    return df


def build_metrics(bt: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in FORECAST_COLS:
        g = bt.assign(abs_err=(bt["actual"] - bt[col]).abs()).groupby(
            ["window", "h", "market", "peak_season"], as_index=False).agg(
            sum_abs_error=("abs_err", "sum"), sum_actual=("actual", "sum"), n=("actual", "size"))
        rows.append(g.assign(model=col, model_label={**fc.MODELS, **fc.COMBOS}[col]))
    m = pd.concat(rows, ignore_index=True)
    m["wape"] = 100 * m["sum_abs_error"] / m["sum_actual"]
    # The sums must reproduce the notebooks' overall WAPE (post-covid 8.74 / 8.33 / 8.17)
    pc = m[m["window"] == "post_covid"].groupby("model")[["sum_abs_error", "sum_actual"]].sum()
    w = (100 * pc["sum_abs_error"] / pc["sum_actual"]).round(2)
    assert (w["naive"], w["gb_no_fx"], w["gb_fx"]) == (8.74, 8.33, 8.17), w
    assert m.groupby("model")["n"].sum().eq(len(bt)).all()
    return m


def build_scenarios(panel, fx_yoy, segments) -> pd.DataFrame:
    """Train the model with FX on all data up to the origin (one model per horizon), then
    re-forecast with the FX feature at the origin moved by log(1 + X%)."""
    out = []
    for h in fc.HORIZONS:
        feats = fc.build_features(panel, fx_yoy, h)
        cols = fc.feature_list(use_fx=True)
        train = feats[(feats["target_date"] <= SCENARIO_ORIGIN) & feats["target"].notna()]
        test = feats[(feats["origin_date"] == SCENARIO_ORIGIN) & feats["y_base"].notna()].copy()
        assert train["origin_date"].max() < SCENARIO_ORIGIN and len(test) == 57
        model = fc.make_model().fit(train[cols], train["target"])
        central = np.clip(np.expm1(test["y_base"] + model.predict(test[cols])), 0, None)
        for stype, currencies in SCENARIO_TYPES.items():
            hit = test["currency"].isin(currencies).to_numpy()
            for pct in SCENARIO_STEPS:
                x = test[cols].copy()
                x.loc[hit, fc.FX_FEATURE] = x.loc[hit, fc.FX_FEATURE] + np.log1p(pct / 100)
                pred = np.clip(np.expm1(test["y_base"] + model.predict(x)), 0, None)
                out.append(test[["series_id", "level", "geo", "origin", "resort_type", "h", "origin_date",
                                 "target_date", "base_nights", "currency"]]
                           .assign(scenario_type=stype, fx_change_pct=pct, fx_sensitive=hit,
                                   gb_fx_scenario=pred.to_numpy(), gb_fx_central=central.to_numpy()))
    df = pd.concat(out, ignore_index=True).rename(columns={"base_nights": "naive"})
    df["fx_feature"] = df["currency"].fillna("none")
    df["combo_fx_scenario"] = (df["naive"] + df["gb_fx_scenario"]) / 2
    direction = np.select([df["fx_change_pct"] < 0, df["fx_change_pct"] > 0],
                          ["stronger franc", "weaker franc"], "actual rate")
    cur = np.where(df["scenario_type"] == "EUR only", "EUR/CHF", "All currencies vs CHF")
    df["scenario_label"] = [f"{c} {p:+d}% now ({d})" if p else f"{c} unchanged ({d})"
                            for c, p, d in zip(cur, df["fx_change_pct"], direction)]
    df = add_series_cols(df, segments)

    n = 57 * len(fc.HORIZONS) * len(SCENARIO_STEPS) * len(SCENARIO_TYPES)
    assert len(df) == n and df[["naive", "gb_fx_scenario"]].notna().all().all()
    zero = df[df["fx_change_pct"] == 0]
    assert np.allclose(zero["gb_fx_scenario"], zero["gb_fx_central"]), "0% scenario must equal the central forecast"
    flat = df[~df["fx_sensitive"]]
    assert np.allclose(flat["gb_fx_scenario"], flat["gb_fx_central"]), "untouched series must not move"
    assert not df.loc[df["origin"] == "Switzerland", "fx_sensitive"].any()
    return df


def monotonicity(sc: pd.DataFrame) -> pd.DataFrame:
    """Total 6-month nights by scenario type x market across the FX steps."""
    t = sc.groupby(["scenario_type", "market", "fx_change_pct"])["gb_fx_scenario"].sum().unstack()
    d = np.sign(np.diff(t.to_numpy(), axis=1).round(6))
    shape = np.select([(d == 0).all(1), (d >= 0).all(1), (d <= 0).all(1)],
                      ["flat (not FX-sensitive)", "monotonic: rises as the franc weakens",
                       "monotonic: falls as the franc weakens"], "non-monotonic")
    res = pd.DataFrame({"pct_at_-10": 100 * (t[-10] / t[0] - 1), "pct_at_+10": 100 * (t[10] / t[0] - 1),
                        "n_flat_steps": (d == 0).sum(1), "shape": shape}, index=t.index)
    return res


# --- Upload ----------------------------------------------------------------
def bq(*args: str, target: str, extra: tuple[str, ...] = ()) -> str:
    """Run a bq command; refuse anything that does not target our dataset."""
    assert target == DS_REF or target.startswith(DS_REF + "."), f"refusing to touch {target}"
    assert args[0] in {"show", "mk", "load", "update"}, f"bq {args[0]} is not allowed"
    cmd = ["bq", f"--project_id={PROJECT}", f"--location={LOCATION}", *args, target, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} ... failed:\n{r.stderr or r.stdout}")
    return r.stdout


def ensure_dataset() -> None:
    try:
        info = json.loads(bq("show", "--format=json", target=DS_REF))
        assert info["location"] == LOCATION, f"dataset exists in {info['location']}, expected {LOCATION}"
        print(f"dataset {DS_REF} exists ({LOCATION})")
    except RuntimeError as err:
        if "Not found" not in str(err):
            raise
        bq("mk", "--dataset", "--description=Swiss hotel nights, forecasts and FX scenarios (dashboard)",
           target=DS_REF)
        print(f"created dataset {DS_REF} in {LOCATION}")


def upload(name: str, csv: Path, schema: Path, n_rows: int) -> None:
    ref = f"{DS_REF}.{name}"
    bq("load", "--replace", "--source_format=CSV", "--skip_leading_rows=1", target=ref,
       extra=(str(csv), str(schema)))
    bq("update", f"--description={DESCRIPTIONS[name]}", target=ref)
    info = json.loads(bq("show", "--format=json", target=ref))
    assert int(info["numRows"]) == n_rows, f"{name}: {info['numRows']} rows in BigQuery, {n_rows} local"
    print(f"loaded {ref}: {int(info['numRows']):,} rows")


def write_table(name: str, df: pd.DataFrame) -> tuple[Path, Path]:
    cols = [c for c, _, _ in SCHEMAS[name]]
    df = df[cols].copy()
    for c, t, _ in SCHEMAS[name]:
        if t == "DATE":
            df[c] = pd.to_datetime(df[c]).dt.strftime("%Y-%m-%d")
        elif t == "BOOL":
            df[c] = df[c].astype(bool)
    assert df.columns.is_unique
    csv, schema = OUT / f"{name}.csv", OUT / f"{name}.schema.json"
    df.to_csv(csv, index=False)
    schema.write_text(json.dumps([{"name": c, "type": t, "description": d} for c, t, d in SCHEMAS[name]], indent=1))
    return csv, schema


def main(dry_run: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect()
    panel, fx_yoy = fc.load_panel(con), fc.load_fx_yoy(con)
    segments = con.sql("SELECT geo, segment FROM canton_segment").df().set_index("geo")["segment"]
    con.close()

    bt = build_backtest(panel, segments)
    sc = build_scenarios(panel, fx_yoy, segments)
    tables = {"nights_monthly": build_nights(panel, segments), "forecasts_backtest": bt,
              "metrics": build_metrics(bt), "fx_scenarios": sc}

    print("\nRow counts:")
    files = {}
    for name, df in tables.items():
        files[name] = write_table(name, df)
        print(f"  {name:<20} {len(df):>7,} rows  -> {files[name][0].relative_to(ROOT)}")

    pd.set_option("display.width", 140)
    print("\nScenario check: total nights over the next 6 months, % vs the 0% scenario")
    print(monotonicity(sc).round(2).to_string())
    hist = fx_yoy[fx_yoy["date"] < SCENARIO_ORIGIN].groupby("currency")["fx_yoy"].agg(["min", "max"]) * 100
    now = fx_yoy[fx_yoy["date"] == SCENARIO_ORIGIN].set_index("currency")["fx_yoy"] * 100
    print("\nFX feature (YoY %): historical range in training vs value at the origin and after -10% / +10%")
    print(hist.assign(at_origin=now, at_minus10=now + 100 * np.log(0.9), at_plus10=now + 100 * np.log(1.1))
          .round(1).to_string())

    if dry_run:
        print("\n--dry-run: nothing sent to BigQuery")
        return
    ensure_dataset()
    for name, (csv, schema) in files.items():
        upload(name, csv, schema, len(tables[name]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build and check the CSVs, upload nothing")
    main(ap.parse_args().dry_run)
