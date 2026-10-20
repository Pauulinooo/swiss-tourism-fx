# Roadmap — Forecasting Swiss hotel demand, with the franc as key driver

**Product:** forecasts monthly hotel overnight stays by canton, origin market and resort type (luxury vs mid-range) six months ahead, so hotels can plan seasonal pricing and seasonal staffing, and quantifies how much the Swiss franc moves that forecast.

**Central question:** How well can monthly hotel nights be forecast 1–6 months ahead, and how much does the exchange rate improve that forecast?

**Forecast set-up (fixed):**
- **Series:** 7 cantons × 7 origin markets (49) + the total of each of the 8 paired resorts (4 luxury, 4 mid-range).
- **Horizon:** 1 to 6 months ahead.
- **FX:** features lagged **at least 6 months** (known at the forecast origin for every horizon), or used as scenarios.
- **Error:** MAPE overall **and in peak-season months** (when seasonal staff is hired), always next to the seasonal-naive baseline.

**Headline to fill at the end (top of README):**
> Six months ahead, the model forecasts hotel nights with A% error (B% in peak-season months), against C% for "same month last year". Adding the exchange rate changes the error from A% to A'%; it matters most for [canton × market]. A 10% stronger franc is linked to X% fewer German nights about 6 months later.

Rules for the whole project:
- Raw data in `data/raw/` is never edited. All cleaning is code (`src/`), so every number can be reproduced.
- Covid (Mar 2020 – Dec 2021) is **excluded** when estimating FX effects; it is a supply shock, not a price shock. Year-over-year estimates also exclude 2022 (its base months are covid months).
- Validation is always time-based (train on the past, test on the future). Never a random split.
- Every line in the repo must be explainable in an interview.

---

## Sprint 0 — Data foundation ✅ done

- [x] Repo structure (`data/`, `src/`, `sql/`, `notebooks/`, `reports/`)
- [x] Raw files renamed and documented in `data/README.md`
- [x] `src/load_data.py`: tidy long tables + check that monthly rows add up to annual totals
- [x] `git init`, `.gitignore`, `requirements.txt`, first push to GitHub
- [x] ~~Re-download the canton table with Arrivals~~ — dropped: average length of stay at commune level only
- [x] ~~Download SNB FX from 2004~~ — dropped: FX from Aug 2005, 12-month lags start mid-2006
- [x] 4th mid-range commune: **Tujetsch** (pair for Klosters), added to the commune file

**Deliverable:** `python src/load_data.py` rebuilds everything from raw files.

## Sprint 1 — SQL layer + EDA

- [x] Load processed tables into **DuckDB** (or BigQuery, same SQL) — `src/build_db.py`
- [x] `sql/` views: year-over-year change, market share by geography, seasonal profile, average length of stay
- [x] Segment cantons by seasonality: winter_peak / balanced / summer_or_flat (winter share of nights) — `sql/06_canton_segment.sql`
- [x] `notebooks/01_eda.ipynb`: 6 charts, each with a one-line takeaway, + 3 hypotheses for Sprint 2

**Deliverable:** 3 written hypotheses, backed by charts.

## Sprint 2 — FX analysis to design the forecast features

Part A (`notebooks/02_fx_effect.ipynb`):
- [x] Change point detection on German, Swiss and US nights (`ruptures`, full period + pre-covid sensitivity), compared with the 2008–09 crisis, the 2011 franc surge, the Jan 2015 floor removal and the 2014–2016 Airbnb boom
- [x] Post-covid regime vs 2016–2019: new normal, or back to the pre-covid path?
- [x] Which FX lags: YoY nights on YoY EUR/CHF, lags 0–12 and usable lags 6–12, Swiss nights as placebo
- [x] **Asymmetry** test (appreciation vs depreciation, Wald test)
- [x] Feature spec for Sprint 3

Part B:
- [ ] FX link by canton × market (same YoY design, lags ≥ 6, own currency per market): which series should get an FX feature
- [ ] Luxury vs mid-range pairs (commune level): **Germany vs Switzerland only**, see note below
- [ ] Arrivals vs length of stay (commune level): fewer guests, or shorter stays?
- [ ] *Extension (optional):* substitution towards Austria (Statistik Austria, German nights) and towards holiday flats (BFS PASTA, from 2017)

**Deliverable:** feature spec for the forecast (regimes, FX lags, symmetric or not), backed by evidence.

## Sprint 3 — Forecasting (main deliverable)

- [ ] Series: 49 canton × origin + 8 paired-resort totals; horizon 1–6 months
- [ ] Baseline: same month last year (seasonal naive)
- [ ] SARIMAX with and without FX as exogenous variable (FX lagged ≥ 6 months)
- [ ] LightGBM with lags of nights, regime/covid indicators and FX (spec from notebook 02)
- [ ] Rolling-origin validation (`TimeSeriesSplit`), change points re-detected inside each training window
- [ ] Error by horizon, overall and in **peak-season months** (default: each series' 3 highest months in `seasonal_profile`, 2013–2019)
- [ ] Key table: error **with vs without FX** per series; asymmetric FX split tested as an experiment

**Deliverable:** a 1–6-month forecast per series, and where the franc improves it.

## Sprint 4 — Scenarios, dashboard, story

- [ ] Scenario simulator: "EUR/CHF at 0.90 → impact on nights by canton, next 6 months"
- [ ] Tableau Public dashboard: canton map with vulnerability index + scenario slider + 2015 event chart
- [ ] README in English: headline, 3 charts, method, **limitations**
- [ ] *Optional storytelling:* the 2015 drop relative to the 2012–2014 trend (actual vs projected, Germany vs Switzerland), moved here from Sprint 2
- [ ] 2-minute interview pitch: problem → data → finding → decision → limitations

**Deliverable:** public repo + dashboard link, ready for CV and LinkedIn.

---

## Notes from the data checks

- **Commune pairs available from 2013:** St. Moritz–Scuol, Klosters–Tujetsch, Zermatt–Saas-Grund, Saanen (Gstaad)–Lenk. Surses, Crans-Montana and Val de Bagnes are excluded (municipal mergers, no data before 2016/2017/2021).
- **FX starts Aug 2005**, so 12-month lag features are available from mid-2006 only.
- **Canton table has overnight stays only**: average length of stay is a commune-level analysis.
- **Small markets are noise at commune level.** Share of months with fewer than 50 nights: China 75–98% in mid-range resorts, US 46–96%, Italy up to 92%. Germany stays below 18% everywhere. → Commune layer compares **German vs Swiss guests** only; other markets are analysed at canton level.
- **Known limitation:** Swiss guests are not a clean control group (a strong franc also makes holidays abroad cheaper for them). Present the 2015 comparison as descriptive evidence, not causal proof.
- **Known limitation:** HESTA covers hotels only. A shift of German guests to holiday flats or Airbnb would look like lost demand.
- **Out of scope:** overbooking and nightly pricing need daily, hotel-level data (cancellations, no-shows, capacity), which this project does not have.
