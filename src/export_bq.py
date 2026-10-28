"""
Export dashboard tables to BigQuery (dataset swiss_tourism_fx, europe-west6) for Looker Studio.

Tables (replaced on every run):
  nights_monthly      actual monthly nights per series (57 series)
  forecasts_backtest  backtest forecasts with actuals: post-covid (h = 1-12) and 2015-16 (h = 1-6)
  metrics             absolute-error and actual sums by window, model, horizon, market, peak season
  fx_scenarios        next 12 months from the latest origin, franc moved -10%..+10% now, 80% intervals
  outlook             next 12 months and winter 2026/27 from the Jul 2026 origin, 80% intervals (low confidence)
  interval_coverage   out-of-sample coverage of the 80% intervals by horizon x market
  canton_vulnerability  expected % change in each canton's nights for a 10% stronger franc (notebook 06, A)
  resort_pairs        German vs Swiss nights after the 2015 shock, 8 resorts in 4 luxury/mid-range pairs (notebook 06, B)

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
import long_horizon as lh
import original_questions as oq
import outlook as ol
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
SCENARIO_ORIGIN = lh.OUTLOOK_ORIGIN               # last month with nights for all 57 series
SCENARIO_STEPS = list(range(-10, 11, 2))           # % change in CHF per unit of foreign currency
SCENARIO_TYPES = {"EUR only": {"EUR"}, "All currencies": {"EUR", "GBP", "USD", "CNY"}}

SCENARIO_NOTE = ("A scenario means: if the franc moves X% now. fx_change_pct is the change in CHF per unit of "
                 "foreign currency at the forecast origin (Jul 2026) vs its actual value; negative = stronger "
                 "franc. The model with FX re-forecasts the next 12 months with that FX value; lower_80/upper_80 are 80% intervals from past forecast errors (fitted on Jan 2024 - Jul 2026, 2023 rebound left out), not FX uncertainty. Swiss guests have "
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
        ("gb_fx_central", "FLOAT64", "Model with FX at the actual FX value (0% scenario)"),
        *[(f"{p}{b}_80", "FLOAT64", f"{'Lower' if b == 'lower' else 'Upper'} bound of the 80% interval of the "
           f"{'combination' if p else 'model with FX'} (past forecast errors per horizon x market)")
          for p in ["", "combo_"] for b in ["lower", "upper"]]],
    "outlook": [
        ("origin_date", "DATE", "Forecast origin (Jul 2026, last month with data for all series)"),
        ("h", "INT64", "Horizon (months ahead)"),
        ("target_date", "DATE", "Month forecast (Aug 2026 - Jul 2027)"), *SERIES_COLS,
        ("in_winter", "BOOL", "Target month in winter 2026/27 (Dec 2026 - Mar 2027)"),
        ("naive", "FLOAT64", "Seasonal naive: same month last year"),
        ("gb_fx", "FLOAT64", "Model with FX"),
        ("combo_fx", "FLOAT64", "Headline forecast: (naive + model with FX) / 2"),
        *[(f"{p}{b}_80", "FLOAT64", f"{'Lower' if b == 'lower' else 'Upper'} bound of the 80% interval of the "
           f"{'combination' if p else 'model with FX'}; summing bounds over months gives a wide, conservative total")
          for p in ["", "combo_"] for b in ["lower", "upper"]],
        ("confidence", "STRING", "low: 12-month outlook validated on one post-covid period")],
    "interval_coverage": [
        ("h", "INT64", "Horizon (months ahead)"),
        ("market", "STRING", "Origin market, or Resort totals"),
        ("model", "STRING", "gb_fx or combo_fx"),
        ("model_label", "STRING", "Readable model name"),
        ("rule", "STRING", "check_preset (pre-set rule) or check_2024 (rule used for the outlook, set after the results)"),
        ("rule_label", "STRING", "Months the interval was fitted on; filter on one rule before aggregating"),
        ("n_inside", "INT64", "Actual months inside the 80% interval (Jan 2025 - Jul 2026)"),
        ("n", "INT64", "Forecasts checked. Coverage = SUM(n_inside) / SUM(n)"),
        ("coverage_pct", "FLOAT64", "Coverage % of this row only; re-aggregate the counts")],
    "canton_vulnerability": [
        ("rank", "INT64", "1 = largest expected fall in nights"),
        ("canton", "STRING", "Canton"),
        ("segment", "STRING", "Canton seasonality segment"),
        ("exposure_pct", "FLOAT64", "Euro-market (DE, FR, IT) share of the canton's nights 2016-2019, % (7 tracked markets)"),
        ("beta", "FLOAT64", "YoY euro nights on YoY EUR/CHF at lag 6 (notebook 02 design, covid excluded)"),
        ("beta_lo", "FLOAT64", "Lower bound of beta's 95% CI (Newey-West)"),
        ("beta_hi", "FLOAT64", "Upper bound of beta's 95% CI"),
        ("p_value", "FLOAT64", "p-value of beta"),
        ("n_months", "INT64", "Months in the regression"),
        ("vulnerability_pct", "FLOAT64", "Expected % change in the canton's nights for a 10% stronger franc = exposure x (0.9^beta - 1)"),
        ("vulnerability_lo", "FLOAT64", "95% interval, most negative end"),
        ("vulnerability_hi", "FLOAT64", "95% interval, least negative end"),
        ("scenario_pct", "FLOAT64", "Cross-check: fx_scenarios, EUR only -10%, canton's 12-month nights vs the 0% scenario (model with FX)"),
        ("scenario_rank", "INT64", "Rank of scenario_pct (1 = largest fall)")],
    "resort_pairs": [
        ("pair", "STRING", "Luxury - mid-range pair"),
        ("resort", "STRING", "Commune"),
        ("resort_type", "STRING", "luxury or mid-range"),
        ("canton", "STRING", "Canton of the resort"),
        ("de_nights_post", "FLOAT64", "German nights Jul 2015 - Dec 2016"),
        ("de_nights_base", "FLOAT64", "German nights in the same calendar months of 2014"),
        ("ch_nights_post", "FLOAT64", "Swiss nights Jul 2015 - Dec 2016"),
        ("ch_nights_base", "FLOAT64", "Swiss nights in the same calendar months of 2014"),
        ("de_index", "FLOAT64", "German index: post / base x 100"),
        ("ch_index", "FLOAT64", "Swiss index: post / base x 100"),
        ("gap", "FLOAT64", "German index minus Swiss index (points); below 0 = German guests fell more"),
        ("gap_2014_vs_2013", "FLOAT64", "Same gap for 2014 vs 2013 (before the shock, context only)"),
        ("comparable", "BOOL", "FALSE for the St. Moritz - Scuol pair: Scuol merged with five villages on 1 Jan 2015"),
        ("luxury_fell_more", "BOOL", "Pair-level: the luxury resort's gap is below the mid-range resort's")],
}
DESCRIPTIONS = {
    "nights_monthly": "Monthly hotel overnight stays per series (49 canton x origin + 8 resort totals). Source: BFS HESTA.",
    "forecasts_backtest": "Rolling-origin backtest forecasts with actuals, by series, horizon and target month "
                          "(notebooks 03-04).",
    "metrics": "Error sums for WAPE by window, model, horizon, market and peak season. "
               "WAPE = SUM(sum_abs_error) / SUM(sum_actual).",
    "fx_scenarios": SCENARIO_NOTE,
    "outlook": "Low-confidence outlook from the Jul 2026 origin: next 12 months and winter 2026/27, with 80% "
               "intervals from past forecast errors (fitted on Jan 2024 - Jul 2026; the 2023 post-covid rebound is left out, "
               "a choice made after seeing the results). Not a calendar-2027 forecast.",
    "interval_coverage": "Out-of-sample check of the 80% intervals on Jan 2025 - Jul 2026, fitted on 2023-2024 "
                         "(pre-set rule) or on 2024 only (2024+ rule). Coverage = SUM(n_inside) / SUM(n) within one rule.",
    "canton_vulnerability": "Notebook 06, A: expected change in each canton's nights for a 10% stronger franc "
                            "(exposure x sensitivity, 95% CI), with the fx_scenarios cross-check. Associations, not causal effects.",
    "resort_pairs": "Notebook 06, B: German vs Swiss nights in Jul 2015 - Dec 2016 vs the same months of 2014, "
                    "8 resorts in 4 luxury/mid-range pairs. 4-case study, not a statistical test; St. Moritz - Scuol "
                    "is not comparable (Scuol merger, 1 Jan 2015).",
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
    """Post-covid h = 1-12 (notebook 05 caches) and the 2015-16 shock h = 1-6 (Sprint 3B cache)."""
    post = ol.load_backtest(panel).rename(columns={"peak": "peak_season"}).assign(window="post_covid")
    meta = json.loads((rx.OUT / "fingerprint.json").read_text())
    assert meta["fingerprint"] == rx.fingerprint(), "experiment cache is stale: run python src/run_experiments.py"
    b = fc.add_combinations(pd.read_csv(rx.OUT / "base_shock_2015.csv", parse_dates=["target_date", "origin_date"]))
    wp = rx.window_panel(panel, "shock_2015")
    b["month"] = b["target_date"].dt.month
    b = b.merge(fc.peak_months(wp, years=tuple(rx.WINDOWS["shock_2015"]["peak_years"])),
                on=["series_id", "month"], how="left")
    b["peak_season"] = b["peak"].fillna(False).astype(bool)
    assert len(b) == 49 * len(rx.targets("shock_2015")) * 6
    df = add_series_cols(pd.concat([post, b.assign(window="shock_2015")], ignore_index=True), segments)
    assert len(df) == 57 * 43 * 12 + 49 * 24 * 6
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
    pc = m[(m["window"] == "post_covid") & (m["h"] <= 6)].groupby("model")[["sum_abs_error", "sum_actual"]].sum()
    w = (100 * pc["sum_abs_error"] / pc["sum_actual"]).round(2)
    assert (w["naive"], w["gb_no_fx"], w["gb_fx"]) == (8.74, 8.33, 8.17), w
    assert m.groupby("model")["n"].sum().eq(len(bt)).all()
    return m


def build_scenarios(models: dict, q: dict, segments) -> pd.DataFrame:
    """Re-forecast the next 12 months with the FX feature at the origin moved by log(1 + X%).

    `models` = long_horizon.forecast_from_origin (model with FX per horizon, trained on all
    targets <= origin); `q` = interval percentiles per horizon x market (outlook.interval_quantiles).
    """
    out = []
    for h, (model, test) in models.items():
        central = lh.predict(model, test)
        for stype, currencies in SCENARIO_TYPES.items():
            hit = test["currency"].isin(currencies).to_numpy()
            for pct in SCENARIO_STEPS:
                pred = lh.predict(model, test, pct / 100, currencies)
                out.append(test[["series_id", "level", "geo", "origin", "resort_type", "h", "origin_date",
                                 "target_date", "base_nights", "currency"]]
                           .assign(scenario_type=stype, fx_change_pct=pct, fx_sensitive=hit,
                                   gb_fx_scenario=pred, gb_fx_central=central))
    df = pd.concat(out, ignore_index=True).rename(columns={"base_nights": "naive"})
    df["fx_feature"] = df["currency"].fillna("none")
    df["combo_fx_scenario"] = (df["naive"] + df["gb_fx_scenario"]) / 2
    direction = np.select([df["fx_change_pct"] < 0, df["fx_change_pct"] > 0],
                          ["stronger franc", "weaker franc"], "actual rate")
    cur = np.where(df["scenario_type"] == "EUR only", "EUR/CHF", "All currencies vs CHF")
    df["scenario_label"] = [f"{c} {p:+d}% now ({d})" if p else f"{c} unchanged ({d})"
                            for c, p, d in zip(cur, df["fx_change_pct"], direction)]
    df = add_series_cols(df, segments)
    df = lh.apply_interval(df, q["gb_fx"], "gb_fx_scenario")
    df = lh.apply_interval(df, q["combo_fx"], "combo_fx_scenario", prefix="combo_")

    n = 57 * len(models) * len(SCENARIO_STEPS) * len(SCENARIO_TYPES)
    assert len(df) == n and df[["naive", "gb_fx_scenario", "lower_80", "upper_80"]].notna().all().all()
    zero = df[df["fx_change_pct"] == 0]
    assert np.allclose(zero["gb_fx_scenario"], zero["gb_fx_central"]), "0% scenario must equal the central forecast"
    flat = df[~df["fx_sensitive"]]
    assert np.allclose(flat["gb_fx_scenario"], flat["gb_fx_central"]), "untouched series must not move"
    assert not df.loc[df["origin"] == "Switzerland", "fx_sensitive"].any()
    assert (df["lower_80"] <= df["gb_fx_scenario"]).all() and (df["gb_fx_scenario"] <= df["upper_80"]).all()
    return df


def monotonicity(sc: pd.DataFrame) -> pd.DataFrame:
    """Total 12-month nights by scenario type x market across the FX steps."""
    t = sc.groupby(["scenario_type", "market", "fx_change_pct"])["gb_fx_scenario"].sum().unstack()
    d = np.sign(np.diff(t.to_numpy(), axis=1).round(6))
    shape = np.select([(d == 0).all(1), (d >= 0).all(1), (d <= 0).all(1)],
                      ["flat (not FX-sensitive)", "monotonic: rises as the franc weakens",
                       "monotonic: falls as the franc weakens"], "non-monotonic")
    res = pd.DataFrame({"pct_at_-10": 100 * (t[-10] / t[0] - 1), "pct_at_+10": 100 * (t[10] / t[0] - 1),
                        "n_flat_steps": (d == 0).sum(1), "shape": shape}, index=t.index)
    return res


def build_vulnerability(con, sc: pd.DataFrame, models: dict, segments) -> pd.DataFrame:
    v = oq.vulnerability(con)
    scen = oq.scenario_by_canton(models)
    # same numbers as the fx_scenarios table (EUR only, -10% vs 0%, canton series, model with FX)
    t = sc[(sc["scenario_type"] == "EUR only") & (sc["level"] == "canton")]
    t = t.groupby(["geo", "fx_change_pct"])["gb_fx_scenario"].sum().unstack()
    assert np.allclose(100 * (t[-10] / t[0] - 1), scen.reindex(t.index)), "cross-check differs from fx_scenarios"
    v = v.merge(scen.rename_axis("canton").reset_index(), on="canton")
    v["scenario_rank"] = v["scenario_pct"].rank(method="min").astype(int)
    v["segment"] = v["canton"].map(segments)
    v["exposure_pct"] = 100 * v["exposure"]
    v = v.rename(columns={"p": "p_value", "N": "n_months", "vuln_pct": "vulnerability_pct",
                          "vuln_lo": "vulnerability_lo", "vuln_hi": "vulnerability_hi"})
    assert len(v) == 7 and v["segment"].notna().all()
    return v[[c for c, _, _ in SCHEMAS["canton_vulnerability"]]]


def build_resort_pairs(con) -> pd.DataFrame:
    idx, pairs = oq.resort_pairs(con)
    w = idx.pivot(index="geo", columns="origin")
    rows = []
    for _, p in pairs.iterrows():
        for resort in [p["luxury"], p["mid_range"]]:
            rows.append({"pair": p["pair"], "resort": resort, "resort_type": fc.RESORTS[resort],
                         "canton": RESORT_CANTON[resort],
                         "de_nights_post": w.loc[resort, ("nights_post", "Germany")],
                         "de_nights_base": w.loc[resort, ("nights_base_2014", "Germany")],
                         "ch_nights_post": w.loc[resort, ("nights_post", "Switzerland")],
                         "ch_nights_base": w.loc[resort, ("nights_base_2014", "Switzerland")],
                         "de_index": w.loc[resort, ("index_post", "Germany")],
                         "ch_index": w.loc[resort, ("index_post", "Switzerland")],
                         "gap_2014_vs_2013": (w.loc[resort, ("index_2014_vs_2013", "Germany")]
                                              - w.loc[resort, ("index_2014_vs_2013", "Switzerland")]),
                         "comparable": p["comparable"], "luxury_fell_more": p["luxury_fell_more"]})
    df = pd.DataFrame(rows)
    df["gap"] = df["de_index"] - df["ch_index"]
    assert len(df) == 8 and df["resort"].is_unique and (~df["comparable"]).sum() == 2
    return df[[c for c, _, _ in SCHEMAS["resort_pairs"]]]


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

    bt = build_backtest(panel, segments)
    post = bt[bt["window"] == "post_covid"].rename(columns={"peak_season": "peak"})
    q = ol.interval_quantiles(post, "forward")    # 2024+ rule, decided after seeing the results (notebook 05)
    models = lh.forecast_from_origin(panel, fx_yoy)
    sc = build_scenarios(models, q, segments)
    outl = add_series_cols(ol.build_outlook(panel, fx_yoy, q, models), segments).assign(confidence="low")
    zero = sc[(sc["fx_change_pct"] == 0) & (sc["scenario_type"] == "EUR only")]
    assert np.allclose(np.sort(zero["gb_fx_scenario"]), np.sort(outl["gb_fx"])), "outlook = 0% scenario"
    tables = {"nights_monthly": build_nights(panel, segments), "forecasts_backtest": bt,
              "metrics": build_metrics(bt), "fx_scenarios": sc, "outlook": outl,
              "interval_coverage": ol.coverage_table(post),
              "canton_vulnerability": build_vulnerability(con, sc, models, segments),
              "resort_pairs": build_resort_pairs(con)}
    con.close()

    print("\nRow counts:")
    files = {}
    for name, df in tables.items():
        files[name] = write_table(name, df)
        print(f"  {name:<20} {len(df):>7,} rows  -> {files[name][0].relative_to(ROOT)}")

    pd.set_option("display.width", 140)
    print("\nScenario check: total nights over the next 12 months, % vs the 0% scenario")
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
