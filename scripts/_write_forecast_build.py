#!/usr/bin/env python3
"""Helper: write the new ieee118_res_forecast_build.py content."""
from pathlib import Path

content = '''#!/usr/bin/env python3
"""
Build `datasets/ieee118/res_forecast_hourly_24h.csv` from archived raw CSVs.

Provenance:
  - PV shape: `archive/non_ieee118_raw/carbon_neutral_dataset_5sec (1).csv`
    First calendar day in file (2025-05-13), column `PV Output (kW)`, hourly mean kW.
    Scaled to PMAX_PV_MW = 150 MW (realistic ~20% daily CF for utility-scale PV).
  - Wind shape: `archive/non_ieee118_raw/Test.csv`
    2017-05-13 (May 13), Location==1 (representative site), WS_100m col, hourly mean;
    power curve vin=3, vr=12, vout=25 m/s, Pmax_wind=400 MW.

Synthetic alignment: PV=2025-05-13 and Wind=2017-05-13 share same calendar month/day
(May 13). Both re-indexed to synthetic date 2025-05-13 — treated as a single
correlated 24-h horizon for DEED/OPF experiments. Year difference acknowledged;
May 13 seasonality (sun angle & typical wind) is preserved.
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "non_ieee118_raw"
OUT_DIR = ROOT / "datasets" / "ieee118"
OUT_CSV = OUT_DIR / "res_forecast_hourly_24h.csv"

PMAX_PV_MW = 150.0   # realistic ~20% CF for utility-scale PV system
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
    """Hourly wind from Location=1 on 2017-05-13 (May 13); cubic power curve."""
    windf = ARCHIVE / "Test.csv"
    w = pd.read_csv(windf)
    if str(w.columns[0]).startswith("Unnamed") or w.columns[0] == "":
        w = w.iloc[:, 1:]
    w["Time"] = pd.to_datetime(w["Time"], dayfirst=True)
    wd = w[
        (w["Time"].dt.strftime("%Y-%m-%d") == WIND_SOURCE_DAY) & (w["Location"] == 1)
    ].copy()
    wd = wd.sort_values("Time")
    wd["hour"] = wd["Time"].dt.floor("h")

    vin, vr, vout = 3.0, 12.0, 25.0

    def wp(vv: float) -> float:
        if vv < vin or vv >= vout:
            return 0.0
        if vv < vr:
            return PMAX_WIND_MW * ((vv ** 3 - vin ** 3) / (vr ** 3 - vin ** 3))
        return PMAX_WIND_MW

    wd["wind_mw_instant"] = wd["WS_100m"].astype(float).apply(wp)
    wh = wd.groupby("hour", as_index=False)["wind_mw_instant"].mean()
    wh["hour_of_day"] = wh["hour"].dt.hour
    wh["p_wind_mw"] = wh["wind_mw_instant"]
    wh["wind_pu_of_pmax"] = wh["p_wind_mw"] / PMAX_WIND_MW
    wh["profile_date_wind"] = SYNTHETIC_DATE
    wh["wind_source_date"] = WIND_SOURCE_DAY
    return wh


def main() -> None:
    ph = _pv_hourly()
    wh = _wind_hourly()
    m = ph[
        ["Timestamp", "hour_of_day", "profile_date_pv", "p_pv_mw", "pv_pu_of_pmax"]
    ].merge(
        wh[["hour_of_day", "p_wind_mw", "wind_pu_of_pmax", "profile_date_wind", "wind_source_date"]],
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
