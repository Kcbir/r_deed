#!/usr/bin/env python3
"""
IEEE 118: thermal + RES + operational CO2 (DEED-style component benchmark).

Thermal: MATPOWER default quadratic fuel cost.
Thermal CO2: sum_i (kg_CO2/MWh)_i * P_i [MWh/h] -> kg/h; x24 -> day.
Monetized carbon: carbon_price [USD/tCO2] * tons CO2 (thermal only; RES ops = 0).
RES: linear variable O&M on forecast available power (full uptake).

Reads:
  datasets/ieee118/ieee118_gen_dispatch_default.csv
  datasets/ieee118/ieee118_res_economics.csv
  datasets/ieee118/ieee118_deed_params.csv
  datasets/ieee118/ieee118_thermal_co2_kg_per_mwh.csv
  datasets/ieee118/res_forecast_hourly_24h.csv

Writes:
  outputs/ieee118_system_cost_benchmark.csv

See docs/STRATEGY.md, docs/DATA_AND_RUNBOOK.md
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT = ROOT / "outputs"


def _load_deed_params() -> dict[str, float]:
    p = pd.read_csv(DATA / "ieee118_deed_params.csv")
    return dict(zip(p["param"], p["value"].astype(float)))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    params = _load_deed_params()
    carbon_price = params["carbon_price_usd_per_tco2"]
    res_co2_kg_mwh = params["res_operational_co2_kg_per_mwh"]

    gen = pd.read_csv(DATA / "ieee118_gen_dispatch_default.csv")
    co2 = pd.read_csv(DATA / "ieee118_thermal_co2_kg_per_mwh.csv")
    g = gen.merge(co2[["gen_idx", "co2_kg_per_mwh"]], on="gen_idx", how="left")
    default_fallback = params.get("thermal_co2_kg_per_mwh_default", 520.0)
    g["co2_kg_per_mwh"] = g["co2_kg_per_mwh"].fillna(default_fallback)

    thermal_usd_per_h = g["cost_usd_per_h_at_default"].sum()
    thermal_usd_per_day_24h = 24.0 * thermal_usd_per_h

    # kg CO2 per hour = sum_i intensity_i * P_i (MWh in 1 h if P in MW)
    thermal_kg_co2_per_h = (g["co2_kg_per_mwh"] * g["Pg_MW_default"]).sum()
    thermal_tons_co2_per_h = thermal_kg_co2_per_h / 1000.0
    thermal_tons_co2_per_day = thermal_tons_co2_per_h * 24.0
    monetized_carbon_usd_per_day = carbon_price * thermal_tons_co2_per_day

    fc = pd.read_csv(DATA / "res_forecast_hourly_24h.csv")
    econ = pd.read_csv(DATA / "ieee118_res_economics.csv")

    row_pv = econ[econ["bus"] == 60].iloc[0]
    row_wd = econ[econ["bus"] == 78].iloc[0]

    dt_h = 1.0
    e_pv_mwh = fc["p_pv_mw"].sum() * dt_h
    e_wind_mwh = fc["p_wind_mw"].sum() * dt_h

    om_pv = row_pv["variable_om_usd_per_mwh"] * e_pv_mwh
    om_wind = row_wd["variable_om_usd_per_mwh"] * e_wind_mwh
    res_om_total_day = om_pv + om_wind

    res_kg_co2_day = res_co2_kg_mwh * (e_pv_mwh + e_wind_mwh)
    res_tons_co2_day = res_kg_co2_day / 1000.0

    curt_pv = row_pv["curtailment_penalty_usd_per_mwh"]
    curt_wd = row_wd["curtailment_penalty_usd_per_mwh"]

    fuel_plus_carbon_monetized_day = thermal_usd_per_day_24h + monetized_carbon_usd_per_day
    naive_all_in_day = fuel_plus_carbon_monetized_day + res_om_total_day

    summary = pd.DataFrame(
        [
            {
                "thermal_usd_per_h_matpower_default": thermal_usd_per_h,
                "thermal_usd_per_day_24h_constant_dispatch": thermal_usd_per_day_24h,
                "thermal_tons_co2_per_h_operational": thermal_tons_co2_per_h,
                "thermal_tons_co2_per_day_24h": thermal_tons_co2_per_day,
                "carbon_price_usd_per_tco2": carbon_price,
                "monetized_thermal_carbon_usd_per_day": monetized_carbon_usd_per_day,
                "res_energy_pv_mwh_forecast_day": e_pv_mwh,
                "res_energy_wind_mwh_forecast_day": e_wind_mwh,
                "res_variable_om_usd_day_pv": om_pv,
                "res_variable_om_usd_day_wind": om_wind,
                "res_variable_om_usd_per_day_total": res_om_total_day,
                "res_operational_tons_co2_per_day": res_tons_co2_day,
                "curtailment_penalty_usd_per_mwh_pv": curt_pv,
                "curtailment_penalty_usd_per_mwh_wind": curt_wd,
                "sum_fuel_plus_monetized_carbon_usd_per_day": fuel_plus_carbon_monetized_day,
                "naive_sum_fuel_carbon_res_om_usd_per_day": naive_all_in_day,
                "disclaimer": (
                    "Component breakdown at MATPOWER default thermal P; not joint optimal DEED. "
                    "Tune carbon_price & co2_kg_per_mwh. RES displaces thermal in a real solver."
                ),
            }
        ]
    )
    out_path = OUT / "ieee118_system_cost_benchmark.csv"
    summary.to_csv(out_path, index=False)
    print(summary.to_string(index=False))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
