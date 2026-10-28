# Looker Studio dashboard — build guide

Three pages, one message each, on top of the BigQuery dataset `swiss-tourism-fx-2026.swiss_tourism_fx`
(location `europe-west6`, Zurich), loaded by `python src/export_bq.py`. Each page has a mockup in
[`docs/dashboard_mockups/`](dashboard_mockups/) (1200 x 900 px, drawn from the same tables by `python src/dashboard_mockups.py`):
copy the layout, titles and labels from it.

| Page | Message | Table(s) |
|---|---|---|
| 1. What happened | German guests stepped down after the 2011 and 2015 franc shocks and have not come back; US guests more than doubled | `nights_monthly` |
| 2. Who is most exposed | A 10% stronger franc is linked to 2.2% fewer hotel nights in Graubünden, the most of 7 cantons (interval overlaps Valais) | `canton_vulnerability` |
| 3. Plan the next season | Roughly flat, about +1%, with low confidence; if the franc strengthens 10% now, foreign markets lose 2-5% of their nights | `fx_scenarios`, `outlook` |

Each table and column has a description in BigQuery (hover a field in Looker Studio to see it). The other tables in the
dataset (`forecasts_backtest`, `interval_coverage`, `resort_pairs`) are not used on the dashboard; `metrics` is only used to
check the forecast-error line on page 3.

---

## 0. Setup (once)

