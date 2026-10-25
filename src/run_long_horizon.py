"""
Backtest h = 7-12 on the post-covid test months (same rolling-origin design as Sprint 3A)
and cache it for notebook 05. h = 1-6 comes from the Sprint 3B cache (not re-run).

Usage:  python src/run_long_horizon.py [--jobs 4]
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")       # one thread per worker

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
import long_horizon as lh
import run_experiments as rx
from charts import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = rx.OUT
CACHE = OUT / "base_post_covid_h7_12.csv"
META = OUT / "fingerprint_long.json"
NEW_HORIZONS = range(7, 13)
FINGERPRINT_FILES = ["src/forecast.py", "src/features.py", "src/long_horizon.py", "src/run_long_horizon.py",
                     "data/processed/tourism_long.csv", "data/processed/fx_long.csv"]


def fingerprint() -> str:
    """Hash of code, data and settings, plus the Sprint 3B fingerprint (h = 1-6 comes from it)."""
    h = hashlib.sha256()
    for f in FINGERPRINT_FILES:
        h.update((ROOT / f).read_bytes())
    h.update(json.dumps({"params": fc.PARAMS, "horizons": list(NEW_HORIZONS), "rx": rx.fingerprint()}).encode())
    return h.hexdigest()


def run_h(h: int) -> pd.DataFrame:
    con = connect()
    panel, fx = fc.load_panel(con), fc.load_fx_yoy(con)
    con.close()
    with lh.horizons(range(h, h + 1)):
        return fc.backtest(panel, fx)        # default targets: the 43 post-covid months


def main(n_jobs: int) -> None:
    t0 = time.time()
    con = connect()
    panel, fx = fc.load_panel(con), fc.load_fx_yoy(con)
    con.close()
    # No look-ahead at the longest horizon: scrambling everything after the origin changes nothing
    with lh.horizons(lh.HORIZONS_LONG):
        fc.check_no_lookahead(panel, fx, h=12, origin=pd.Timestamp("2024-07-01"))
    print("no-look-ahead check at h = 12: OK")

    parts = Parallel(n_jobs=n_jobs, verbose=5)(delayed(run_h)(h) for h in NEW_HORIZONS)
    res = pd.concat(parts, ignore_index=True)
    assert sorted(res["h"].unique()) == list(NEW_HORIZONS)
    assert len(res) == 57 * 43 * len(NEW_HORIZONS)
    res.to_csv(CACHE, index=False)
    meta = {"fingerprint": fingerprint(), "seconds": round(time.time() - t0),
            "finished": time.strftime("%Y-%m-%d %H:%M")}
    META.write_text(json.dumps(meta, indent=2))
    print(f"{len(res):,} forecasts (h = 7-12) in {meta['seconds']}s -> {CACHE.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    main(ap.parse_args().jobs)
