# The Strong Franc and Swiss Tourism

> **Headline (to be written at the end):** A 10% stronger franc costs [canton] X% of its European overnight stays. Luxury resorts lose [less/more] than mid-range neighbours. Adding the exchange rate cuts forecast error from A% to B% MAPE.

**Question:** How much does the appreciation of the Swiss franc explain the evolution of foreign hotel demand in 7 Swiss cantons and selected ski resorts, and does it improve demand forecasts?

## Data
- Swiss Federal Statistical Office (BFS), HESTA hotel statistics: monthly arrivals and overnight stays by canton (2005–2026) and commune (2013–2026), by guest country of residence.
- Swiss National Bank (SNB): monthly exchange rates EUR, GBP, USD, CNY vs CHF.

Details and known data issues: [`data/README.md`](data/README.md).

## Reproduce
```bash
pip install -r requirements.txt
python src/load_data.py
```

## Status
Work in progress. See [`ROADMAP.md`](ROADMAP.md).
