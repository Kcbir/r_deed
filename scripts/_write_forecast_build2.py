#!/usr/bin/env python3
"""Helper: overwrite ieee118_res_forecast_build.py with ensemble-wind version."""
from pathlib import Path

content = '''#!/usr/bin/env python3
"""
Build `datasets/ieee118/res_forecast_hourly_24h.csv` from archived raw CSVs.

Provenance:
  - PV shape: `archive/non_ieee118_raw/carbon_neutral_dataset_5sec (1).csv`
    First calendar day in file (2025-05-13), column `PV Output (kW)`, hourly mean kW.
    Scaled to PMAX_PV_MW = 150 MW (realistic for ~20% daily CF).
  - Wind shape: `archive/non_ieee118_raw/Test.csv`
    2017-05-13 (May 13), WS_100m ensembled across all 4 available locations to
    produce a spatially-smoothed hourly mean wind speed; cubic power curve
    vin=3, vr=12, vout=25 m/s, Pmax_wind=400 MW.

Synthetic alignment: PV=2025-05-13 and Wind=2017-05-13 both represent May 13
conditions. Re-indexed to synthetic date 2025-05-13 — treated as a single
correlated 24-h horizon for DEED/OPF experiments (same calendar day seasonality).
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "non_ieee118_raw"
OUT_DIR = ROOT / "datasets" / "ieee118"
OUT_CSV = OUT_DIR / "res_forecast_hourly_24h.csv"

PMAX_PV_MW = 150.0   # 150 MW; realistic utility-scale PV (~3.5 % of 4242 MW load)
PMAX_WIND_MW = 400.0
SYNTHETIC_DATE = "2025-05-13"
WIND_SOURCE_DAY = "2017-05-13"


def _pv_hourly() -> pd.DataFrame:
    """Hourly PV from 5-second logger; normalized by daily max then scaled to PMAX_PV_MW."""
    carbon = ARCHIVE / "carbon_neutral_dataset_5sec (1).csv"
    pvdf = pd.read_csv(carbon, parse_dates=["Timestamp"])
    pvdf = pvdf.sort_values("Timestamp")
    d0 = pvdf["Timestamp"].dt.normalize().iloc[0]
    pvdf = pvdf[pvdf["Timestamp"].dt.normalize() == d0].set_index("Timestamp")
    ph = pvdf.resample("1h").agg({"PV Output (kW)": "mean"}).dropna().reset_index()
    ph["hour_of_day"] = ph["Timestamp"].dt.hour
    ph["Timestamp"] = pd.to_datetime(SYNTHETIC_DATE) + pd.to_timedelta(ph["hour_of_day"], unit="h")
    ph["profile_date_pv"] = SYNTHETIC_DATE
    mx = ph["PV Output (kW)"].max()
    ph["pv_pu_of_pmax"] = ph["PV Output (kW)"] / mx if mx > 0 else 0.0
    ph["p_pv_mw"] = ph["pv_pu_of_pmax"] * PMAX_PV_MW
    return ph


def _wind_hourly() -> pd.DataFrame:
    """Hourly wind: ensemble average WS_100m across all 4 locations on WIND_SOURCE_DAY."""
    windf = ARCHIVE / "Test.csv"
    w = pd.read_csv(windf)
    if str(w.columns[0]).startswith("Unnamed") or w.columns[0] == "":
        w = w.iloc[:, 1:]
    w["Time"] = pd.to_datetime(w["Time"], dayfirst=True)
    # Filter to source day, all locations
    wd = w[
        (w["Time"].dt.month == 5) & (w["Time"].dt.day == 13) &
        (w["Time"].dt.year == 2017)
    ].copy()
    wd["hour_of_day"] = wd["Time"].dt.hour
    # Ensemble mean WS across locations → one spatially-smoothed speed per hour
    ws_ensemble = wd.groupby("hour_of_day")["WS_100m"].mean().reset_index()

    vin, vr, vout = 3.0, 12.0, 25.0

    def wp(vv: float) -> float:
        if vv < vin or vv >= vout:
            return 0.0
        if vv < vr:
            return PMAX_WIND_MW * ((vv ** 3 - vin ** 3) / (vr ** 3 - vin ** 3))
        return PMAX_WIND_MW

    ws_ensemble["p_wind_mw"] = ws_ensemble["WS_100m"].apply(wp)
    ws_ensemble["wind_pu_of_pmax"] = ws_ensemble["p_wind_mw"] / PMAX_WIND_MW
    ws_ensemble["profile_date_wind"] = SYNTHETIC_DATE
    ws_ensemble["wind_source_date"] = WIND_SOURCE_DAY
    ws_ensemble["ws_ensemble_m_s"] = ws_ensemble["WS_100m"].round(3)
    return ws_ensemble


def main() -> None:
    ph = _pv_hourly()
    wh = _wind_hourly()
    m = ph[
        ["Timestamp", "hour_of_day", "profile_date_pv", "p_pv_mw", "pv_pu_of_pmax"]
    ].merge(
        wh[[
            "hour_of_day", "p_wind_mw", "wind_pu_of_pmax",
            "profile_date_wind", "wind_source_date", "ws_ensemble_m_s"
        ]],
        on="hour_of_day",
        how="left",
    )
    if len(m) != 24:
        raise RuntimeError(f"Expected 24 hourly rows, got {len(m)}")
    cf_pv = m["p_pv_mw"].mean() / PMAX_PV_MW
    cf_wind = m["p_wind_mw"].mean() / PMAX_WIND_MW
    print(f"PV   Pmax={PMAX_PV_MW:.0f} MW | daily avg={m['p_pv_mw'].mean():.1f} MW | day CF={cf_pv:.1%}")
    print(f"Wind Pmax={PMAX_WIND_MW:.0f} MW | daily avg={m['p_wind_mw'].mean():.1f} MW | day CF={cf_wind:.1%}")
    m.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
'''

target = Path(__file__).resolve().parent / "ieee118_res_forecast_build.py"
target.write_text(content)
print(f"Wrote {target}")
