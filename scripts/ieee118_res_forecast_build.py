#!/usr/bin/env python3
"""
Build `datasets/ieee118/res_forecast_hourly_24h.csv` from archived raw CSVs.

Provenance (document changes in docs/DATA_AND_RUNBOOK.md):
  - PV shape: `archive/non_ieee118_raw/carbon_neutral_dataset_5sec (1).csv`
    First calendar day in file (column Timestamp, PV Output (kW)), hourly mean kW.
  - Wind shape: `archive/non_ieee118_raw/Test.csv`
    2017-05-13, WS_100m, cubic-to-rated then flat-to-cutout; hourly mean of 15-min rows.

Alignment note: PV and wind rows are NOT the same meteorological day/year.
The merged file uses hour_of_day (0–23) to pair profiles for a single 24h horizon.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "non_ieee118_raw"
OUT_DIR = ROOT / "datasets" / "ieee118"
OUT_CSV = OUT_DIR / "res_forecast_hourly_24h.csv"

PMAX_PV_MW = 400.0
PMAX_WIND_MW = 400.0
WIND_DAY = "2017-05-13"


def _pv_hourly() -> pd.DataFrame:
    carbon = ARCHIVE / "carbon_neutral_dataset_5sec (1).csv"
    pvdf = pd.read_csv(carbon, parse_dates=["Timestamp"])
    pvdf = pvdf.sort_values("Timestamp")
    d0 = pvdf["Timestamp"].dt.normalize().iloc[0]
    pvdf = pvdf[pvdf["Timestamp"].dt.normalize() == d0].set_index("Timestamp")
    ph = pvdf.resample("1h").agg({"PV Output (kW)": "mean"}).dropna().reset_index()
    ph["hour_of_day"] = ph["Timestamp"].dt.hour
    ph["profile_date_pv"] = ph["Timestamp"].dt.strftime("%Y-%m-%d")
    mx = ph["PV Output (kW)"].max()
    ph["pv_pu_of_pmax"] = ph["PV Output (kW)"] / mx if mx > 0 else 0.0
    ph["p_pv_mw"] = ph["pv_pu_of_pmax"] * PMAX_PV_MW
    return ph


def _wind_hourly() -> pd.DataFrame:
    windf = ARCHIVE / "Test.csv"
    w = pd.read_csv(windf)
    if str(w.columns[0]).startswith("Unnamed") or w.columns[0] == "":
        w = w.iloc[:, 1:]
    w["Time"] = pd.to_datetime(w["Time"], dayfirst=True)
    wd = w[w["Time"].dt.strftime("%Y-%m-%d") == WIND_DAY].copy()
    wd = wd.sort_values("Time")
    wd["hour"] = wd["Time"].dt.floor("h")
    vin, vr, vout = 3.0, 12.0, 25.0
    rated = PMAX_WIND_MW

    def wp(vv: float) -> float:
        if vv < vin or vv >= vout:
            return 0.0
        if vv < vr:
            return rated * ((vv**3 - vin**3) / (vr**3 - vin**3))
        return rated

    wd["wind_mw_instant"] = wd["WS_100m"].astype(float).apply(wp)
    wh = wd.groupby("hour", as_index=False)["wind_mw_instant"].mean()
    wh["hour_of_day"] = wh["hour"].dt.hour
    wh["p_wind_mw"] = wh["wind_mw_instant"]
    wh["wind_pu_of_pmax"] = wh["p_wind_mw"] / PMAX_WIND_MW
    wh["profile_date_wind"] = WIND_DAY
    return wh


def main() -> None:
    ph = _pv_hourly()
    wh = _wind_hourly()
    m = ph[
        ["Timestamp", "hour_of_day", "profile_date_pv", "p_pv_mw", "pv_pu_of_pmax"]
    ].merge(wh[["hour_of_day", "p_wind_mw", "wind_pu_of_pmax", "profile_date_wind"]], on="hour_of_day", how="left")
    if len(m) != 24:
        raise RuntimeError(f"Expected 24 hourly rows, got {len(m)}")
    m.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