1. Open [lookerstudio.google.com](https://lookerstudio.google.com) with the Google account that owns the GCP project.
2. **Create → Report**. In **Add data to report** choose **BigQuery → My Projects → swiss-tourism-fx-2026 → swiss_tourism_fx → nights_monthly → Add**, then **Add to report**.
3. **Resource → Manage added data sources → Add a data source**: repeat for `canton_vulnerability`, `fx_scenarios`, `outlook` and `metrics`.
4. **File → Theme and layout**: a light theme; **Layout → Canvas size → Custom, 1200 x 900**.
5. **Market colours** (same on every page): **Resource → Manage added data sources → `nights_monthly` → Edit**, then for the field `market`
   set the colours in any chart's **Style → Dimension value colors** (they are saved with the data source; repeat for `fx_scenarios`):
   Switzerland `#2a78d6`, Germany `#eb6834`, France `#1baf7a`, Italy `#eda100`, United Kingdom `#e87ba4`, United States `#008300`,
   China `#6250d6` (the repo charts' palette).
6. **Pages**: **Page → Manage pages**, rename *Page 1* and add two more with **Add a page**: *What happened*, *Who is most exposed*,
   *Plan the next season*.
7. On every page: **Insert → Text** at the top with the page name (bold, 24 px) and, below it, the page message from the table
   above (14 px, grey). At the bottom, a small text box: *Source: BFS, HESTA (hotel overnight stays); SNB (exchange rates). Hotels only.*
   These header and source boxes are not counted as page elements.

### Calculated fields (data source editor: **Resource → Manage added data sources → Edit → Add a field**)

| Data source | Field name | Formula | Type (in the data source field list) |
|---|---|---|---|
| `metrics` | `WAPE` | `SUM(sum_abs_error) / SUM(sum_actual)` | Numeric → Percent |
| `canton_vulnerability` | `Change in nights` | `MIN(vulnerability_pct) / 100` | Numeric → Percent |
| `canton_vulnerability` | `Euro share` | `MIN(exposure_pct) / 100` | Numeric → Percent |
| `canton_vulnerability` | `95% low` | `MIN(vulnerability_lo) / 100` | Numeric → Percent |
| `canton_vulnerability` | `95% high` | `MIN(vulnerability_hi) / 100` | Numeric → Percent |
| `fx_scenarios` | `Change vs actual rate` | `(SUM(gb_fx_scenario) - SUM(gb_fx_central)) / SUM(gb_fx_central)` | Numeric → Percent |
| `outlook` | `Change vs a year earlier` | `SUM(combo_fx) / SUM(naive) - 1` | Numeric → Percent |

> **WAPE comes from sums, never from an average.** The `wape` column of `metrics` is the WAPE of one row; aggregating across
> horizons, markets or peak/off-peak needs the calculated `WAPE` above (sum the errors and the actuals first, then divide).
> The same rule holds for every ratio here: `Change vs actual rate` and `Change vs a year earlier` divide sums, not averages
> of row-level percentages. The `peak_season` column of `metrics` splits rows (TRUE / FALSE) without duplicating them, so
> leaving it unfiltered gives the overall WAPE.
>
> **`canton_vulnerability` has one row per canton:** use `MIN` (as above), never `SUM`, which would only be right by accident.
>
> **`Change vs a year earlier`:** in `outlook`, `naive` is "same month last year", i.e. the actual nights a year before each
> forecast month, so this field is the forecast vs the same months a year earlier.

---

## Page 1 — What happened (`nights_monthly`)

Mockup: [`page1.png`](dashboard_mockups/page1.png)

**Page filter (applies to both elements):** **Page → Current page settings → Setup → Filters → Add a filter → Create a filter**:
name `Canton series only`, **Include**, `level`, **Equal to (=)**, `canton`, **Save**. This keeps the 49 canton x origin series
and leaves out the resort totals (they would count the same nights twice).

| # | Element | Setup |
|---|---|---|
| 1 | **Scorecard** (Insert → Scorecard), top left | **Data source** `nights_monthly`; **Date Range Dimension** `date`; **Metric** `nights` (SUM), rename it *Hotel nights, last 12 months (Aug 2025 - Jul 2026)*; **Default date range → Custom**: Aug 1, 2025 – Jul 31, 2026; **Comparison date range → Previous year**. **Style**: **Compact numbers** on, **Decimal precision** 1; comparison shown as % change |
| 2 | **Time series chart** (Insert → Time series chart), below | **Data source** `nights_monthly`; **Date Range Dimension** `date`; **Dimension** `date`, click the field's calendar icon and set **Date & time → Year**; **Breakdown Dimension** `market`; **Metric** `nights` (SUM); **Default date range → Custom**: Jan 1, 2005 – Dec 31, 2025. **Style**: **Left Y-axis → Log scale** on; **Show points** on; legend **Right**. Chart title (**Style → Chart title**, on): *Hotel nights by guest market, 2005 - 2025 (7 cantons; 2020-21 = covid)* |

Expected values (from the mockup data): scorecard **24.7 m**, **+2.3%** vs Aug 2024 – Jul 2025.

---

## Page 2 — Who is most exposed (`canton_vulnerability`)

Mockup: [`page2.png`](dashboard_mockups/page2.png)

| # | Element | Setup |
|---|---|---|
| 1 | **Table** (Insert → Table) | **Data source** `canton_vulnerability`; **Dimension** `rank`, `canton`; **Metric** `Euro share`, `Change in nights`, `95% low`, `95% high` (in this order); **Sort** `rank` **Ascending**; no date range (the table has no date). **Style → Columns → Change in nights → Bar**, **Show number** on, bar colour `#c0392b`; the other metrics **Number**, **Decimal precision** 1. **Style → Table body**: **Show row numbers** off. Chart title: *Change in hotel nights for a 10% stronger franc, by canton (95% interval)* |
| 2 | **Text** (Insert → Text), one line under the table | *Geneva has the most euro guests (27.6%) but ranks 4th: its euro nights move less with the franc.* |

Looker Studio has no error bars, so the 95% interval is two columns next to the bar (most negative end, least negative end). If the bars for negative numbers do
not display well, use **Style → Columns → Change in nights → Heatmap** instead.

Expected values: Graubünden -2.2% (-3.2% to -1.1%), Valais -1.3% (-1.9% to -0.6%), Geneva 4th at -0.9% with a 27.6% euro share.
Associations from notebook 06, not causal effects: euro share = Germany, France and Italy in 2016-2019 (7 tracked markets);
sensitivity = euro nights on EUR/CHF six months earlier, covid excluded.

---

## Page 3 — Plan the next season (`fx_scenarios`, `outlook`)

Mockup: [`page3.png`](dashboard_mockups/page3.png)

Data elements: the bar chart and two scorecards. The controls select the scenario for the bar chart only; the text line is static.

| # | Element | Setup |
|---|---|---|
| Control | **Drop-down list** (Insert → Drop-down list), top left | **Data source** `fx_scenarios`; **Control field** `scenario_type`; **Default selection** `All currencies`. **Style**: **Single select** on. Label it *Scenario* |
| Control | **Drop-down list**, next to it | **Data source** `fx_scenarios`; **Control field** `fx_change_pct`; **Sort** `fx_change_pct` **Ascending**; **Default selection** `-10`. **Style**: **Single select** on. Label it *Franc move now (%)*. Add a small grey text next to the controls: *Negative = stronger franc* |
| 1 | **Bar chart** (Insert → Bar chart, horizontal), left | **Data source** `fx_scenarios`; **Dimension** `market`; **Metric** `Change vs actual rate`; **Sort** `Change vs actual rate` **Ascending**; **Default date range → Custom**: Aug 1, 2026 – Jul 31, 2027; **Filter → Add a filter**: Include `level` Equal to `canton`. **Style**: **Show data labels** on; bar colours by **Dimension value colors** (step 5 of the setup); x-axis title *Change in hotel nights, Aug 2026 - Jul 2027, vs the actual rate*. Chart title: *Nights change by market for the selected scenario* |
| 2 | **Scorecard**, right, top | **Data source** `outlook`; **Metric** `Change vs a year earlier`, renamed *Next 12 months (Aug 2026 - Jul 2027) vs a year earlier*; **Default date range → Custom**: Aug 1, 2026 – Jul 31, 2027; **Filter**: Include `level` Equal to `canton`. **Style**: **Decimal precision** 1 |
| 3 | **Scorecard**, right, below | As scorecard 2, renamed *Winter 2026/27 (Dec - Mar) vs a year earlier*, with a second filter: Include `in_winter` Equal to `true` |
| Text | **Text**, one line at the bottom | *Forecast error 6 months ahead (Jan 2023 - Jul 2026): 8.3% for the average of the model and "same month last year", vs 8.7% for "same month last year" alone (WAPE).* |

**Why the controls do not move the scorecards:** a filter control only filters charts whose data source has the control's
field; `outlook` has no `scenario_type` or `fx_change_pct`, so the scorecards always show the central forecast.

**Checking the text line** (optional, then delete the chart): a scorecard on `metrics` with metric `WAPE` and filters
`window` = `post_covid`, `h` = 6 and `model` = `combo_fx` (8.3%) or `naive` (8.7%).

Expected values with the default scenario (all currencies, -10%): United Kingdom -4.9%, China -4.8%, United States -3.6%,
Germany -3.1%, France -2.7%, Italy -2.0%, Switzerland 0.0% (Swiss guests have no FX feature). With *EUR only*, only Germany,
France and Italy move. Scorecards: **+1.1%** (25.0 m nights) and **+1.0%** (8.4 m nights).

How to read a scenario (the column descriptions in BigQuery say the same):
- A scenario means *"if the franc moves X% now"*: the exchange rate at the forecast origin (Jul 2026) is set X% away from
  its actual value, and the model with FX re-forecasts Aug 2026 – Jul 2027.
- The model is a tree ensemble, so it responds in steps: neighbouring scenarios can wiggle (e.g. -4% can show a larger
  drop than -6%). Read the direction and the size at the ends, not single steps. Moves beyond about ±10% are outside
  what the model saw historically.
- The outlook is low confidence: validated on one post-covid period (2023-2026); its intervals are fitted on Jan 2024 –
  Jul 2026 errors (the 2023 rebound left out, decided after seeing the results).
- These are associations learned from history, not causal effects. After covid the FX gain in the backtest is
  inconclusive (p = 0.095), so treat scenarios as a sensitivity check, not a promise.

---

## Final checklist

- [ ] Three pages, each with its header message, at most 3 data elements, and the source line.
- [ ] Page 1 has the page filter `level = canton`; the time series uses **Log scale** and the year granularity.
- [ ] Market colours are the same on pages 1 and 3.
- [ ] Ratios use the calculated fields (sums first, then divide); `canton_vulnerability` metrics use `MIN`, not `SUM`.
- [ ] The numbers match the "Expected values" above and the mockups.
- [ ] **Share → Manage access**: "Anyone with the link can view". Viewers see data through your credentials
      (**Resource → Manage added data sources → Edit → Data credentials: Owner's credentials**), so they need no access to the GCP project.
- [ ] After re-running `python src/export_bq.py`, click **Refresh data** in the report (tables are replaced in place, field
      names stay the same). The text lines on pages 2 and 3 are typed in: update them if the numbers change, then re-run
      `python src/dashboard_mockups.py`.
