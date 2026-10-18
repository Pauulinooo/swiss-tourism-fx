"""
Shared chart style and helpers: one look for every figure in reports/figures/.

Colours follow the entity, never the chart: Germany is the same orange everywhere.
"""

from pathlib import Path

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.transforms import ScaledTranslation
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "processed" / "tourism.duckdb"
FIGURES = ROOT / "reports" / "figures"

COVID_START, COVID_END = pd.Timestamp("2020-03-01"), pd.Timestamp("2021-12-31")

SOURCE_BFS = "Source: BFS, HESTA (hotel overnight stays)"
SOURCE_BFS_SNB = "Source: BFS, HESTA (hotel overnight stays); SNB (monthly average exchange rates)"
COVID_ROLLING_NOTE = ("Covid shaded Mar 2020 - Dec 2021. A rolling 12-month sum keeps "
                      "the covid dip until late 2022, after the shaded period ends.")

# Validated categorical palette, fixed order (slot 1 = blue, 2 = orange, ...)
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
ORIGIN_COLORS = dict(zip(
    ["Switzerland", "Germany", "France", "Italy", "United Kingdom", "United States", "China"],
    SLOTS))

INK, INK_SOFT, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
GREY = "#c4c3bd"          # context lines that should recede behind the highlighted ones


def connect() -> duckdb.DuckDBPyConnection:
    """Read-only connection: notebooks must never modify the database."""
    return duckdb.connect(str(DB_PATH), read_only=True)


def set_style() -> None:
    """Thin marks, recessive grid and axes, no chart junk."""
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "axes.titlesize": 13, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.edgecolor": GRID, "axes.labelcolor": INK_SOFT,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "xtick.color": INK_SOFT, "ytick.color": INK_SOFT, "text.color": INK,
        "lines.linewidth": 2, "legend.frameon": False,
    })


def shade_covid(ax: plt.Axes, label: bool = True) -> None:
    """Grey band over the covid months (kept in plots, excluded from FX estimates)."""
    ax.axvspan(COVID_START, COVID_END, color="#000000", alpha=0.07, lw=0, zorder=0)
    if label:
        ax.text(COVID_START + (COVID_END - COVID_START) / 2, 0.02, "covid",
                transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                fontsize=8, color=INK_SOFT)


def year_axis(ax: plt.Axes, step: int = 2) -> None:
    ax.xaxis.set_major_locator(mdates.YearLocator(step))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def add_source(fig: plt.Figure, source: str, note: str | None = None) -> None:
    """Source line (and optional note) at the bottom-left of the figure."""
    text = source if note is None else f"{note}\n{source}"
    fig.text(0.01, 0.01, text, ha="left", va="bottom", fontsize=8, color=INK_SOFT)


def save(fig: plt.Figure, name: str) -> Path:
    """Save as PNG in reports/figures/ and return the path."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    assert path.stat().st_size > 0, f"empty figure: {path}"
    return path


def label_line_ends(ax: plt.Axes, ends: dict[str, tuple], colors: dict[str, str],
                    min_gap: float) -> None:
    """Direct labels at the right end of lines, spread apart so they never overlap.

    Labels that would collide are grouped and the group is centred on the lines'
    mean, so a label stays next to its own line instead of drifting upwards.
    """
    items = sorted(ends.items(), key=lambda kv: kv[1][1])
    groups = []                                   # each: list of (name, x, y)
    for name, (x, y) in items:
        if groups:
            g = groups[-1]
            top = _centre(g) + (len(g) - 1) * min_gap / 2
            if y - top < min_gap:
                g.append((name, x, y))
                continue
        groups.append([(name, x, y)])
    # Merging can create new collisions with the group below: repeat until stable
    merged = True
    while merged:
        merged = False
        for i in range(len(groups) - 1):
            lo, hi = groups[i], groups[i + 1]
            lo_top = _centre(lo) + (len(lo) - 1) * min_gap / 2
            hi_bottom = _centre(hi) - (len(hi) - 1) * min_gap / 2
            if hi_bottom - lo_top < min_gap:
                groups[i:i + 2] = [lo + hi]
                merged = True
                break

    for g in groups:
        start = _centre(g) - (len(g) - 1) * min_gap / 2
        for k, (name, x, y) in enumerate(g):
            ax.plot([x], [y], "o", ms=4, color=colors[name], zorder=3, clip_on=False)
            # Text at the spread-out height, with a thin leader back to the line end
            ax.annotate(name, xy=(x, y), xytext=(x, start + k * min_gap),
                        textcoords=_offset_x(ax, 14),
                        ha="left", va="center", fontsize=9, color=INK, annotation_clip=False,
                        arrowprops=dict(arrowstyle="-", color="#b5b4ae", lw=0.8,
                                        shrinkA=0, shrinkB=2))


def _centre(group: list) -> float:
    """Centre of a label group: the mean of its lines' end values."""
    return sum(y for _, _, y in group) / len(group)


def _offset_x(ax: plt.Axes, points: float):
    """Transform: x in data units shifted right by `points`, y in data units."""
    return ax.transData + ScaledTranslation(points / 72, 0, ax.figure.dpi_scale_trans)
