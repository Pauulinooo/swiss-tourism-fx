# The Strong Franc and Swiss Tourism

**Forecasts monthly hotel overnight stays by canton, origin market and resort type (luxury vs mid-range) six months ahead, so hotels can plan seasonal pricing and seasonal staffing, and quantifies how much the Swiss franc moves that forecast.**

> **Headline (to be written at the end):** Six months ahead, the model forecasts hotel nights with A% error (B% in peak-season months), against C% for "same month last year". Adding the exchange rate changes the error from A% to A'%; it matters most for [canton × market]. A 10% stronger franc is linked to X% fewer German nights about 6 months later.

**Question:** How well can monthly hotel nights be forecast 1–6 months ahead for 7 Swiss cantons × 7 origin markets and 8 paired ski resorts, and how much does the Swiss franc (the key explanatory variable) improve those forecasts?

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
python src/run_experiments.py --jobs 4   # ~1.5 h, cached for notebook 04
jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 \
  notebooks/01_eda.ipynb notebooks/02_fx_effect.ipynb notebooks/03_forecasting.ipynb \
  notebooks/04_forecast_experiments.ipynb
```

## Status
Work in progress. See [`ROADMAP.md`](ROADMAP.md).
