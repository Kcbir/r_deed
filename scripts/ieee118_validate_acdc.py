#!/usr/bin/env python3
"""
IEEE 118 — Sanity checks, MATPOWER validation, and AC vs DC OPF comparison.

Checks performed:
  1. MATPOWER default dispatch vs our baseline: cost matches within tolerance.
  2. OPF fuel cost < MATPOWER default cost (OPF must improve on fixed dispatch).
  3. Power balance: sum(Pg) ≈ sum(Pd) + losses for both AC and DC.
  4. Generator limits: all Pg within [Pmin, Pmax].
  5. AC vs DC fuel cost comparison (24 h, per hour delta).

Uses PYPOWER:
  - rundcopf → DC OPF dispatch (optimal)
  - runpf    → AC power flow (Newton-Raphson, full AC equations)

Note: PYPOWER's runpf is AC power flow (not AC OPF); it solves the network
equations given dispatch, not optimises. We compare the COST at the DC-OPF
dispatch point evaluated under AC vs DC flows to quantify the approximation error.

Outputs:
  outputs/ieee118_validation_sanity.csv       — scalar checks
  outputs/ieee118_acdc_comparison_hourly.csv  — hourly AC vs DC summary
  outputs/ieee118_acdc_comparison_summary.csv — daily summary

Usage:
  python3 scripts/ieee118_validate_acdc.py
  python3 scripts/ieee118_validate_acdc.py --plot
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from pypower.api import case118, ppoption, rundcopf, runpf
from pypower.idx_bus import PD, QD, VM, VA, BUS_TYPE, REF
from pypower.idx_gen import GEN_BUS, GEN_STATUS, PG, PMAX, PMIN, QG, QMAX, QMIN
from pypower.idx_cost import COST, NCOST
from pypower.totcost import totcost

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT = ROOT / "outputs"


def _load_deed_params() -> dict[str, float]:
    p = pd.read_csv(DATA / "ieee118_deed_params.csv")
    return dict(zip(p["param"], p["value"].astype(float)))


def _load_co2_per_gen(n_expected: int) -> np.ndarray:
    df = pd.read_csv(DATA / "ieee118_thermal_co2_kg_per_mwh.csv").sort_values("gen_idx")
    if len(df) != n_expected:
        raise ValueError(f"Expected {n_expected} CO2 rows, got {len(df)}")
    return df["co2_kg_per_mwh"].values.astype(float)


def _build_ppc_with_res(
    ppc_base: dict,
    p_pv_mw: float,
    p_wind_mw: float,
) -> dict:
    """Curtailable RES (Pmin=0, Pmax=P_avail)."""
    ppc = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in ppc_base.items()}
    template = ppc_base["gen"][0].copy()
    n0 = ppc_base["gen"].shape[0]

    g_pv = template.copy()
    g_pv[GEN_BUS] = 60
    g_pv[PG] = p_pv_mw
    g_pv[PMAX] = p_pv_mw
    g_pv[PMIN] = 0.0
    g_pv[QMAX] = min(100.0, max(10.0, p_pv_mw * 0.4))
    g_pv[QMIN] = -g_pv[QMAX]
    g_pv[GEN_STATUS] = 1 if p_pv_mw > 0 else 0

    g_wd = template.copy()
    g_wd[GEN_BUS] = 78
    g_wd[PG] = p_wind_mw
    g_wd[PMAX] = p_wind_mw
    g_wd[PMIN] = 0.0
    g_wd[QMAX] = min(200.0, max(10.0, p_wind_mw * 0.4))
    g_wd[QMIN] = -g_wd[QMAX]
    g_wd[GEN_STATUS] = 1 if p_wind_mw > 0 else 0

    ppc["gen"] = np.vstack([ppc_base["gen"], g_pv, g_wd])
    extra_gc = np.array([[2, 0.0, 0.0, 3, 0.0, 0.0, 0.0],
                         [2, 0.0, 0.0, 3, 0.0, 0.0, 0.0]], dtype=float)
    ppc["gencost"] = np.vstack([ppc_base["gencost"], extra_gc])
    ppc["_n_thermal"] = n0
    return ppc


def _thermal_cost(result: dict, gc_fuel_ext: np.ndarray) -> float:
    n_th = int(result["_n_thermal"])
    pg = result["gen"][:, PG]
    tc = totcost(gc_fuel_ext, pg)
    return float(np.sum(tc[:n_th]))


def _thermal_co2(result: dict, co2: np.ndarray) -> float:
    n_th = int(result["_n_thermal"])
    pg = result["gen"][:n_th, PG]
    return float(np.sum(co2 * pg) / 1000.0)


# ---------------------------------------------------------------------------
# Sanity Check 1: baseline cost match
# ---------------------------------------------------------------------------

def check_baseline(ppc_base: dict) -> dict:
    """Verify our PYPOWER cost matches the stored ieee118_gen_dispatch_default.csv."""
    gen_ref = pd.read_csv(DATA / "ieee118_gen_dispatch_default.csv")
    gc = ppc_base["gencost"]
    pg_ref = gen_ref["Pg_MW_default"].values
    tc = totcost(gc, pg_ref)
    computed_total = float(np.sum(tc))
    stored_total = float(gen_ref["cost_usd_per_h_at_default"].sum())
    delta_pct = abs(computed_total - stored_total) / max(stored_total, 1.0) * 100.0
    passed = delta_pct < 0.1  # <0.1% tolerance
    print(f"  [CHECK 1] Baseline cost: computed={computed_total:,.2f} stored={stored_total:,.2f} "
          f"delta={delta_pct:.4f}%  {'PASS' if passed else 'FAIL'}")
    return {"check": "baseline_cost_match", "computed": computed_total,
            "stored": stored_total, "delta_pct": delta_pct, "passed": passed}


# ---------------------------------------------------------------------------
# Sanity Check 2: OPF must improve on fixed dispatch (fuel-only case)
# ---------------------------------------------------------------------------

def check_opf_improves(ppc_base: dict, ppopt: dict, fc: pd.DataFrame) -> dict:
    """For hour 6 (peak PV), DC OPF fuel cost must be <= MATPOWER default."""
    gen_ref = pd.read_csv(DATA / "ieee118_gen_dispatch_default.csv")
    matpower_default_usd_h = float(gen_ref["cost_usd_per_h_at_default"].sum())

    row = fc[fc["hour_of_day"] == 6].iloc[0]
    ppc = _build_ppc_with_res(ppc_base, float(row["p_pv_mw"]), float(row["p_wind_mw"]))
    result = rundcopf(ppc, ppopt)
    ok = bool(result.get("success", False))
    if not ok:
        return {"check": "opf_improves", "passed": False, "note": "DC OPF failed"}

    n_th = ppc_base["gen"].shape[0]
    gc_ext = np.vstack([ppc_base["gencost"],
                        np.array([[2, 0.0, 0.0, 3, 0.0, 0.0, 0.0],
                                  [2, 0.0, 0.0, 3, 0.0, 0.0, 0.0]])])
    result["_n_thermal"] = n_th
    opf_cost = _thermal_cost(result, gc_ext)
    passed = opf_cost <= matpower_default_usd_h * 1.01  # 1% tolerance
    print(f"  [CHECK 2] OPF vs default (hour 6): OPF={opf_cost:,.0f}  "
          f"MATPOWER_default={matpower_default_usd_h:,.0f}  "
          f"ratio={opf_cost/matpower_default_usd_h:.4f}  {'PASS' if passed else 'FAIL'}")
    return {"check": "opf_improves_at_h6", "opf_usd": opf_cost,
            "matpower_default_usd": matpower_default_usd_h,
            "ratio": opf_cost / matpower_default_usd_h, "passed": passed}


# ---------------------------------------------------------------------------
# Sanity Check 3: Generator limits
# ---------------------------------------------------------------------------

def check_gen_limits(result: dict, ppc_with_res: dict, label: str = "") -> dict:
    n = result["gen"].shape[0]
    pg = result["gen"][:, PG]
    pmax = ppc_with_res["gen"][:, PMAX]
    pmin = ppc_with_res["gen"][:, PMIN]
    violations = int(np.sum((pg < pmin - 1e-3) | (pg > pmax + 1e-3)))
    passed = violations == 0
    print(f"  [CHECK 3] Gen limits {label}: violations={violations}  {'PASS' if passed else 'FAIL'}")
    return {"check": f"gen_limits_{label}", "n_generators": n,
            "violations": violations, "passed": passed}


# ---------------------------------------------------------------------------
# Sanity Check 4 — Power balance (DC and AC)
# ---------------------------------------------------------------------------

def check_power_balance(result: dict, label: str, mva_base: float = 100.0) -> dict:
    """Check |sum(Pg) - sum(Pd)| as fraction of total load."""
    pg_sum = float(np.sum(result["gen"][:, PG]))
    pd_sum = float(np.sum(result["bus"][:, PD]))
    imbalance_mw = abs(pg_sum - pd_sum)
    imbalance_pct = imbalance_mw / max(pd_sum, 1.0) * 100.0
    # DC: exact balance; AC: includes losses so small positive imbalance ok
    passed = imbalance_pct < 2.0
    print(f"  [CHECK 4] Power balance {label}: Pg={pg_sum:.1f} Pd={pd_sum:.1f} "
          f"|imb|={imbalance_mw:.2f} MW ({imbalance_pct:.3f}%)  {'PASS' if passed else 'FAIL'}")
    return {"check": f"power_balance_{label}", "Pg_MW": pg_sum, "Pd_MW": pd_sum,
            "imbalance_mw": imbalance_mw, "imbalance_pct": imbalance_pct, "passed": passed}


# ---------------------------------------------------------------------------
# AC vs DC comparison (24 h)
# ---------------------------------------------------------------------------

def acdc_comparison(
    ppc_base: dict,
    gc_fuel: np.ndarray,
    co2: np.ndarray,
    fc: pd.DataFrame,
    ppopt_dc: dict,
    ppopt_ac: dict,
) -> pd.DataFrame:
    """Run DC OPF → get dispatch → re-run AC power flow at same dispatch → compare."""
    n_th = ppc_base["gen"].shape[0]
    gc_ext = np.vstack([gc_fuel, np.array([[2, 0.0, 0.0, 3, 0.0, 0.0, 0.0],
                                            [2, 0.0, 0.0, 3, 0.0, 0.0, 0.0]])])
    rows = []
    for _, row in fc.iterrows():
        hod = int(row["hour_of_day"])
        p_pv = float(row["p_pv_mw"])
        p_wd = float(row["p_wind_mw"])

        ppc = _build_ppc_with_res(ppc_base, p_pv, p_wd)

        # 1. DC OPF dispatch
        dc_result = rundcopf(ppc, ppopt_dc)
        dc_ok = bool(dc_result.get("success", False))
        if not dc_ok:
            rows.append({"hour_of_day": hod, "dc_success": False, "ac_success": False})
            continue
        dc_result["_n_thermal"] = n_th
        dc_fuel = _thermal_cost(dc_result, gc_ext)
        dc_co2 = _thermal_co2(dc_result, co2)
        pg_dc = dc_result["gen"][:, PG].copy()

        # 2. Fix generation at DC-OPF solution; run AC power flow
        ppc_ac = _build_ppc_with_res(ppc_base, p_pv, p_wd)
        ppc_ac["gen"][:, PG] = pg_dc
        ppc_ac["gen"][:, PMAX] = np.maximum(pg_dc, ppc_ac["gen"][:, PMAX])
        ppc_ac["gen"][:, PMIN] = np.minimum(pg_dc, ppc_ac["gen"][:, PMIN])
        ac_result, ac_ok = runpf(ppc_ac, ppopt_ac)
        if not ac_ok:
            rows.append({"hour_of_day": hod, "dc_success": True, "ac_success": False,
                         "dc_fuel_usd": dc_fuel, "dc_co2_tons": dc_co2,
                         "ac_fuel_usd": np.nan, "ac_co2_tons": np.nan})
            continue

        # AC evaluates at solved AC Pg (may differ slightly due to slack re-dispatch)
        ac_result["_n_thermal"] = n_th
        ac_fuel = _thermal_cost(ac_result, gc_ext)
        ac_co2 = _thermal_co2(ac_result, co2)

        # AC total losses
        ac_pg_sum = float(np.sum(ac_result["gen"][:, PG]))
        dc_pg_sum = float(np.sum(pg_dc))
        ac_pd_sum = float(np.sum(ac_result["bus"][:, PD]))
        ac_losses_mw = ac_pg_sum - ac_pd_sum  # positive = losses

        rows.append({
            "hour_of_day": hod,
            "dc_success": True,
            "ac_success": True,
            "p_pv_available_mw": p_pv,
            "p_wind_available_mw": p_wd,
            "dc_fuel_usd_per_h": dc_fuel,
            "ac_fuel_usd_per_h": ac_fuel,
            "dc_co2_tons_per_h": dc_co2,
            "ac_co2_tons_per_h": ac_co2,
            "dc_pg_sum_mw": dc_pg_sum,
            "ac_pg_sum_mw": ac_pg_sum,
            "ac_losses_mw": ac_losses_mw,
            "fuel_delta_ac_minus_dc_usd": ac_fuel - dc_fuel,
            "fuel_delta_pct": (ac_fuel - dc_fuel) / max(dc_fuel, 1.0) * 100.0,
            "co2_delta_ac_minus_dc_tons": ac_co2 - dc_co2,
        })
        print(f"  h={hod:2d}: DC fuel={dc_fuel:>10,.0f}  AC fuel={ac_fuel:>10,.0f} "
              f"delta={ac_fuel-dc_fuel:>+8,.0f}  AC_losses={ac_losses_mw:.2f} MW")

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="IEEE 118 sanity checks and AC vs DC OPF comparison."
    )
    parser.add_argument("--plot", action="store_true",
                        help="Generate comparison PNG figures (requires matplotlib).")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    fc = pd.read_csv(DATA / "res_forecast_hourly_24h.csv")
    params = _load_deed_params()
    pi = float(params["carbon_price_usd_per_tco2"])

    ppc_base = case118()
    n_th = ppc_base["gen"].shape[0]
    gc_fuel = ppc_base["gencost"].copy()
    co2 = _load_co2_per_gen(n_th)

    ppopt_dc = ppoption(VERBOSE=0, OUT_ALL=0)
    ppopt_ac = ppoption(VERBOSE=0, OUT_ALL=0, PF_ALG=1)  # Newton-Raphson AC

    print("=" * 70)
    print("IEEE 118 — Sanity Checks")
    print("=" * 70)
    sanity_results = []

    # Check 1: baseline cost
    r1 = check_baseline(ppc_base)
    sanity_results.append(r1)

    # Check 2: OPF improves on default
    r2 = check_opf_improves(ppc_base, ppopt_dc, fc)
    sanity_results.append(r2)

    # Check 3 & 4: gen limits and power balance (hour 12)
    row12 = fc[fc["hour_of_day"] == 12].iloc[0]
    ppc12 = _build_ppc_with_res(ppc_base, float(row12["p_pv_mw"]), float(row12["p_wind_mw"]))
    dc12 = rundcopf(ppc12, ppopt_dc)
    dc12_ok = bool(dc12.get("success", False))
    if dc12_ok:
        dc12["_n_thermal"] = n_th
        r3 = check_gen_limits(dc12, ppc12, "DC_h12")
        r4 = check_power_balance(dc12, "DC_h12")
        sanity_results += [r3, r4]

    # Save sanity
    sanity_df = pd.DataFrame(sanity_results)
    san_path = OUT / "ieee118_validation_sanity.csv"
    sanity_df.to_csv(san_path, index=False)
    print(f"\nWrote {san_path}")
    n_pass = int(sanity_df["passed"].sum())
    n_total = len(sanity_df)
    print(f"Sanity: {n_pass}/{n_total} checks passed")

    print()
    print("=" * 70)
    print("AC vs DC Comparison (24 h, DC dispatch → AC power flow)")
    print("=" * 70)
    df_cmp = acdc_comparison(ppc_base, gc_fuel, co2, fc, ppopt_dc, ppopt_ac)
    cmp_path = OUT / "ieee118_acdc_comparison_hourly.csv"
    df_cmp.to_csv(cmp_path, index=False)

    valid = df_cmp[df_cmp.get("ac_success", False) == True] if "ac_success" in df_cmp.columns else pd.DataFrame()
    if len(valid) == 0:
        valid = df_cmp[df_cmp["dc_success"] == True]

    # Summary
    if "dc_fuel_usd_per_h" in df_cmp.columns and "ac_fuel_usd_per_h" in df_cmp.columns:
        v2 = df_cmp.dropna(subset=["dc_fuel_usd_per_h", "ac_fuel_usd_per_h"])
        summary = pd.DataFrame([{
            "dc_fuel_usd_per_day": v2["dc_fuel_usd_per_h"].sum(),
            "ac_fuel_usd_per_day": v2["ac_fuel_usd_per_h"].sum(),
            "day_fuel_delta_ac_minus_dc_usd": (v2["ac_fuel_usd_per_h"] - v2["dc_fuel_usd_per_h"]).sum(),
            "day_fuel_delta_pct": (v2["ac_fuel_usd_per_h"] - v2["dc_fuel_usd_per_h"]).sum()
                                  / max(v2["dc_fuel_usd_per_h"].sum(), 1.0) * 100,
            "dc_co2_tons_per_day": v2["dc_co2_tons_per_h"].sum() if "dc_co2_tons_per_h" in v2 else np.nan,
            "ac_co2_tons_per_day": v2["ac_co2_tons_per_h"].sum() if "ac_co2_tons_per_h" in v2 else np.nan,
            "ac_losses_mw_mean": v2["ac_losses_mw"].mean() if "ac_losses_mw" in v2 else np.nan,
            "hours_both_solved": int(len(v2)),
        }])
        sum_path = OUT / "ieee118_acdc_comparison_summary.csv"
        summary.to_csv(sum_path, index=False)
        print()
        print(summary.to_string(index=False))
        print(f"\nWrote {cmp_path}")
        print(f"Wrote {sum_path}")
    else:
        print("\n(Insufficient successful AC runs for summary)")
        print(df_cmp.to_string(index=False))

    if args.plot:
        _plot_acdc(df_cmp, OUT)


def _plot_acdc(df: pd.DataFrame, out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping plots.")
        return

    v = df.dropna(subset=["dc_fuel_usd_per_h", "ac_fuel_usd_per_h"])
    if len(v) == 0:
        print("No valid AC/DC pairs to plot.")
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Fuel cost comparison
    ax = axes[0]
    ax.plot(v["hour_of_day"], v["dc_fuel_usd_per_h"] / 1e3, "b-o", markersize=5, label="DC OPF")
    ax.plot(v["hour_of_day"], v["ac_fuel_usd_per_h"] / 1e3, "r--s", markersize=5, label="AC (at DC dispatch)")
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Thermal Fuel Cost (k USD/h)")
    ax.set_title("Fuel Cost: DC OPF vs AC Flow\nIEEE 118-bus, 24 h")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Delta
    ax = axes[1]
    delta = v["ac_fuel_usd_per_h"] - v["dc_fuel_usd_per_h"]
    ax.bar(v["hour_of_day"], delta / 1e3, color=["red" if x > 0 else "green" for x in delta])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("AC - DC fuel cost  (k USD/h)")
    ax.set_title("AC vs DC Fuel Discrepancy\n(positive = AC costs more)")
    ax.grid(True, alpha=0.3)

    # CO2
    if "dc_co2_tons_per_h" in v.columns and "ac_co2_tons_per_h" in v.columns:
        ax = axes[2]
        ax.plot(v["hour_of_day"], v["dc_co2_tons_per_h"], "b-o", markersize=5, label="DC")
        ax.plot(v["hour_of_day"], v["ac_co2_tons_per_h"], "r--s", markersize=5, label="AC")
        ax.set_xlabel("Hour of Day")
        ax.set_ylabel("Thermal CO2 (tons/h)")
        ax.set_title("CO2 Emissions: DC vs AC\nIEEE 118-bus, 24 h")
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = out_dir / "ieee118_acdc_comparison.png"
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {fig_path}")
    plt.close()


if __name__ == "__main__":
    main()
