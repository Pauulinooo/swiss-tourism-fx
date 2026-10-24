# Roadmap — Forecasting Swiss hotel demand, with the franc as key driver

**Product:** forecasts monthly hotel overnight stays by canton, origin market and resort type (luxury vs mid-range) six months ahead, so hotels can plan seasonal pricing and seasonal staffing, and quantifies how much the Swiss franc moves that forecast.

**Central question:** How well can monthly hotel nights be forecast 1–12 months ahead, and how much does the exchange rate improve that forecast?

**Forecast set-up (fixed):**
- **Series:** 7 cantons × 7 origin markets (49) + the total of each of the 8 paired resorts (4 luxury, 4 mid-range).
- **Horizon:** 1 to 12 months ahead (7–12 added in Sprint 4; covers the winter season from a summer origin).
- **FX:** direct strategy, one model per horizon h: FX features use **lags ≥ h** (rates known at the forecast origin); FX after the origin enters only as scenarios.
- **Error:** **WAPE** (sum of absolute errors / sum of actuals) overall **and in peak-season months** (when seasonal staff is hired), always next to the seasonal-naive baseline. MAPE per series is secondary: it explodes on small, near-zero months (resort off-season).
- **Peak season (confirmed):** each series' 3 highest months by average share of annual nights, 2013–2019 (`seasonal_profile`).

**Headline (numbers from notebook 04, Sprint 3B; final wording for the README at the end):**
> Six months ahead, averaging "same month last year" with the model with FX forecasts hotel nights with 8.3% error (WAPE, post-covid 2023–2026), against 8.7% for "same month last year" alone. During the 2015–16 franc shock, the model with FX had 7.6% error against 8.8% (all horizons; 8.2% vs 8.8% at h = 6), a gain that beats a time-shifted FX placebo (p = 0.048). After covid the FX gain is inconclusive: it passes the pre-set rule narrowly (+0.16 points) but is not significant at 5% by the permutation p-value (0.095). In 2011–12, with EUR/CHF held near the 1.20 floor, there is no measurable FX gain.

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

Part B *(optional, skipped for now; Sprint 3 went first)*:
- [ ] FX link by canton × market (same YoY design, lags ≥ h per horizon, own currency per market): which series should get an FX feature
- [ ] Luxury vs mid-range pairs (commune level): **Germany vs Switzerland only**, see note below
- [ ] Arrivals vs length of stay (commune level): fewer guests, or shorter stays?
- [ ] *Extension (optional):* substitution towards Austria (Statistik Austria, German nights) and towards holiday flats (BFS PASTA, from 2017)

**Deliverable:** feature spec for the forecast (regimes, FX lags, symmetric or not), backed by evidence.

## Sprint 3 — Forecasting (main deliverable)

Part A (`src/forecast.py`, `notebooks/03_forecasting.ipynb`):
- [x] Series: 49 canton × origin + 8 paired-resort totals; horizon 1–6 months, direct strategy
- [x] Baseline: same month last year (seasonal naive)
- [x] Global gradient-boosting model per horizon (scikit-learn `HistGradientBoostingRegressor`; LightGBM switchable but not installable on the dev machine), target = seasonal log change, covid kept in training with indicators
- [x] Rolling-origin validation: same 43 target months (Jan 2023 – Jul 2026) for every horizon, expanding training window, no look-ahead (asserted + scramble test)
- [x] **WAPE** by horizon and model, overall and in **peak-season months** (each series' 3 highest months, 2013–2019); MAPE per series secondary
- [x] Main model: **ONE symmetric FX feature per horizon** (YoY log change of the market's currency vs CHF, lag h)
- [x] Key table: WAPE **with vs without FX** per series, by origin market and by canton/resort

Part B (`src/run_experiments.py`, `notebooks/04_forecast_experiments.ipynb`):
- [x] Shock backtests on the 49 canton × origin series: Jan 2015 – Dec 2016 and Sep 2011 – Dec 2012
- [x] Noise floor: 20 circular shifts of FX (24+ months, all currencies together), plus Diebold–Mariano per origin market with Holm adjustment
- [x] Simple combinations (naive + model) / 2, without and with FX, by horizon
- [ ] SARIMAX with and without FX as exogenous variable (classical benchmark)
- [ ] Regime indicators from change points re-detected inside each training window (part A uses calendar covid/post-covid indicators only)
- [ ] One experiment: appreciation/depreciation split (where the Wald test flagged it, h = 1–5), kept only if it lowers forecast error
- [ ] Validate out of sample the FX lag choice and the symmetry rule (both were selected on the full sample in notebook 02)
- [ ] Prediction intervals (e.g. quantile loss) for staffing decisions

**Deliverable:** a 1–6-month forecast per series, and where the franc improves it.

## Sprint 4 — Scenarios, dashboard, story

Part A (`src/export_bq.py`, `docs/dashboard_guide.md`):
- [x] Scenario table: franc moved -10%..+10% at the Jul 2026 origin (EUR only / all currencies), model with FX, next 6 months
- [x] Export script for BigQuery (`swiss_tourism_fx`, europe-west6): nights, backtest forecasts, WAPE sums, FX scenarios; `--dry-run` checks
- [x] Upload to BigQuery: project `swiss-tourism-fx-2026` (dedicated, billing enabled), tables never expire
- [x] Looker Studio build guide: demand history, forecast accuracy, FX scenario simulator
- [ ] Build the Looker Studio dashboard by hand from the guide (replaces the Tableau Public plan)

Part B — 12-month horizon (`src/long_horizon.py`, `src/run_long_horizon.py`, `src/outlook.py`, `notebooks/05_long_horizon.ipynb`):
- [x] Horizon h = 1–12, direct strategy, same rules; `forecast.py` unchanged (scoped `horizons` override keeps the Sprint 3B cache valid)
- [x] Validation of h = 7–12 on the same 43 post-covid target months: WAPE vs seasonal naive and combinations
- [x] 80% prediction intervals from empirical log errors per horizon × market, coverage checked out of sample (2025–26)
- [x] Low-confidence outlook from Jul 2026: next 12 months and winter 2026/27 (Dec–Mar), by canton and market
- [x] Export: `fx_scenarios` to 12 months with intervals, new tables `outlook` and `interval_coverage`; guide updated
- [ ] Upload the 12-month tables to BigQuery
- [ ] *Optional:* refit intervals without the 2023 rebound months (decision pending)
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
