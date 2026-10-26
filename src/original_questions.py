"""
Sprint 5: the project's original questions (notebook 06), with the rules fixed before the results.

A. Which cantons are most vulnerable to the franc (exposure x sensitivity)?
B. Did luxury resorts lose more German nights than their mid-range neighbours after the 2015 shock?
C. What is the model's accuracy gain worth in seasonal staff (under an explicit assumption)?
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import forecast as fc
import fx_effect as fe
import long_horizon as lh
from features import yoy_log_change

EURO_MARKETS = ["Germany", "France", "Italy"]
EXPOSURE_YEARS = (2016, 2019)
FX_LAG = 6                                   # notebook 02: BIC keeps lag h only; lag 6 = h = 6
FRANC_MOVE = -0.10                           # 10% stronger franc: CHF per EUR falls 10%
PAIRS = [("St. Moritz", "Scuol"), ("Klosters", "Tujetsch"), ("Zermatt", "Saas-Grund"), ("Saanen", "Lenk")]
POST = pd.date_range("2015-07-01", "2016-12-01", freq="MS")        # after the 15 Jan 2015 shock
PRE_CONTEXT = pd.date_range("2014-01-01", "2014-12-01", freq="MS")  # context: 2014 vs 2013
# Found AFTER the pre-set results (data-validity check, not a rule change): Scuol merged with Ardez, Ftan,
# Guarda, Sent and Tarasp on 1 Jan 2015, so its 2014 base covers a smaller area than 2015-2016.
MERGED_2015 = {"Scuol": "merged with Ardez, Ftan, Guarda, Sent and Tarasp on 1 Jan 2015"}
STAFF_H = 6
NIGHTS_PER_STAFF = (40, 180)                 # assumption range: nights per seasonal FTE per month


# --- A. Vulnerability --------------------------------------------------------
def eur_chf(con) -> pd.Series:
    eur = con.sql("SELECT date, chf_per_unit FROM fx WHERE currency = 'EUR' ORDER BY date").df()
    return eur.assign(date=pd.to_datetime(eur["date"])).set_index("date")["chf_per_unit"]


def canton_nights(con) -> pd.DataFrame:
    n = con.sql("SELECT date, geo, origin, nights FROM monthly_nights WHERE level = 'canton'").df()
    n["date"] = pd.to_datetime(n["date"])
    assert n["nights"].notna().all() and n.groupby("date")["geo"].nunique().eq(7).all()
    return n


def fx_sensitivity(y_nights: pd.Series, eur: pd.Series) -> dict:
    """Notebook 02 design: YoY log nights on YoY log CHF per EUR at lag 6, notebook 02 sample, HAC SE."""
    y = yoy_log_change(y_nights)
    x = yoy_log_change(eur).reindex(y.index)
    mask = fe.sample_mask(y, fe.fx_lags(x, range(0, 13), split=True))     # same sample as notebook 02
    res = fe.fit_hac(y, fe.fx_lags(x, range(FX_LAG, FX_LAG + 1), split=False), mask)
    b, se = res.params[f"fx_{FX_LAG}"], res.bse[f"fx_{FX_LAG}"]
    return {"beta": b, "se": se, "beta_lo": b - 1.96 * se, "beta_hi": b + 1.96 * se,
            "p": res.pvalues[f"fx_{FX_LAG}"], "N": int(res.nobs)}


def vulnerability(con) -> pd.DataFrame:
    """Exposure (euro share 2016-2019) x sensitivity (euro nights on EUR/CHF lag 6) per canton."""
    n, eur = canton_nights(con), eur_chf(con)
    yrs = n[n["date"].dt.year.between(*EXPOSURE_YEARS)]
    exposure = (yrs[yrs["origin"].isin(EURO_MARKETS)].groupby("geo")["nights"].sum()
                / yrs.groupby("geo")["nights"].sum())
    rows = []
    for geo, g in n[n["origin"].isin(EURO_MARKETS)].groupby("geo"):
        s = g.groupby("date")["nights"].sum().asfreq("MS")
        rows.append({"canton": geo, "exposure": exposure[geo], **fx_sensitivity(s, eur)})
    v = pd.DataFrame(rows)
    move = lambda b: 100 * v["exposure"] * ((1 + FRANC_MOVE) ** b - 1)
    # A stronger franc lowers nights when beta > 0: the high beta gives the most negative change
    v["vuln_pct"], v["vuln_lo"], v["vuln_hi"] = move(v["beta"]), move(v["beta_hi"]), move(v["beta_lo"])
    v = v.sort_values("vuln_pct").reset_index(drop=True)
    v["rank"] = np.arange(1, len(v) + 1)
    assert len(v) == 7 and v["exposure"].between(0, 1).all() and (v["vuln_lo"] <= v["vuln_hi"]).all()
    return v


def verdict_a(v: pd.DataFrame) -> str:
    first, second = v.iloc[0], v.iloc[1]
    separated = first["vuln_hi"] < second["vuln_lo"]       # intervals do not overlap
    return f"{first['canton']}: " + ("clearly separated" if separated else "ranking not clearly separated")


def scenario_by_canton(models: dict) -> pd.Series:
    """fx_scenarios cross-check: EUR only, -10%, canton series, 12-month total vs the 0% scenario (in %)."""
    parts = []
    for h, (model, test) in models.items():
        cant = test["level"] == "canton"
        t = test[cant]
        parts.append(pd.DataFrame({"geo": t["geo"].to_numpy(),
                                   "central": lh.predict(model, test)[cant.to_numpy()],
                                   "minus10": lh.predict(model, test, FRANC_MOVE, {"EUR"})[cant.to_numpy()]}))
    s = pd.concat(parts).groupby("geo")[["central", "minus10"]].sum()
    assert len(s) == 7 and len(parts) == 12
    return (100 * (s["minus10"] / s["central"] - 1)).rename("scenario_pct")


def cross_check(v: pd.DataFrame, scen: pd.Series) -> dict:
    m = v.set_index("canton").join(scen)
    rho = spearmanr(m["vuln_pct"], m["scenario_pct"]).statistic
    return {"spearman": float(rho), "first_vuln": m["vuln_pct"].idxmin(), "first_scenario": m["scenario_pct"].idxmin()}


# --- B. Resort pairs ---------------------------------------------------------
def resort_nights(con) -> pd.DataFrame:
    geos = tuple(g for p in PAIRS for g in p)
    n = con.sql(f"""SELECT date, geo, origin, nights FROM monthly_nights
                    WHERE level = 'commune' AND origin IN ('Germany', 'Switzerland') AND geo IN {geos}""").df()
    n["date"] = pd.to_datetime(n["date"])
    return n


def resort_pairs(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per resort x market index (post-shock and context), and per pair the German-minus-Swiss gaps."""
    n = resort_nights(con)
    window = n[n["date"].between("2013-01-01", "2016-12-01")]
    assert len(window) == 8 * 2 * 48 and window["nights"].notna().all(), "missing resort month 2013-2016"
    post_base = [d.replace(year=2014) for d in POST]                      # Jul-Dec 2014 + Jan-Dec 2014
    sub = window.set_index("date")
    cur = sub[sub.index.isin(POST)].groupby(["geo", "origin"])["nights"].sum()
    base = sum(sub[sub.index == d].groupby(["geo", "origin"])["nights"].sum() for d in post_base)
    ctx_cur = sub[sub.index.isin(PRE_CONTEXT)].groupby(["geo", "origin"])["nights"].sum()
    ctx_base = sub[sub.index.year == 2013].groupby(["geo", "origin"])["nights"].sum()
    idx = pd.DataFrame({"nights_post": cur, "nights_base_2014": base, "index_post": 100 * cur / base,
                        "index_2014_vs_2013": 100 * ctx_cur / ctx_base}).reset_index()
    idx["resort_type"] = idx["geo"].map(fc.RESORTS)
    assert len(idx) == 16 and idx.notna().all().all()

    w = idx.pivot(index="geo", columns="origin", values=["index_post", "index_2014_vs_2013"])
    gap = (w["index_post"]["Germany"] - w["index_post"]["Switzerland"]).rename("gap_post")
    gap_ctx = (w["index_2014_vs_2013"]["Germany"] - w["index_2014_vs_2013"]["Switzerland"]).rename("gap_ctx")
    rows = []
    for lux, mid in PAIRS:
        rows.append({"pair": f"{lux} - {mid}", "luxury": lux, "mid_range": mid,
                     "de_index_luxury": w["index_post"]["Germany"][lux], "de_index_mid": w["index_post"]["Germany"][mid],
                     "gap_luxury": gap[lux], "gap_mid": gap[mid],
                     "gap_ctx_luxury": gap_ctx[lux], "gap_ctx_mid": gap_ctx[mid]})
    pairs = pd.DataFrame(rows)
    pairs["luxury_fell_more"] = pairs["gap_luxury"] < pairs["gap_mid"]
    pairs["difference"] = pairs["gap_luxury"] - pairs["gap_mid"]
    pairs["comparable"] = ~(pairs["luxury"].isin(MERGED_2015) | pairs["mid_range"].isin(MERGED_2015))
    return idx, pairs


