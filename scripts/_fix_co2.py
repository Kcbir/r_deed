#!/usr/bin/env python3
"""One-time script: generate realistic heterogeneous CO2 emissions for IEEE 118 generators."""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"

g = pd.read_csv(DATA / "ieee118_gen_dispatch_default.csv")

# Classification by cost structure (documented rationale):
# Large baseload (Pmax>200MW, c1=20, small c2) → coal/steam, 820 kg CO2/MWh
coal_ids  = [5, 11, 12, 21, 25, 26, 28, 29, 30, 37, 40, 45]
# Mid-merit (Pmax 100-200MW, c1=20, larger c2) → gas CCGT, 400 kg CO2/MWh
ccgt_ids  = [6, 14, 20, 22, 39, 46, 51]
# Small peakers (Pmax=100MW, c1=40, c2=0.01) → gas OCGT, 550 kg CO2/MWh (remaining 35)

rows = []
for _, r in g.iterrows():
    idx = int(r["gen_idx"])
    bus = int(r["bus"])
    if idx in coal_ids:
        co2, fuel = 820.0, "coal_steam"
        note = "Large baseload (Pmax>200MW, low c2): coal/steam. 820 kg CO2/MWh (IEA coal avg)."
    elif idx in ccgt_ids:
        co2, fuel = 400.0, "gas_ccgt"
        note = "Mid-merit gas CCGT (Pmax 100-200MW, c1=20). 400 kg CO2/MWh (combined-cycle gas avg)."
    else:
        co2, fuel = 550.0, "gas_ocgt"
        note = "Gas peaker/OCGT (Pmax=100MW, c1=40). 550 kg CO2/MWh (open-cycle gas avg)."
    rows.append({"gen_idx": idx, "bus": bus, "fuel_type": fuel, "co2_kg_per_mwh": co2, "notes": note})

df = pd.DataFrame(rows)
out_path = DATA / "ieee118_thermal_co2_kg_per_mwh.csv"
df.to_csv(out_path, index=False)
print(df.groupby("fuel_type")[["co2_kg_per_mwh"]].agg(["count", "mean"]))
print(f"\nSaved {len(df)} rows → {out_path}")
