# Looker Studio dashboard — build guide

Three pages (plus an optional outlook page) on top of the BigQuery dataset `swiss-tourism-fx-2026.swiss_tourism_fx` (location `europe-west6`, Zurich),
loaded by `python src/export_bq.py`:

| Table | Used on | Grain |
|---|---|---|
| `nights_monthly` | Page 1 | series x month (2005 – 2026) |
| `metrics` | Page 2 | window x model x horizon x market x peak season (error **sums**) |
| `forecasts_backtest` | Page 2 | series x horizon x target month, with actuals |
| `interval_coverage` | Page 2 | horizon x market x model (out-of-sample coverage **counts** of the 80% intervals) |
| `fx_scenarios` | Page 3 | scenario x series x horizon (origin Jul 2026, targets Aug 2026 – Jul 2027), with 80% intervals |
| `outlook` | Page 4 | series x month, Aug 2026 – Jul 2027 from the Jul 2026 origin, with 80% intervals (low confidence) |

Each table and column has a description in BigQuery (visible in Looker Studio when you hover a field).

---

## 0. Setup (once)

1. Open [lookerstudio.google.com](https://lookerstudio.google.com) with the Google account that owns the GCP project.
2. **Create → Report**. In "Add data to report" choose **BigQuery → My projects → swiss-tourism-fx-2026 → swiss_tourism_fx → nights_monthly → Add**.
3. **Resource → Manage added data sources → Add a data source**: repeat for `metrics`, `forecasts_backtest`, `interval_coverage`, `fx_scenarios` and `outlook`.
4. **Theme and layout**: pick a light theme; canvas 1200 x 900 px. Use one fixed colour per origin market on every page
   (**Resource → Manage added data sources → Edit → field `market` or `origin` → "Dimension value colors"**; colours as in the
   repo charts: Switzerland blue, Germany orange, France teal, Italy amber, United Kingdom pink, United States green, China purple,
   Resort totals grey).
5. Add **pages** (Page → New page) named *Demand history*, *Forecast accuracy*, *FX scenario simulator*, *Outlook 2026/27*.
6. On every page add a small text box at the bottom: *Source: BFS, HESTA (hotel overnight stays); SNB (exchange rates). Hotels only.*

### Calculated fields (add in the data source: Edit → Add a field)

| Data source | Field | Formula | Type |
|---|---|---|---|
| `metrics` | `WAPE` | `SUM(sum_abs_error) / SUM(sum_actual)` | Percent |
| `forecasts_backtest` | `Abs error with FX` | `ABS(actual - gb_fx)` | Number |
| `fx_scenarios` | `Change vs actual rate` | `(SUM(gb_fx_scenario) - SUM(gb_fx_central)) / SUM(gb_fx_central)` | Percent |
| `fx_scenarios` | `Nights change` | `SUM(gb_fx_scenario) - SUM(gb_fx_central)` | Number |
| `interval_coverage` | `Coverage` | `SUM(n_inside) / SUM(n)` | Percent |

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

**Message:** how far off the forecast is, 1 to 12 months ahead, compared with "same month last year". The post-covid window has h = 1-12; the 2015-16 shock only h = 1-6.

| # | Element | Setup |
|---|---|---|
| Controls | Drop-down `window` | Single select, default `post_covid` (the other value is `shock_2015`, the 2015-16 franc shock) |
| | Drop-down `peak_season` | Optional; leave empty for all months |
| | Drop-down `market` | Multi-select |
| 1 | Line chart (`metrics`) | Dimension `h`, breakdown `model_label`, metric `WAPE`. Sort `h` ascending. Title: "12 months ahead the model alone is worse than 'same month last year'; the naive + model average stays at 8.2-8.7% from h = 5 to 12" |
| 2 | Table (`metrics`) | Rows `market`, columns via pivot `model_label`, metric `WAPE`; **conditional formatting**: lower = better. Add filter `h = 6` as a chart filter for a "6 months ahead" view |
| 3 | Scorecards (`metrics`) | Three scorecards of `WAPE` with chart filters `model = naive`, `model = gb_fx`, `model = combo_fx` and `h = 6` |
| 4 | Time series (`forecasts_backtest`) | Dimension `target_date`, metrics `SUM(actual)`, `SUM(naive)`, `SUM(gb_fx)`, `SUM(combo_fx)`. Add a drop-down control `series_id` (single select, default `Graubünden \| Germany`) and a chart filter `h = 6` |
| 5 | Text box | The Sprint 3B verdicts (see below) |
| 6 | Line chart (`interval_coverage`) | Dimension `h`, breakdown `model_label`, metric `Coverage`; add a reference line at 80%. Title: "The 80% intervals are slightly too wide: 85% of actual months fall inside (combination)" |
| 7 | Table (`interval_coverage`) | Rows `market`, metric `Coverage`, chart filter `model = combo_fx`; conditional formatting below 75% and above 85% (US and China are below, Switzerland and the UK above) |

Text for box 5:

> *In the 2015-16 franc shock, the model with FX had 7.6% error vs 8.8% for "same month last year" (all horizons),
> a gain that beats a time-shifted FX placebo. After covid the FX gain is inconclusive: it passes the pre-set rule
> narrowly but is not significant at 5% by the permutation p-value (0.095). WAPE = sum of absolute errors / sum of actual nights.*

---

## Page 3 — FX scenario simulator (`fx_scenarios`)

**Message:** "if the franc moves X% now, the next 12 months look like this".

| # | Element | Setup |
|---|---|---|
| Controls | Drop-down `scenario_type` | Single select, default `EUR only`. Applies to the whole page |
| | Drop-down (or slider) `fx_change_pct` | Single select, default `0`. **Group it** (select the control and charts 1, 3, 4 → Arrange → Group) so it does not filter chart 2 |
| | Drop-down `market`, `canton` | Multi-select |
| 1 | Scorecard | `SUM(gb_fx_scenario)` with title "Forecast nights, Aug 2026 – Jul 2027"; second scorecard `Change vs actual rate`. Add a chart filter `h <= 6` for a 6-month view if needed |
| 2 | Line chart — response curve | Dimension `fx_change_pct` (sort ascending), breakdown `market`, metric `Change vs actual rate`. Title: "A stronger franc goes with fewer foreign nights; Swiss guests do not move" |
| 3 | Bar chart | Dimension `market`, metric `Nights change`; Switzerland shows 0 (no FX feature) |
| 4 | Time series with band | Dimension `target_date`, metrics `SUM(gb_fx_scenario)`, `SUM(lower_80)`, `SUM(upper_80)`, `SUM(gb_fx_central)`. Style `lower_80` and `upper_80` as thin light lines (Looker has no native band; or use an area chart of the two bounds). Subtitle: "Band = 80% interval from past forecast errors, not FX uncertainty" |
| 5 | Table | `series_id`, `fx_feature`, `fx_sensitive`, `SUM(gb_fx_scenario)`, `Change vs actual rate` |
| 6 | **Text box (visible, next to the controls)** | See below |

Text for box 6 (keep it visible, not in a tooltip):

> **How to read a scenario.** A scenario means *"if the franc moves X% now"*: the exchange rate at the forecast origin
> (Jul 2026) is set X% away from its actual value; negative = stronger franc (fewer CHF per euro, dollar, pound or yuan).
> The model with FX then re-forecasts Aug 2026 – Jul 2027. *EUR only* moves EUR/CHF; *All currencies* moves EUR, GBP, USD
> and CNY together.
>
> - **Swiss guests have no FX feature**, so their forecast never changes (`fx_sensitive = FALSE`); under *EUR only*,
>   UK, US and Chinese guests do not change either.
> - **The model is a tree ensemble, so it responds in steps:** the curve is not smooth and can wiggle between neighbouring
>   scenarios (e.g. -4% can show a larger drop than -6%). Read the direction and the size at the ends, not single steps.
> - **Moves beyond about ±10% are outside what the model saw historically.** Since 2006 the year-over-year change of
>   EUR/CHF ranged from -18.1% to +10.3%; today's value is -0.8%, so a +10% move puts it at +8.8%, at the edge of that range.
>   Trees cannot extrapolate: beyond the range they repeat the response of the most extreme months seen.
> - **The response is weaker than the notebook 02 regression.** For Germany, a -10% move gives -3.1% nights over the
>   next 12 months, while the regression coefficient at lag 6 (0.63) implies about -6% (0.9^0.63 - 1 = -6.4%). The forecast
>   also uses recent nights, so the scenario shows what this model expects, **not an elasticity**.
> - **Responses are not proportional.** Germany shows -1.4% at -4% but -0.8% at -6%: tree models split the FX feature
>   at a few thresholds, so a bigger move does not always mean a bigger change.
> - **The band (`lower_80` / `upper_80`) is past forecast error, not FX uncertainty.** It is fitted on 2023-2026 errors,
>   which include the 2023 rebound, so upper bounds are wide (China above all).
> - These are **associations learned from history, not causal effects**. After covid the FX gain in the backtest is
>   inconclusive (p = 0.095), so treat scenarios as a sensitivity check, not a promise.

### What the scenarios show (from `python src/export_bq.py`, total nights over 12 months vs the actual rate)

| Market | EUR/CHF or all currencies -10% (stronger franc) | +10% (weaker franc) | Shape across the 11 steps |
|---|---|---|---|
| Germany | -3.1% | +5.6% | stepwise, same direction |
| France | -2.7% | +4.4% | stepwise, same direction |
| Italy | -2.0% | +4.9% | stepwise, same direction |
| Resort totals | -3.2% | +2.9% | stepwise, same direction |
| United Kingdom (all currencies) | -4.9% | +6.2% | stepwise, same direction |
| United States (all currencies) | -3.6% | +2.1% | stepwise, same direction |
| China (all currencies) | -4.8% | +2.8% | monotonic (flat between +4% and +8%) |
| Switzerland | 0.0% | 0.0% | flat (no FX feature) |

EUR markets give the same numbers under both scenario types, because their feature uses only EUR/CHF.

---

## Page 4 — Outlook 2026/27 (`outlook`, low confidence)

**Message:** "the next 12 months and the coming winter look roughly flat, about +1%, with a wide range".

| # | Element | Setup |
|---|---|---|
| Controls | Drop-down `in_winter` | TRUE = winter 2026/27 (Dec 2026 - Mar 2027); empty = next 12 months (Aug 2026 - Jul 2027) |
| | Drop-down `level` | Single select, default `canton` (do not add canton and resort totals together) |
| | Drop-down `market`, `canton` | Multi-select |
| 1 | Scorecards | `SUM(combo_fx)` "Forecast nights", `SUM(combo_lower_80)` and `SUM(combo_upper_80)` "Range" |
| 2 | Time series with band | Dimension `target_date`, metrics `SUM(combo_fx)`, `SUM(combo_lower_80)`, `SUM(combo_upper_80)`, `SUM(naive)` |
| 3 | Bar chart | Dimension `market`, metric `SUM(combo_fx)`; or `canton` |
| 4 | **Text box (visible)** | See below |

Text for box 4:

> **Low-confidence outlook.** Forecast = average of "same month last year" and the model with FX, made in Jul 2026
> (the last month with data for every series). Validated on one post-covid period (2023-2026). Monthly bands are 80%
> intervals from past forecast errors; **summed over months they are wider than 80%** (in the backtest they held 100% of
> 12-month totals), so read the total as a range. Upper bounds are wide because the 2023 rebound is in the errors.
> Calendar 2027 is not forecast: Aug - Dec 2027 would be 13-17 months ahead.

Headline numbers (notebook 05, 49 canton x origin series): next 12 months 25.0 m nights, +1.1% vs a year earlier
(range -9.0% to +26.5%); winter 2026/27 8.4 m nights, +1.0% (range -9.2% to +24.0%).

---

## Final checklist

- [ ] Every chart title states the takeaway; axis titles name the unit (nights, %).
- [ ] Market colours are the same on all three pages.
- [ ] Page 2 uses the calculated `WAPE`, never an average of `wape`.
- [ ] Page 3 text box 6 and page 4 text box 4 are visible without hovering.
- [ ] Source line on every page.
- [ ] **Share → Manage access**: "Anyone with the link can view". Viewers see data through your credentials
      (Data source → Data credentials: Owner's), so they need no access to the GCP project.
- [ ] After re-running `python src/export_bq.py`, click **Refresh data** in the report (tables are replaced in place, field names stay the same).
