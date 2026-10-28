"""
Mockups of the 3 Looker Studio pages (docs/dashboard_mockups/page1-3.png, 1200 x 900 px).

Drawn from the CSVs that src/export_bq.py uploads to BigQuery (data/processed/bq/), so every
number on a mockup is the number the dashboard will show. Run after `python src/export_bq.py --dry-run`.
The layout, titles and labels match docs/dashboard_guide.md.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FuncFormatter, LogLocator

from charts import GRID, INK, INK_SOFT, ORIGIN_COLORS, SURFACE, set_style

ROOT = Path(__file__).resolve().parents[1]
BQ = ROOT / "data" / "processed" / "bq"
OUT = ROOT / "docs" / "dashboard_mockups"
SOURCE = "Source: BFS, HESTA (hotel overnight stays); SNB (exchange rates). Hotels only."
NOTE = "#8a8984"            # mockup-only annotations (not shown to viewers)
MARKETS = list(ORIGIN_COLORS)


# --- Numbers (same rules as the guide) ---------------------------------------
def page1_data():
    n = pd.read_csv(BQ / "nights_monthly.csv", parse_dates=["date"])
    c = n[n["level"] == "canton"]                                     # page filter level = canton
    yearly = (c[c["date"].dt.year.between(2005, 2025)]
              .groupby([c["date"].dt.year, "market"])["nights"].sum().unstack())
    assert yearly.shape == (21, 7) and yearly.notna().all().all()
    last12 = c[c["date"].between("2025-08-01", "2026-07-01")]["nights"].sum()
    prev12 = c[c["date"].between("2024-08-01", "2025-07-01")]["nights"].sum()
    assert c["date"].max() == pd.Timestamp("2026-07-01")
    return yearly, last12, 100 * (last12 / prev12 - 1)


def page2_data():
    v = pd.read_csv(BQ / "canton_vulnerability.csv").sort_values("rank")
    assert len(v) == 7 and v.iloc[0]["canton"] == "Graubünden"
    geneva = v.set_index("canton").loc["Geneva"]
    assert v["exposure_pct"].idxmax() == v.index[v["canton"] == "Geneva"][0] and geneva["rank"] == 4
    return v


def page3_data(scenario_type="All currencies", change=-10):
    s = pd.read_csv(BQ / "fx_scenarios.csv")
    s = s[(s["scenario_type"] == scenario_type) & (s["fx_change_pct"] == change) & (s["level"] == "canton")]
    g = s.groupby("market")[["gb_fx_scenario", "gb_fx_central"]].sum()
    by_market = (100 * (g["gb_fx_scenario"] / g["gb_fx_central"] - 1)).sort_values()
    assert len(by_market) == 7

    o = pd.read_csv(BQ / "outlook.csv")
    o = o[o["level"] == "canton"]
    change_vs_year = lambda d: 100 * (d["combo_fx"].sum() / d["naive"].sum() - 1)   # naive = actual a year earlier
    outlook = {"12m": change_vs_year(o), "winter": change_vs_year(o[o["in_winter"]]),
               "12m_nights": o["combo_fx"].sum(), "winter_nights": o[o["in_winter"]]["combo_fx"].sum()}

    m = pd.read_csv(BQ / "metrics.csv")
    m = m[(m["window"] == "post_covid") & (m["h"] == 6)].groupby("model")[["sum_abs_error", "sum_actual"]].sum()
    wape = 100 * m["sum_abs_error"] / m["sum_actual"]                  # from sums, never an average of wape
    assert (round(wape["combo_fx"], 1), round(wape["naive"], 1)) == (8.3, 8.7)
    assert (round(outlook["12m"], 1), round(outlook["winter"], 1)) == (1.1, 1.0)
    return by_market, outlook, wape


# --- Page furniture ----------------------------------------------------------
def page(title: str, message: str):
    fig = plt.figure(figsize=(12, 9), dpi=100)
    fig.text(0.04, 0.955, title, fontsize=22, fontweight="bold", color=INK, va="top")
    fig.text(0.04, 0.905, message, fontsize=12.5, color=INK_SOFT, va="top")
    fig.text(0.04, 0.025, SOURCE, fontsize=9, color=INK_SOFT)
    return fig


def card(fig, rect, label: str, value: str, sub: str | None = None, sub_color=INK_SOFT):
    """A Looker scorecard: label on top, big number, optional comparison line."""
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.008",
                                      transform=fig.transFigure, fc="white", ec=GRID, lw=1))
    fig.text(x + 0.015, y + h - 0.02, label, fontsize=10.5, color=INK_SOFT, va="top", wrap=True)
    fig.text(x + 0.015, y + 0.035 + (0.03 if sub else 0), value, fontsize=30, fontweight="bold", color=INK, va="bottom")
    if sub:
        fig.text(x + 0.015, y + 0.022, sub, fontsize=10.5, color=sub_color, va="bottom")


def control(fig, rect, label: str, value: str):
    """A drop-down list control."""
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.006",
                                      transform=fig.transFigure, fc="white", ec="#9b9a95", lw=1))
    fig.text(x + 0.012, y + h / 2, f"{label}:  {value}", fontsize=10.5, color=INK, va="center")
    fig.text(x + w - 0.012, y + h / 2, "▾", fontsize=11, color=INK_SOFT, va="center", ha="right")


def mock_note(fig, x, y, text):
    fig.text(x, y, text, fontsize=8.5, color=NOTE, style="italic", va="top")


def fmt_m(x: float) -> str:
    return f"{x / 1e6:.1f} m"


# --- Pages -------------------------------------------------------------------
def draw_page1():
    yearly, last12, change = page1_data()
    de, us = yearly["Germany"], yearly["United States"]
    assert de[2025] < de[2005] and us[2025] > 2 * us[2005]
    fig = page("What happened",
               "German guests stepped down after the 2011 and 2015 franc shocks and have not come back; "
               "US guests more than doubled.")
    mock_note(fig, 0.66, 0.985, "Page filter: level = canton (not visible to viewers)")

    card(fig, (0.04, 0.70, 0.30, 0.16), "Hotel nights, last 12 months (Aug 2025 - Jul 2026)",
         fmt_m(last12), f"▲ {change:+.1f}% vs previous year", sub_color="#1a7f4b")

    ax = fig.add_axes([0.08, 0.09, 0.70, 0.55])
    for mk in MARKETS:
        ax.plot(yearly.index, yearly[mk], color=ORIGIN_COLORS[mk], lw=2, marker="o", ms=3)
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e6:g} m"))
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    ax.set_xticks(range(2005, 2026, 2))
    ax.set_xlim(2004.5, 2025.5)
    ax.set_ylabel("Hotel nights per year (log scale)")
    ax.set_title("Hotel nights by guest market, 2005 - 2025 (7 cantons; 2020-21 = covid)", fontsize=13, pad=10)
    # Legend on the right, in the order of the 2025 values (as Looker sorts the breakdown by the metric)
    order = yearly.loc[2025].sort_values(ascending=False).index
    handles = [plt.Line2D([], [], color=ORIGIN_COLORS[mk], lw=2.5) for mk in order]
    fig.legend(handles, order, loc="center left", bbox_to_anchor=(0.80, 0.37), fontsize=10.5, frameon=False)
    return fig


def draw_page2():
    v = page2_data()
    geneva = v.set_index("canton").loc["Geneva"]
    first = v.iloc[0]
    fig = page("Who is most exposed",
               f"A 10% stronger franc is linked to {abs(first['vulnerability_pct']):.1f}% fewer hotel nights in "
               f"{first['canton']}, the most of 7 cantons (interval overlaps Valais).")

    # Table with bars: rank | canton (dimensions) | euro share | change in nights (bar) | 95% low | 95% high (metrics)
    ax = fig.add_axes([0.04, 0.22, 0.92, 0.62])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(len(v) + 0.6, -1.2)
    ax.text(0.0, -1.05, "Change in hotel nights for a 10% stronger franc, by canton (95% interval)",
            fontsize=13, fontweight="bold", va="center")
    cols = [(0.01, "Rank", "left"), (0.08, "Canton", "left"), (0.30, "Euro share", "right"),
            (0.40, "Change in nights", "left"), (0.86, "95% low", "right"), (0.98, "95% high", "right")]
    for x, lab, ha in cols:
        ax.text(x, -0.25, lab, fontsize=10.5, fontweight="bold", color=INK_SOFT, ha=ha, va="center")
    ax.axhline(0.15, color=GRID, lw=1)
    lo = v["vulnerability_lo"].min()
    bar_x0, bar_w = 0.34, 0.38                      # bar area: 0 at the right end, most negative at the left
    scale = bar_w / abs(lo)
    for i, r in enumerate(v.itertuples(), start=1):
        y = i - 0.15
        ax.text(0.01, y, f"{r.rank}", fontsize=11, va="center")
        ax.text(0.08, y, r.canton, fontsize=11, va="center", fontweight="bold" if r.rank == 1 else "normal")
        ax.text(0.30, y, f"{r.exposure_pct:.1f}%", fontsize=11, va="center", ha="right")
        zero = bar_x0 + bar_w
        w = abs(r.vulnerability_pct) * scale
        ax.barh(y, -w, left=zero, height=0.5, color="#c0392b" if r.rank == 1 else "#e0a39b")
        ax.text(zero - w - 0.008, y, f"{r.vulnerability_pct:.1f}%", fontsize=11, va="center", ha="right")
        ax.text(0.86, y, f"{r.vulnerability_lo:.1f}%", fontsize=11, va="center", ha="right")
        ax.text(0.98, y, f"{r.vulnerability_hi:.1f}%", fontsize=11, va="center", ha="right")
        ax.axhline(y + 0.5, color=GRID, lw=0.6)

    fig.text(0.04, 0.15, f"Geneva has the most euro guests ({geneva['exposure_pct']:.1f}%) but ranks "
                         f"{int(geneva['rank'])}th: its euro nights move less with the franc.",
             fontsize=13, color=INK, va="top")
    mock_note(fig, 0.04, 0.10, "Table sorted by rank; 'Change in nights' shown as bars; euro share = Germany, France, "
                               "Italy, 2016-2019. Associations, not causal effects.")
    return fig


def draw_page3():
    by_market, outlook, wape = page3_data()
    foreign = by_market.drop("Switzerland")
    assert round(foreign.max()) == -2 and round(foreign.min()) == -5      # "2-5%" in the message
    fig = page("Plan the next season",
               "Roughly flat, about +1%, with low confidence. If the franc strengthens 10% now, "
               "foreign markets lose 2-5% of their nights.")
    control(fig, (0.04, 0.80, 0.25, 0.05), "Scenario", "All currencies")
    control(fig, (0.31, 0.80, 0.23, 0.05), "Franc move now (%)", "-10")
    mock_note(fig, 0.56, 0.835, "Negative = stronger franc. Controls filter the bar chart only.")

    ax = fig.add_axes([0.17, 0.17, 0.42, 0.53])
    colors = [ORIGIN_COLORS[mk] for mk in by_market.index]
    ax.barh(by_market.index, by_market.values, color=colors, height=0.6)
    for y, val in enumerate(by_market.values):
        ax.text(val - 0.12 if val < 0 else 0.12, y, f"{val:.1f}%", va="center",
                ha="right" if val < 0 else "left", fontsize=10.5)
    ax.set_xlim(by_market.min() * 1.3, 0.8)
    ax.axvline(0, color=INK_SOFT, lw=0.8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    ax.set_xlabel("Change in hotel nights, Aug 2026 - Jul 2027, vs the actual rate")
    ax.set_title("Nights change by market for the selected scenario", fontsize=13, pad=10, x=-0.25, ha="left")

    card(fig, (0.66, 0.52, 0.30, 0.18), "Next 12 months (Aug 2026 - Jul 2027) vs a year earlier",
         f"{outlook['12m']:+.1f}%")
    card(fig, (0.66, 0.30, 0.30, 0.18), "Winter 2026/27 (Dec - Mar) vs a year earlier",
         f"{outlook['winter']:+.1f}%")
    mock_note(fig, 0.66, 0.285, f"Forecast: {fmt_m(outlook['12m_nights'])} and {fmt_m(outlook['winter_nights'])} "
                                "nights (outlook, combo_fx).")

    fig.text(0.04, 0.10, f"Forecast error 6 months ahead (Jan 2023 - Jul 2026): {wape['combo_fx']:.1f}% for the "
                         f"average of the model and \"same month last year\",\nvs {wape['naive']:.1f}% for "
                         "\"same month last year\" alone (WAPE).", fontsize=12, color=INK, va="top", linespacing=1.4)
    return fig


if __name__ == "__main__":
    set_style()
    plt.rcParams.update({"figure.facecolor": SURFACE})
    OUT.mkdir(parents=True, exist_ok=True)
    for i, draw in enumerate([draw_page1, draw_page2, draw_page3], start=1):
        fig = draw()
        fig.savefig(OUT / f"page{i}.png", dpi=100)
        plt.close(fig)
        size = plt.imread(OUT / f"page{i}.png").shape[:2]
        assert size == (900, 1200), size
        print(f"page{i}.png: 1200 x 900")
