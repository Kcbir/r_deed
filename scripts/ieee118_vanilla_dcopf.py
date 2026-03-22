#!/usr/bin/env python3
"""
IEEE 118 — vanilla economic dispatch via DC OPF (minimum fuel cost).

Uses PYPOWER `case118` + `rundcpf`: quadratic thermal gencost (MATPOWER), no valve-point.
Adds two **fixed** RES injections (PV @ bus 60, wind @ bus 78) from
`res_forecast_hourly_24h.csv` with Pmin = Pmax = available MW each hour (full uptake).

Stage 2 — emissions:
  - Always reports thermal CO2 (kg/MWh × P) and monetized carbon using
    `ieee118_thermal_co2_kg_per_mwh.csv` + `ieee118_deed_params.csv`.
  - Optional `--carbon-price-for-opf`: adds linear monetized carbon to thermal `c1` so DC OPF
    minimizes (fuel + π·tons) in one quadratic+linear objective.

Does NOT: AC OPF, valve-point, OTS, ramp.

See docs/DATA_AND_RUNBOOK.md §8–9.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from pypower.api import case118, ppoption, rundcpf
from pypower.idx_cost import COST, NCOST
from pypower.idx_gen import GEN_BUS, GEN_STATUS, PG, PMAX, PMIN, QMAX, QMIN
from pypower.totcost import totcost

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT = ROOT / "outputs"


def _load_deed_params() -> dict[str, float]:
    p = pd.read_csv(DATA / "ieee118_deed_params.csv")
    return dict(zip(p["param"], p["value"].astype(float)))


def _load_co2_per_gen(n_expected: int) -> np.ndarray:
    df = pd.read_csv(DATA / "ieee118_thermal_co2_kg_per_mwh.csv")
    df = df.sort_values("gen_idx")
    if len(df) != n_expected:
        raise ValueError(f"Expected {n_expected} thermal gens in co2 CSV, got {len(df)}")
    return df["co2_kg_per_mwh"].values.astype(float)


def _apply_carbon_to_c1(
    gencost: np.ndarray,
    co2_kg_per_mwh: np.ndarray,
    carbon_price_usd_per_tco2: float,
    n_thermal: int,
) -> np.ndarray:
    """Add π * (kg_CO2/MWh) / 1000 to linear coefficient c1 (USD per MW per h)."""
    gc = gencost.copy()
    delta = carbon_price_usd_per_tco2 * co2_kg_per_mwh / 1000.0
    # Polynomial ncost=3: COST, COST+1, COST+2 = c2, c1, c0
    for i in range(n_thermal):
        ncost = int(gc[i, NCOST])
        if ncost < 3:
            raise ValueError(f"Unexpected NCOST for gen {i}")
        gc[i, COST + 1] += delta[i]
    return gc


def _build_ppc_with_res(
    ppc_base: dict,
    p_pv_mw: float,
    p_wind_mw: float,
    gencost_override: np.ndarray | None = None,
) -> dict:
    """Return copy of ppc with two extra fixed RES generators."""
    ppc = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in ppc_base.items()}
    if gencost_override is not None:
        ppc["gencost"] = gencost_override.copy()
    template = ppc_base["gen"][0].copy()
    n0 = ppc_base["gen"].shape[0]

    g_pv = template.copy()
    g_pv[GEN_BUS] = 60
    g_pv[PG] = p_pv_mw
    g_pv[PMAX] = p_pv_mw
    g_pv[PMIN] = p_pv_mw
    g_pv[QMAX] = min(300.0, max(30.0, p_pv_mw * 0.5))
    g_pv[QMIN] = -g_pv[QMAX]
    g_pv[GEN_STATUS] = 1

    g_wd = template.copy()
    g_wd[GEN_BUS] = 78
    g_wd[PG] = p_wind_mw
    g_wd[PMAX] = p_wind_mw
    g_wd[PMIN] = p_wind_mw
    g_wd[QMAX] = min(300.0, max(30.0, p_wind_mw * 0.5))
    g_wd[QMIN] = -g_wd[QMAX]
    g_wd[GEN_STATUS] = 1

    ppc["gen"] = np.vstack([ppc_base["gen"], g_pv, g_wd])
    extra_gc = np.array([[2, 0, 0, 3, 0, 0, 0], [2, 0, 0, 3, 0, 0, 0]], dtype=float)
    ppc["gencost"] = np.vstack([ppc["gencost"], extra_gc])
    ppc["_n_thermal"] = n0
    return ppc


def run_hour(
    ppc_base: dict,
    gencost_fuel_only: np.ndarray,
    p_pv_mw: float,
    p_wind_mw: float,
    ppopt: dict,
    gencost_for_opf: np.ndarray | None,
) -> tuple[dict | None, bool]:
    gc_opf = gencost_fuel_only if gencost_for_opf is None else gencost_for_opf
    ppc = _build_ppc_with_res(ppc_base, p_pv_mw, p_wind_mw, gencost_override=gc_opf)
    result, success = rundcpf(ppc, ppopt)
    if not success:
        return None, False
    result["_n_thermal"] = ppc["_n_thermal"]
    result["_gencost_fuel_only"] = np.vstack(
        [gencost_fuel_only, np.array([[2, 0, 0, 3, 0, 0, 0], [2, 0, 0, 3, 0, 0, 0]])]
    )
    return result, True


def thermal_fuel_cost_usd(result: dict) -> tuple[float, float]:
    """Fuel-only polynomial cost (original gencost) for thermal + RES rows."""
    n_th = int(result["_n_thermal"])
    pg = result["gen"][:, PG]
    gc_fuel = result["_gencost_fuel_only"]
    tc = totcost(gc_fuel, pg)
    return float(np.sum(tc[:n_th])), float(np.sum(tc[n_th:]))


def thermal_emissions_tons(result: dict, co2_kg_per_mwh: np.ndarray) -> float:
    """Operational CO2 tons/h from thermal units (linear in P)."""
    n_th = int(result["_n_thermal"])
    pg = result["gen"][:n_th, PG]
    kg_h = np.sum(co2_kg_per_mwh * pg)
    return float(kg_h / 1000.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="IEEE 118 vanilla DC OPF with fixed RES + emissions.")
    parser.add_argument("--hour", type=int, default=None, help="Single hour 0–23 (default: all 24).")
    parser.add_argument(
        "--carbon-price-for-opf",
        type=float,
        default=None,
        metavar="USD/tCO2",
        help="If set, OPF minimizes fuel + π·(thermal CO2) by adding π·e_i/1000 to each thermal c1.",
    )
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    fc_path = DATA / "res_forecast_hourly_24h.csv"
    fc = pd.read_csv(fc_path)
    if args.hour is not None:
        fc = fc[fc["hour_of_day"] == args.hour]
        if fc.empty:
            raise SystemExit(f"No row for hour_of_day={args.hour}")

    params = _load_deed_params()
    pi_default = float(params["carbon_price_usd_per_tco2"])

    ppc_base = case118()
    n_th = ppc_base["gen"].shape[0]
    gencost_fuel = ppc_base["gencost"].copy()
    co2 = _load_co2_per_gen(n_th)

    pi_opf = args.carbon_price_for_opf
    if pi_opf is not None and pi_opf < 0:
        raise SystemExit("--carbon-price-for-opf must be >= 0")

    gencost_opf: np.ndarray | None = None
    if pi_opf is not None and pi_opf > 0:
        gencost_opf = _apply_carbon_to_c1(gencost_fuel, co2, pi_opf, n_th)

    ppopt = ppoption(VERBOSE=0, OUT_ALL=0)

    records = []
    for _, row in fc.iterrows():
        hod = int(row["hour_of_day"])
        p_pv = float(row["p_pv_mw"])
        p_wd = float(row["p_wind_mw"])
        result, ok = run_hour(ppc_base, gencost_fuel, p_pv, p_wd, ppopt, gencost_opf)
        base_rec: dict = {
            "hour_of_day": hod,
            "opf_mode": "fuel_only" if gencost_opf is None else "carbon_weighted",
            "carbon_price_for_opf_usd_per_tco2": pi_opf if pi_opf is not None else np.nan,
        }
        if not ok or result is None:
            base_rec.update(
                {
                    "success": False,
                    "thermal_fuel_cost_usd_per_h": np.nan,
                    "thermal_tons_co2_per_h": np.nan,
                    "monetized_carbon_usd_per_h": np.nan,
                    "thermal_social_cost_usd_per_h": np.nan,
                    "res_fuel_cost_usd_per_h": np.nan,
                    "sum_Pg_thermal_mw": np.nan,
                    "P_pv_dispatch_mw": np.nan,
                    "P_wind_dispatch_mw": np.nan,
                }
            )
            records.append(base_rec)
            continue

        c_th, c_res = thermal_fuel_cost_usd(result)
        tons = thermal_emissions_tons(result, co2)
        monet = pi_default * tons
        social = c_th + monet
        n_t = int(result["_n_thermal"])
        Pg = result["gen"][:, PG]
        base_rec.update(
            {
                "success": True,
                "thermal_fuel_cost_usd_per_h": c_th,
                "thermal_tons_co2_per_h": tons,
                "monetized_carbon_usd_per_h": monet,
                "thermal_social_cost_usd_per_h": social,
                "res_fuel_cost_usd_per_h": c_res,
                "sum_Pg_thermal_mw": float(np.sum(Pg[:n_t])),
                "P_pv_dispatch_mw": float(Pg[n_t]),
                "P_wind_dispatch_mw": float(Pg[n_t + 1]),
            }
        )
        records.append(base_rec)

    out = pd.DataFrame(records).sort_values("hour_of_day")
    suffix = "_fuelopf" if gencost_opf is None else "_socialopf"
    out_path = OUT / f"ieee118_vanilla_dcopf_hourly{suffix}.csv"
    out.to_csv(out_path, index=False)

    valid = out[out["success"]]
    day_fuel = float(valid["thermal_fuel_cost_usd_per_h"].sum()) if len(valid) else float("nan")
    day_co2 = float(valid["thermal_tons_co2_per_h"].sum()) if len(valid) else float("nan")
    day_monet = float(valid["monetized_carbon_usd_per_h"].sum()) if len(valid) else float("nan")
    day_social = float(valid["thermal_social_cost_usd_per_h"].sum()) if len(valid) else float("nan")

    summary = pd.DataFrame(
        [
            {
                "case": f"IEEE118_DCOPF_fixed_RES_{suffix.strip('_')}",
                "hours_solved": int(valid.shape[0]),
                "thermal_fuel_usd_per_day_sum_of_hours": day_fuel,
                "thermal_tons_co2_per_day_sum_of_hours": day_co2,
                "monetized_carbon_usd_per_day_pi_from_deed_params": day_monet,
                "thermal_social_usd_per_day_fuel_plus_monetized": day_social,
                "carbon_price_for_reporting_usd_per_tco2": pi_default,
                "carbon_price_for_opf_usd_per_tco2": pi_opf if pi_opf is not None else np.nan,
                "source": "pypower.case118 + res_forecast + ieee118_deed_params + ieee118_thermal_co2_kg_per_mwh",
            }
        ]
    )
    sum_path = OUT / f"ieee118_vanilla_dcopf_summary{suffix}.csv"
    summary.to_csv(sum_path, index=False)

    print(out.to_string(index=False))
    print()
    print(summary.to_string(index=False))
    print(f"\nWrote {out_path}")
    print(f"Wrote {sum_path}")


if __name__ == "__main__":
    main()
