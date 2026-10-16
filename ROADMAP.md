# Roadmap — Swiss tourism demand & the strong franc

**Central question:** How much does franc appreciation explain the evolution of foreign hotel demand in Swiss cantons and resorts, and does adding the exchange rate improve demand forecasts?

**Headline to fill at the end (top of README):**
> A 10% stronger franc costs [canton] X% of its European overnight stays after N months. Luxury resorts lose [less/more] than mid-range neighbours. Adding the exchange rate reduces forecast error from A% to B% MAPE.

Rules for the whole project:
- Raw data in `data/raw/` is never edited. All cleaning is code (`src/`), so every number can be reproduced.
- Covid (Mar 2020 – Dec 2021) is **excluded** when estimating FX effects; it is a supply shock, not a price shock.
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
- [ ] `notebooks/01_eda.ipynb`: 5–6 charts, each with a one-line takeaway

**Deliverable:** 3 written hypotheses, backed by charts.

## Sprint 2 — The franc effect (explanatory core)

- [ ] Features: monthly log change of each currency vs CHF, lags 0–12
- [ ] Elasticity of nights to FX by canton × market (log-log regression, seasonal controls, covid excluded)
- [ ] Event study around **15 Jan 2015**: nights indexed to 100 in 2014, EUR markets vs domestic
- [ ] Luxury vs mid-range pairs (commune level): **Germany vs Switzerland only**, see note below
- [ ] Arrivals vs length of stay (commune level): fewer guests, or shorter stays?

**Deliverable:** vulnerability ranking by canton + the 2015 event chart.

## Sprint 3 — Forecasting (ML)

- [ ] Baseline: same month last year (seasonal naive)
- [ ] SARIMAX with and without FX as exogenous variable
- [ ] LightGBM with lags of nights and FX
- [ ] Rolling-origin validation (`TimeSeriesSplit`, 12-month test windows), MAPE per canton
- [ ] Key table: error **with vs without FX** per canton

**Deliverable:** does the franc help predict demand, and where?

## Sprint 4 — Scenarios, dashboard, story

- [ ] Scenario simulator: "EUR/CHF at 0.90 → impact on nights by canton, next 12 months"
- [ ] Tableau Public dashboard: canton map with vulnerability index + scenario slider + 2015 event chart
- [ ] README in English: headline, 3 charts, method, **limitations**
- [ ] 2-minute interview pitch: problem → data → finding → decision → limitations

**Deliverable:** public repo + dashboard link, ready for CV and LinkedIn.

---

## Notes from the data checks

- **Commune pairs available from 2013:** St. Moritz–Scuol, Klosters–Tujetsch, Zermatt–Saas-Grund, Saanen (Gstaad)–Lenk. Surses, Crans-Montana and Val de Bagnes are excluded (municipal mergers, no data before 2016/2017/2021).
- **FX starts Aug 2005**, so 12-month lag features are available from mid-2006 only.
- **Canton table has overnight stays only**: average length of stay is a commune-level analysis.
- **Small markets are noise at commune level.** Share of months with fewer than 50 nights: China 75–98% in mid-range resorts, US 46–96%, Italy up to 92%. Germany stays below 18% everywhere. → Commune layer compares **German vs Swiss guests** only; other markets are analysed at canton level.
- **Known limitation:** Swiss guests are not a clean control group (a strong franc also makes holidays abroad cheaper for them). Present the 2015 comparison as descriptive evidence, not causal proof.
