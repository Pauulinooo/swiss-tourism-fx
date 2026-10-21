# Looker Studio dashboard — build guide

Three pages on top of the BigQuery dataset `data-analytics-bootcamp-363212.swiss_tourism_fx` (location `europe-west6`, Zurich),
loaded by `python src/export_bq.py`:

| Table | Used on | Grain |
|---|---|---|
| `nights_monthly` | Page 1 | series x month (2005 – 2026) |
| `metrics` | Page 2 | window x model x horizon x market x peak season (error **sums**) |
| `forecasts_backtest` | Page 2 | series x horizon x target month, with actuals |
| `fx_scenarios` | Page 3 | scenario x series x horizon (origin Jul 2026, targets Aug 2026 – Jan 2027) |

Each table and column has a description in BigQuery (visible in Looker Studio when you hover a field).

---

## 0. Setup (once)

1. Open [lookerstudio.google.com](https://lookerstudio.google.com) with the Google account that owns the GCP project.
2. **Create → Report**. In "Add data to report" choose **BigQuery → My projects → data-analytics-bootcamp-363212 → swiss_tourism_fx → nights_monthly → Add**.
3. **Resource → Manage added data sources → Add a data source**: repeat for `metrics`, `forecasts_backtest` and `fx_scenarios`.
4. **Theme and layout**: pick a light theme; canvas 1200 x 900 px. Use one fixed colour per origin market on every page
   (**Resource → Manage added data sources → Edit → field `market` or `origin` → "Dimension value colors"**; colours as in the
   repo charts: Switzerland blue, Germany orange, France teal, Italy amber, United Kingdom pink, United States green, China purple,
   Resort totals grey).
5. Add **pages** (Page → New page) named *Demand history*, *Forecast accuracy*, *FX scenario simulator*.
6. On every page add a small text box at the bottom: *Source: BFS, HESTA (hotel overnight stays); SNB (exchange rates). Hotels only.*

### Calculated fields (add in the data source: Edit → Add a field)

| Data source | Field | Formula | Type |
|---|---|---|---|
| `metrics` | `WAPE` | `SUM(sum_abs_error) / SUM(sum_actual)` | Percent |
| `forecasts_backtest` | `Abs error with FX` | `ABS(actual - gb_fx)` | Number |
| `fx_scenarios` | `Change vs actual rate` | `(SUM(gb_fx_scenario) - SUM(gb_fx_central)) / SUM(gb_fx_central)` | Percent |
| `fx_scenarios` | `Nights change` | `SUM(gb_fx_scenario) - SUM(gb_fx_central)` | Number |

> **Never average the `wape` column** of `metrics`: it is the WAPE of one row. Aggregating across horizons, markets or
> peak/off-peak needs the calculated `WAPE` above (sums first, then divide). The `peak_season` column splits rows
> (TRUE / FALSE) without duplicating them, so leaving it unfiltered gives the overall WAPE.

---

## Page 1 — Demand history (`nights_monthly`)

**Message:** where and when the nights come from, and how each market moved over 20 years.

| # | Element | Setup |
|---|---|---|
| Controls (top row) | Date range control | Default: Jan 2013 – latest |
| | Drop-down `level` | Single select, default `canton` (avoid adding canton and resort totals together) |
| | Drop-down `market` | Multi-select |
| | Drop-down `canton` | Multi-select |
| | Drop-down `segment` | Multi-select (winter_peak / balanced / summer_or_flat) |
| 1 | Scorecard | Metric `SUM(nights)`, date range "last 12 months" via the control; **Comparison date range → Previous year**, show % change. Title: "Hotel nights, last 12 months" |
| 2 | Time series | Dimension `date` (Month), breakdown `market`, metric `SUM(nights)`. Style: lines, no stacking. Add a reference band or a text note: "Mar 2020 – Dec 2021: covid" |
| 3 | 100% stacked bar | Dimension `canton`, breakdown `market`, metric `SUM(nights)` — market mix by canton |
| 4 | Pivot table with heat map | Rows `canton`, columns `MONTH(date)` (create a field `Month = MONTH(date)`), metric `SUM(nights)`, **Style → heat map** — seasonality |
| 5 | Table | `geo`, `resort_type`, `SUM(nights)`; filter `level = resort` — luxury vs mid-range pairs |

Chart titles should state the takeaway (e.g. "German nights stepped down in 2011 and 2015; Swiss nights rose after covid").

---

## Page 2 — Forecast accuracy (`metrics` + `forecasts_backtest`)

**Message:** how far off the forecast is, 1 to 6 months ahead, compared with "same month last year".

| # | Element | Setup |
|---|---|---|
| Controls | Drop-down `window` | Single select, default `post_covid` (the other value is `shock_2015`, the 2015-16 franc shock) |
| | Drop-down `peak_season` | Optional; leave empty for all months |
| | Drop-down `market` | Multi-select |
| 1 | Line chart (`metrics`) | Dimension `h`, breakdown `model_label`, metric `WAPE`. Sort `h` ascending. Title: "Error grows with the horizon; the naive + model average is the most stable at h = 6" |
| 2 | Table (`metrics`) | Rows `market`, columns via pivot `model_label`, metric `WAPE`; **conditional formatting**: lower = better. Add filter `h = 6` as a chart filter for a "6 months ahead" view |
| 3 | Scorecards (`metrics`) | Three scorecards of `WAPE` with chart filters `model = naive`, `model = gb_fx`, `model = combo_fx` and `h = 6` |
| 4 | Time series (`forecasts_backtest`) | Dimension `target_date`, metrics `SUM(actual)`, `SUM(naive)`, `SUM(gb_fx)`, `SUM(combo_fx)`. Add a drop-down control `series_id` (single select, default `Graubünden \| Germany`) and a chart filter `h = 6` |
| 5 | Text box | The Sprint 3B verdicts (see below) |

Text for box 5:

> *In the 2015-16 franc shock, the model with FX had 7.6% error vs 8.8% for "same month last year" (all horizons),
> a gain that beats a time-shifted FX placebo. After covid the FX gain is inconclusive: it passes the pre-set rule
> narrowly but is not significant at 5% by the permutation p-value (0.095). WAPE = sum of absolute errors / sum of actual nights.*

---

## Page 3 — FX scenario simulator (`fx_scenarios`)

**Message:** "if the franc moves X% now, the next 6 months look like this".

| # | Element | Setup |
|---|---|---|
| Controls | Drop-down `scenario_type` | Single select, default `EUR only`. Applies to the whole page |
| | Drop-down (or slider) `fx_change_pct` | Single select, default `0`. **Group it** (select the control and charts 1, 3, 4 → Arrange → Group) so it does not filter chart 2 |
| | Drop-down `market`, `canton` | Multi-select |
| 1 | Scorecard | `SUM(gb_fx_scenario)` with title "Forecast nights, Aug 2026 – Jan 2027"; second scorecard `Change vs actual rate` |
| 2 | Line chart — response curve | Dimension `fx_change_pct` (sort ascending), breakdown `market`, metric `Change vs actual rate`. Title: "A stronger franc goes with fewer foreign nights; Swiss guests do not move" |
| 3 | Bar chart | Dimension `market`, metric `Nights change`; Switzerland shows 0 (no FX feature) |
| 4 | Time series | Dimension `target_date`, metrics `SUM(gb_fx_scenario)`, `SUM(gb_fx_central)`, `SUM(naive)` |
| 5 | Table | `series_id`, `fx_feature`, `fx_sensitive`, `SUM(gb_fx_scenario)`, `Change vs actual rate` |
| 6 | **Text box (visible, next to the controls)** | See below |

Text for box 6 (keep it visible, not in a tooltip):

> **How to read a scenario.** A scenario means *"if the franc moves X% now"*: the exchange rate at the forecast origin
> (Jul 2026) is set X% away from its actual value; negative = stronger franc (fewer CHF per euro, dollar, pound or yuan).
> The model with FX then re-forecasts Aug 2026 – Jan 2027. *EUR only* moves EUR/CHF; *All currencies* moves EUR, GBP, USD
> and CNY together.
>
> - **Swiss guests have no FX feature**, so their forecast never changes (`fx_sensitive = FALSE`); under *EUR only*,
>   UK, US and Chinese guests do not change either.
> - **The model is a tree ensemble, so it responds in steps:** the curve is not smooth and can wiggle between neighbouring
>   scenarios (e.g. -4% can show a larger drop than -6%). Read the direction and the size at the ends, not single steps.
> - **Moves beyond about ±10% are outside what the model saw historically.** Since 2006 the year-over-year change of
>   EUR/CHF ranged from -18.1% to +10.3%; today's value is -0.8%, so a +10% move puts it at +8.8%, at the edge of that range.
>   Trees cannot extrapolate: beyond the range they repeat the response of the most extreme months seen.
> - These are **associations learned from history, not causal effects**. After covid the FX gain in the backtest is
>   inconclusive (p = 0.095), so treat scenarios as a sensitivity check, not a promise.

### What the scenarios show (from `python src/export_bq.py`, total nights over 6 months vs the actual rate)

| Market | EUR/CHF or all currencies -10% (stronger franc) | +10% (weaker franc) | Shape across the 11 steps |
|---|---|---|---|
| Germany | -2.2% | +2.3% | stepwise, same direction |
| France | -2.5% | +1.9% | stepwise, same direction |
| Italy | -1.0% | +2.8% | stepwise, same direction |
| Resort totals | -3.1% | +1.9% | stepwise, same direction |
| United Kingdom (all currencies) | -4.0% | +1.8% | monotonic |
| United States (all currencies) | -2.9% | +0.5% | stepwise; small response above 0% |
| China (all currencies) | -3.1% | +1.5% | stepwise; flat above +2% |
| Switzerland | 0.0% | 0.0% | flat (no FX feature) |

EUR markets give the same numbers under both scenario types, because their feature uses only EUR/CHF.

---

## Final checklist

- [ ] Every chart title states the takeaway; axis titles name the unit (nights, %).
- [ ] Market colours are the same on all three pages.
- [ ] Page 2 uses the calculated `WAPE`, never an average of `wape`.
- [ ] Page 3 text box 6 is visible without hovering.
- [ ] Source line on every page.
- [ ] **Share → Manage access**: "Anyone with the link can view". Viewers see data through your credentials
      (Data source → Data credentials: Owner's), so they need no access to the GCP project.
- [ ] After re-running `python src/export_bq.py`, click **Refresh data** in the report (tables are replaced in place, field names stay the same).
