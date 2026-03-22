#!/usr/bin/env python3
"""
IEEE 118-bus only: thermal generation cost from MATPOWER case118 default dispatch.

Reads:
  datasets/ieee118/ieee118_gen_dispatch_default.csv
  (optional) datasets/ieee118/ieee118_generator_cost_usd.csv — same a,b,c as MATPOWER gencost

Outputs:
  outputs/ieee118_thermal_benchmark_summary.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT = ROOT / "outputs"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    g = pd.read_csv(DATA / "ieee118_gen_dispatch_default.csv")

    total_h = g["cost_usd_per_h_at_default"].sum()
    day = 24 * total_h

    summary = pd.DataFrame(
        [
            {
                "case": "IEEE118_MATPOWER_case118_default_dispatch",
                "thermal_cost_usd_per_h": total_h,
                "thermal_cost_usd_per_day_24h_constant": day,
                "n_generators": len(g),
                "source": "MATPOWER data/case118.m mpc.gen + mpc.gencost",
            }
        ]
    )
    out_path = OUT / "ieee118_thermal_benchmark_summary.csv"
    summary.to_csv(out_path, index=False)
    print(summary.to_string(index=False))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
