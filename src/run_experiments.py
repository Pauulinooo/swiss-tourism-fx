"""
Sprint 3B experiments: shock backtests, FX noise floor (circular shifts), inputs
for Diebold-Mariano tests and simple combinations.

Heavy (~10,000 model fits), so results are cached in data/processed/experiments/
with a fingerprint of code, parameters and data; notebook 04 refuses to read
results whose fingerprint does not match the current files.

Usage:  python src/run_experiments.py [--jobs 4]
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")       # one thread per worker: 4 workers on 4 cores

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast as fc
from charts import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "experiments"

# Rules fixed before any result was seen (see notebook 04)
WINDOWS = {
    "post_covid": {"start": "2023-01-01", "end": "2026-07-01", "series": "all", "peak_years": (2013, 2019)},
    "shock_2015": {"start": "2015-01-01", "end": "2016-12-01", "series": "canton", "peak_years": (2005, 2010)},
    "shock_2011": {"start": "2011-09-01", "end": "2012-12-01", "series": "canton", "peak_years": (2005, 2010)},
}
N_SHIFTS = 20
FINGERPRINT_FILES = ["src/forecast.py", "src/features.py", "src/run_experiments.py",
                     "data/processed/tourism_long.csv", "data/processed/fx_long.csv"]


def fingerprint() -> str:
    """Hash of the code, data and settings that produce the cached results."""
    h = hashlib.sha256()
    for f in FINGERPRINT_FILES:
        h.update((ROOT / f).read_bytes())
    h.update(json.dumps({"params": fc.PARAMS, "windows": WINDOWS, "n_shifts": N_SHIFTS,
                         "min_shift": fc.MIN_SHIFT}, sort_keys=True).encode())
    return h.hexdigest()


def window_panel(panel: pd.DataFrame, window: str) -> pd.DataFrame:
    """Series used in a window: all 57, or the 49 canton x origin series for the shock tests."""
    if WINDOWS[window]["series"] == "canton":
        panel = panel[panel["level"] == "canton"]
        assert panel["series_id"].nunique() == 49
    return panel


def targets(window: str) -> pd.DatetimeIndex:
    w = WINDOWS[window]
    return pd.date_range(w["start"], w["end"], freq="MS")


def run_job(window: str, seed: int | None) -> tuple[str, int | None, int | None, pd.DataFrame]:
    """seed=None: base run (both models). Otherwise: model with FX on a circularly shifted FX."""
    con = connect()
    panel = window_panel(fc.load_panel(con), window)
    fx = fc.load_fx_yoy(con)
    con.close()
    if seed is None:
        return window, None, None, fc.backtest(panel, fx, targets=targets(window))
    fx_shifted, k = fc.shift_fx(fx, seed)
    res = fc.backtest(panel, fx_shifted, targets=targets(window), run_no_fx=False)
    return window, seed, k, res


def main(n_jobs: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # Biggest window first, so the 4 workers finish at about the same time
    jobs = [(w, s) for w in WINDOWS for s in [None, *range(N_SHIFTS)]]
    results = Parallel(n_jobs=n_jobs, verbose=5)(delayed(run_job)(w, s) for w, s in jobs)

    shifts_k = {}
    for window in WINDOWS:
        base = [r for w, s, _, r in results if w == window and s is None][0]
        base.to_csv(OUT / f"base_{window}.csv", index=False)
        sh = [r[["series_id", "h", "target_date", "gb_fx"]].assign(seed=s, k=k)
              for w, s, k, r in results if w == window and s is not None]
        shifted = pd.concat(sh, ignore_index=True)
        assert shifted["seed"].nunique() == N_SHIFTS and len(shifted) == N_SHIFTS * len(base)
        shifted.to_csv(OUT / f"shifts_{window}.csv", index=False)
        shifts_k[window] = {int(s): int(k) for w, s, k, _ in results if w == window and s is not None}
        print(f"{window}: {len(base):,} base forecasts, {len(shifted):,} shifted-FX forecasts")

    meta = {"fingerprint": fingerprint(), "seconds": round(time.time() - t0),
            "finished": time.strftime("%Y-%m-%d %H:%M"), "shifts_k": shifts_k}
    (OUT / "fingerprint.json").write_text(json.dumps(meta, indent=2))
    print(f"done in {meta['seconds']}s -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    main(ap.parse_args().jobs)