def verdict_b(pairs: pd.DataFrame) -> str:
    """Pre-set rule: luxury fell more in at least 3 of the 4 pairs."""
    return "luxury lost more" if pairs["luxury_fell_more"].sum() >= 3 else "no consistent pattern"


def verdict_b_comparable(pairs: pd.DataFrame) -> str:
    """Data-validity check (added after the results): the pre-set 3-pair threshold on comparable pairs only."""
    ok = pairs[pairs["comparable"]]
    k = int(ok["luxury_fell_more"].sum())
    return f"{'luxury lost more' if k >= 3 else 'not established'} ({k} of {len(ok)} comparable pairs)"


# --- C. Seasonal staff -------------------------------------------------------
def staff_gain(res: pd.DataFrame, con) -> pd.DataFrame:
    """Peak-month MAE of canton totals at h = 6: naive vs (naive + model with FX) / 2, with staff equivalents."""
    prof = con.sql("SELECT geo, month, avg_share_pct FROM seasonal_profile WHERE level = 'canton'").df()
    peak = prof.sort_values("avg_share_pct", ascending=False).groupby("geo").head(3)
    peak_months = peak.groupby("geo")["month"].apply(sorted)
    assert len(peak) == 21

    r = res[(res["h"] == STAFF_H) & (res["level"] == "canton")]
    tot = r.groupby(["geo", "target_date"], as_index=False)[["actual", "naive", "combo_fx"]].sum()
    assert len(tot) == 7 * 43 and r.groupby(["geo", "target_date"]).size().eq(7).all()
    tot = tot[[d.month in peak_months[g] for g, d in zip(tot["geo"], tot["target_date"])]]
    out = tot.groupby("geo").apply(lambda g: pd.Series({
        "peak_months": ", ".join(pd.Timestamp(2000, m, 1).strftime("%b") for m in peak_months[g.name]),
        "n_months": len(g),
        "mean_actual": g["actual"].mean(),
        "mae_naive": (g["actual"] - g["naive"]).abs().mean(),
        "mae_combo": (g["actual"] - g["combo_fx"]).abs().mean()}), include_groups=False)
    out["gain_nights"] = out["mae_naive"] - out["mae_combo"]
    out["gain_pct_of_peak"] = 100 * out["gain_nights"] / out["mean_actual"]
    out["staff_low"] = out["gain_nights"] / NIGHTS_PER_STAFF[1]
    out["staff_high"] = out["gain_nights"] / NIGHTS_PER_STAFF[0]
    return out.reset_index().rename(columns={"geo": "canton"})
