# Data

Raw files in `raw/` are exactly as downloaded and are never edited. `src/load_data.py` builds `processed/`.

| File | Source | Content | Downloaded |
|---|---|---|---|
| `raw/bfs_hesta_canton_monthly_2005_2026.csv` | BFS, HESTA, PxWeb table `px-x-1003020000_102` | Hotel overnight stays by month, canton and guest country of residence. 7 cantons. Jan 2005 – Jul 2026 | Oct 2026 |
| `raw/bfs_hesta_commune_monthly_2013_2026.csv` | BFS, HESTA, PxWeb table `px-x-1003020000_101` | Hotel arrivals and overnight stays by month, commune and guest country of residence. Includes Tujetsch. Jan 2013 – Aug 2026 | 16 Oct 2026 |
| `raw/snb_fx_monthly_2005_2026.csv` | Swiss National Bank (SNB) data portal, cube `devkum` | Monthly average exchange rates, CHF per 1 EUR / GBP / USD and per 100 CNY. Aug 2005 – Aug 2026 | Sep 2026 |

## Known quirks (handled in `src/load_data.py`)

- Export format: semicolon delimited, cp1252 encoding, `...` = value not available or suppressed.
- Annual totals ("Total of the year") are mixed with monthly rows and must be removed before aggregating.
- The commune table spells July as `Juli`.
- FX rates: a falling value means the franc **appreciates**. CNY is quoted per 100 units.
- Commune mergers break series: Surses exists only from 2016, Crans-Montana from 2017, Val de Bagnes from 2021 (excluded from pairs, see below).
- Monthly values add up exactly to the published annual totals, except where a month is suppressed (e.g. Anniviers 2020).

## Scope decisions

- **Canton table: overnight stays only.** No re-download with Arrivals; average length of stay is analysed at commune level only.
- **FX covers Aug 2005 – Aug 2026.** No re-download from 2004; 12-month lag features start mid-2006 (accepted).
- **Tujetsch added** (mid-range pair for Klosters): complete from Jan 2013, except one suppressed German month (Nov 2025).
- **Final luxury vs mid-range pairs:** St. Moritz–Scuol, Klosters–Tujetsch, Zermatt–Saas-Grund, Saanen (Gstaad)–Lenk.
- **Excluded from pairs:** Surses, Crans-Montana, Val de Bagnes. Municipal mergers mean no data before 2016 / 2017 / 2021.
