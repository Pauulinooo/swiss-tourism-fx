# The Strong Franc and Swiss Tourism

**Forecasts monthly hotel overnight stays by canton, origin market and resort type (luxury vs mid-range) six months ahead, so hotels can plan seasonal pricing and seasonal staffing, and quantifies how much the Swiss franc moves that forecast.**

> **Headline (to be written at the end):** Six months ahead, the model forecasts hotel nights with A% error (B% in peak-season months), against C% for "same month last year". Adding the exchange rate changes the error from A% to A'%; it matters most for [canton × market]. A 10% stronger franc is linked to X% fewer German nights about 6 months later.

**Question:** How well can monthly hotel nights be forecast 1–12 months ahead for 7 Swiss cantons × 7 origin markets and 8 paired ski resorts, and how much does the Swiss franc (the key explanatory variable) improve those forecasts?

## Data
- Swiss Federal Statistical Office (BFS), HESTA hotel statistics: monthly arrivals and overnight stays by canton (2005–2026) and commune (2013–2026), by guest country of residence.
- Swiss National Bank (SNB): monthly exchange rates EUR, GBP, USD, CNY vs CHF.

Details and known data issues: [`data/README.md`](data/README.md).

## Approach
1. **SQL layer + EDA** (`sql/`, `notebooks/01_eda.ipynb`): demand trends, market mix, seasonality.
2. **FX analysis → feature design** (`notebooks/02_fx_effect.ipynb`): trend regimes, which FX lags, symmetric or asymmetric effect.
3. **Forecasting** (`notebooks/03_forecasting.ipynb`): seasonal-naive baseline vs a global gradient-boosting model per horizon, without and with FX; rolling-origin validation; WAPE overall, by origin market and in peak-season months.
   Results use scikit-learn's `HistGradientBoostingRegressor`, because LightGBM could not be installed on the development machine (no `libomp` for macOS 14 on Intel). The backend is a parameter in `src/forecast.py` (`"lightgbm"` if it can be imported).
4. **Scenarios**: e.g. "EUR/CHF at 0.90 → nights by canton, next 6 months".

## Limitations
- HESTA covers hotels only: a shift of guests to holiday flats or Airbnb looks like lost demand.
- FX effects are associations, not causal effects.
- Overbooking and nightly pricing need daily, hotel-level data (cancellations, no-shows, capacity), which this project does not have. The forecast supports monthly planning (seasonal pricing levels, seasonal staffing), not revenue management.

## Reproduce
```bash
pip install -r requirements.txt
python src/load_data.py
python src/build_db.py
python src/run_experiments.py --jobs 4   # ~1 h 45 min, cached for notebooks 04-05
python src/run_long_horizon.py --jobs 4  # h = 7-12 backtest, ~5 min, cached for notebook 05
python src/export_bq.py --dry-run         # dashboard tables; drop --dry-run to upload to BigQuery
jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 \
  notebooks/01_eda.ipynb notebooks/02_fx_effect.ipynb notebooks/03_forecasting.ipynb \
  notebooks/04_forecast_experiments.ipynb notebooks/05_long_horizon.ipynb
```

## Updating with new BFS data
BFS publishes HESTA monthly, about 5-6 weeks after the end of the month.
1. **Download** from the BFS PxWeb tables, same selections and format as the current files (CSV, semicolon, see `data/README.md`):
   `px-x-1003020000_102` (canton, overnight stays, 7 cantons x 7 countries) and `px-x-1003020000_101` (commune, arrivals and overnight stays, the 8 resorts);
   optionally the SNB cube `devkum` for newer exchange rates.
2. **Save under a new file name** in `data/raw/` (e.g. `bfs_hesta_canton_monthly_2005_2026-08.csv`); never overwrite a raw file.
   Point the file names in `src/load_data.py` to the new files and add a row to the table in `data/README.md`.
3. **Move the forecast origin** to the new last month with data for all 57 series: `OUTLOOK_ORIGIN` in `src/long_horizon.py`
   (and, to extend the test period, `TEST_END` in `src/forecast.py`).
4. **Re-run the pipeline** with the commands above, in order. New data change the cache fingerprints, so `run_experiments.py`
   and `run_long_horizon.py` must run again before notebooks 04-05; then `python src/export_bq.py` to refresh the dashboard.

## Status
Work in progress. See [`ROADMAP.md`](ROADMAP.md).
