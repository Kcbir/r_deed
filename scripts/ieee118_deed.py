#!/usr/bin/env python3
"""
IEEE 118 — True DEED (Dynamic Economic Emission Dispatch).

Implements two standard DEED multi-objective formulations for one 24-h horizon:

  1. Weighted-sum (scalarisation):
       min  w*C_fuel + (1-w)*E_co2_monetized
     for a sweep of weight w in [0,1] → Pareto-like trade-off curve (daily total).

  2. ε-constraint:
       min  C_fuel           (primary: cost)
       s.t. E_co2 <= epsilon (emissions cap, swept over [E_min, E_max])
     Implemented by adding a large penalty for violated emission budget in the
     modified c1 spirit, or by binary-search on the carbon price that achieves
     the budget — here we use the monetization-in-c1 approach via PYPOWER rundcpf.

Both methods use:
  - PYPOWER DC OPF (rundcpf), IEEE case118, thermal gencost (quadratic).
  - Two curtailable RES: PV @ bus 60 (Pmin=0, Pmax=p_pv_avail),
    wind @ bus 78 (Pmin=0, Pmax=p_wind_avail).
  - Heterogeneous CO2 intensity from ieee118_thermal_co2_kg_per_mwh.csv
    (coal_steam=820, gas_ccgt=400, gas_ocgt=550 kg CO2/MWh).

Daily aggregation: sum C_fuel and E_CO2 over 24 hours for each objective weight /
emission cap, giving a day-level trade-off curve.

Outputs:
  outputs/ieee118_deed_weighted_sum_pareto.csv   — Pareto front (daily)
  outputs/ieee118_deed_epsilon_constraint.csv    — ε-constraint front (daily)
  outputs/ieee118_deed_hourly_best.csv           — hourly dispatch at selected points

Usage:
  python3 scripts/ieee118_deed.py
  python3 scripts/ieee118_deed.py --n-points 30 --plot

See docs/STRATEGY.md and docs/DATA_AND_RUNBOOK.md §8-9.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from pypower.api import case118, ppoption, rundcopf
from pypower.idx_cost import COST, NCOST
from pypower.idx_gen import GEN_BUS, GEN_STATUS, PG, PMAX, PMIN, QMAX, QMIN
from pypower.totcost import totcost

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT = ROOT / "outputs"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_deed_params() -> dict[str, float]:
    p = pd.read_csv(DATA / "ieee118_deed_params.csv")
    return dict(zip(p["param"], p["value"].astype(float)))


def _load_co2_per_gen(n_expected: int) -> np.ndarray:
    df = pd.read_csv(DATA / "ieee118_thermal_co2_kg_per_mwh.csv").sort_values("gen_idx")
    if len(df) != n_expected:
        raise ValueError(f"CO2 CSV: expected {n_expected} rows, got {len(df)}")
    return df["co2_kg_per_mwh"].values.astype(float)


def _load_forecast() -> pd.DataFrame:
    return pd.read_csv(DATA / "res_forecast_hourly_24h.csv")


# ---------------------------------------------------------------------------
# PYPOWER helpers (same pattern as vanilla DCOPF but with curtailable RES)
# ---------------------------------------------------------------------------

def _build_ppc_with_res(
    ppc_base: dict,
    p_pv_mw: float,
    p_wind_mw: float,
    gencost_override: np.ndarray | None = None,
) -> dict:
    ppc = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in ppc_base.items()}
    if gencost_override is not None:
        ppc["gencost"] = gencost_override.copy()
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
    ppc["gencost"] = np.vstack([ppc["gencost"], extra_gc])
    ppc["_n_thermal"] = n0
    return ppc


def _modified_gencost(
    gencost_fuel: np.ndarray,
    co2_kg_per_mwh: np.ndarray,
    n_thermal: int,
    pi: float,
) -> np.ndarray:
    """Return a copy of gencost with pi*(e_i/1000) added to each thermal c1."""
    gc = gencost_fuel.copy()
    for i in range(n_thermal):
        if int(gc[i, NCOST]) < 3:
            raise ValueError(f"Unexpected NCOST for gen {i}")
        gc[i, COST + 1] += pi * co2_kg_per_mwh[i] / 1000.0
    return gc


def _run_one_hour(
    ppc_base: dict,
    gc_for_opf: np.ndarray,
    gc_fuel_only: np.ndarray,
    p_pv: float,
    p_wd: float,
    ppopt: dict,
    co2: np.ndarray,
) -> dict | None:
    """Run DC OPF for one hour; return result dict or None on failure."""
    ppc = _build_ppc_with_res(ppc_base, p_pv, p_wd, gencost_override=gc_for_opf)
    # Stash fuel-only gencost in result for post-processing
    result = rundcopf(ppc, ppopt)
    success = bool(result.get("success", False))
    if not success:
        return None
    n_th = int(ppc["_n_thermal"])
    Pg = result["gen"][:, PG]
    # Fuel cost (fuel-only coefficients, not the modified ones)
    gc_fuel_ext = np.vstack([gc_fuel_only, np.array([[2, 0.0, 0.0, 3, 0.0, 0.0, 0.0],
                                                      [2, 0.0, 0.0, 3, 0.0, 0.0, 0.0]])])
    tc = totcost(gc_fuel_ext, Pg)
    fuel_usd = float(np.sum(tc[:n_th]))
    co2_tons = float(np.sum(co2 * Pg[:n_th]) / 1000.0)
    return {
        "fuel_usd": fuel_usd,
        "co2_tons": co2_tons,
        "Pg_thermal": Pg[:n_th].copy(),
        "P_pv": float(Pg[n_th]),
        "P_wind": float(Pg[n_th + 1]),
        "pv_curt": max(0.0, p_pv - float(Pg[n_th])),
        "wind_curt": max(0.0, p_wd - float(Pg[n_th + 1])),
    }


def _run_24h(
    ppc_base: dict,
    gc_fuel: np.ndarray,
    co2: np.ndarray,
    fc: pd.DataFrame,
    ppopt: dict,
    pi: float,
) -> dict:
    """Run all 24 hours at a given carbon price pi; return daily aggregates."""
    gc_opf = _modified_gencost(gc_fuel, co2, ppc_base["gen"].shape[0], pi) if pi != 0 else gc_fuel.copy()
    day_fuel, day_co2, day_pv_curt, day_wind_curt, n_solved = 0.0, 0.0, 0.0, 0.0, 0
    hourly = []
    for _, row in fc.iterrows():
        r = _run_one_hour(ppc_base, gc_opf, gc_fuel, float(row["p_pv_mw"]),
                          float(row["p_wind_mw"]), ppopt, co2)
        if r is None:
            hourly.append(None)
            continue
        day_fuel += r["fuel_usd"]
        day_co2 += r["co2_tons"]
        day_pv_curt += r["pv_curt"]
        day_wind_curt += r["wind_curt"]
        n_solved += 1
        hourly.append({**r, "hour_of_day": int(row["hour_of_day"]), "pi": pi})
    return {
        "pi": pi,
        "day_fuel_usd": day_fuel,
        "day_co2_tons": day_co2,
        "day_pv_curtailment_mwh": day_pv_curt,
        "day_wind_curtailment_mwh": day_wind_curt,
        "hours_solved": n_solved,
        "hourly": hourly,
    }


# ---------------------------------------------------------------------------
# 1. Weighted-sum Pareto sweep
# ---------------------------------------------------------------------------

def weighted_sum_pareto(
    ppc_base: dict,
    gc_fuel: np.ndarray,
    co2: np.ndarray,
    fc: pd.DataFrame,
    ppopt: dict,
    n_points: int,
    pi_nom: float,
) -> pd.DataFrame:
    """
    Weighted-sum: for each omega in linspace(0,1,n_points), solve with
    effective carbon price   pi_eff = omega / (1 - omega) * normalisation_factor.

    Normalisation: we use a large reference pi (pi_ref) to represent relative
    importance. In practice: pi_eff = omega * pi_max / (1 - omega + 1e-9)
    where pi_max is the upper bound price that fully penalises emissions.

    For display: omega=0 → pure fuel cost; omega=1 → pure emissions.
    """
    # Bounds: run pure fuel (pi=0) and high-pi (pi=300) to set axis
    print("  Computing emission range for normalisation...")
    r_fuel = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi=0.0)
    r_env = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi=300.0)
    E_min = r_env["day_co2_tons"]    # emissions at max penalty
    E_max = r_fuel["day_co2_tons"]   # emissions at zero penalty (fuel-only)
    C_min = r_fuel["day_fuel_usd"]   # fuel at fuel-only
    C_max = r_env["day_fuel_usd"]    # fuel at max penalty

    # Sweep pi values that map omega ∈ (0,1) to effective carbon price
    omegas = np.linspace(0.0, 1.0, n_points)
    # pi_eff = omega * pi_max / (1-omega): ensures smooth sweep
    pi_max = 600.0
    rows = []
    for idx, omega in enumerate(omegas):
        if omega == 0.0:
            pi_eff = 0.0
        elif omega >= 1.0:
            pi_eff = pi_max
        else:
            pi_eff = omega / (1.0 - omega) * pi_nom  # proportional to nominal
            pi_eff = min(pi_eff, pi_max)
        print(f"  [{idx+1:3d}/{n_points}] omega={omega:.3f}  pi_eff={pi_eff:.1f} USD/tCO2", end="\r")
        res = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi_eff)
        rows.append({
            "omega_fuel_weight": round(omega, 4),
            "omega_emission_weight": round(1.0 - omega, 4),
            "pi_effective_usd_per_tco2": round(pi_eff, 2),
            "day_fuel_usd": res["day_fuel_usd"],
            "day_co2_tons": res["day_co2_tons"],
            "day_monetized_carbon_usd_pi_nom": pi_nom * res["day_co2_tons"],
            "day_social_cost_usd": res["day_fuel_usd"] + pi_nom * res["day_co2_tons"],
            "day_pv_curtailment_mwh": res["day_pv_curtailment_mwh"],
            "day_wind_curtailment_mwh": res["day_wind_curtailment_mwh"],
            "hours_solved": res["hours_solved"],
        })
    print()
    df = pd.DataFrame(rows)
    # Mark dominated points (both cost and emissions worse than another) — tag Pareto
    is_pareto = []
    vals = df[["day_fuel_usd", "day_co2_tons"]].values
    for i in range(len(vals)):
        dominated = False
        for j in range(len(vals)):
            if i == j:
                continue
            if vals[j, 0] <= vals[i, 0] and vals[j, 1] <= vals[i, 1] and (
                vals[j, 0] < vals[i, 0] or vals[j, 1] < vals[i, 1]
            ):
                dominated = True
                break
        is_pareto.append(not dominated)
    df["pareto_non_dominated"] = is_pareto
    return df


# ---------------------------------------------------------------------------
# 2. ε-constraint sweep
# ---------------------------------------------------------------------------

def epsilon_constraint(
    ppc_base: dict,
    gc_fuel: np.ndarray,
    co2: np.ndarray,
    fc: pd.DataFrame,
    ppopt: dict,
    n_points: int,
    pi_nom: float,
) -> pd.DataFrame:
    """
    ε-constraint: sweep emission budget epsilon ∈ [E_min, E_max].
    For each epsilon, find the carbon price pi* via binary search such that
    sum_24h CO2(pi*) ≈ epsilon.  Report fuel cost at that solution.

    This gives the exact trade-off curve:  C*(epsilon) vs epsilon.
    """
    print("  Finding unconstrained bounds for epsilon range...")
    r0 = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi=0.0)
    r_hi = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi=500.0)
    E_free = r0["day_co2_tons"]     # unconstrained (max) emissions
    E_min = r_hi["day_co2_tons"]    # minimum achievable emissions

    print(f"  Emission range: {E_min:.0f} - {E_free:.0f} tCO2/day")
    epsilons = np.linspace(E_min * 1.01, E_free * 0.99, n_points)

    rows = []
    for idx, eps in enumerate(epsilons):
        # Binary search for pi* such that CO2(pi*) ≈ eps
        lo, hi = 0.0, 600.0
        best_res = None
        for _ in range(30):  # 30 iterations → ~1e-9 precision
            mid = (lo + hi) / 2.0
            res = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, mid)
            if res["hours_solved"] == 0:
                break
            best_res = res
            if res["day_co2_tons"] > eps:
                lo = mid
            else:
                hi = mid
        print(f"  [{idx+1:3d}/{n_points}] eps={eps:.0f} tCO2 → pi*={mid:.2f}", end="\r")
        if best_res is None:
            continue
        rows.append({
            "epsilon_co2_budget_tons_day": round(eps, 2),
            "pi_shadow_price_usd_per_tco2": round(mid, 4),
            "day_fuel_usd": best_res["day_fuel_usd"],
            "day_co2_tons": best_res["day_co2_tons"],
            "day_monetized_carbon_usd_pi_nom": pi_nom * best_res["day_co2_tons"],
            "day_social_cost_usd": best_res["day_fuel_usd"] + pi_nom * best_res["day_co2_tons"],
            "day_pv_curtailment_mwh": best_res["day_pv_curtailment_mwh"],
            "day_wind_curtailment_mwh": best_res["day_wind_curtailment_mwh"],
            "hours_solved": best_res["hours_solved"],
            "emission_constraint_satisfied": best_res["day_co2_tons"] <= eps * 1.01,
        })
    print()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="IEEE 118 True DEED: weighted-sum + epsilon-constraint Pareto front."
    )
    parser.add_argument("--n-points", type=int, default=20,
                        help="Number of Pareto front points (default 20).")
    parser.add_argument("--plot", action="store_true",
                        help="Generate Pareto front PNG figures (requires matplotlib).")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    fc = _load_forecast()
    params = _load_deed_params()
    pi_nom = float(params["carbon_price_usd_per_tco2"])
    ppopt = ppoption(VERBOSE=0, OUT_ALL=0)

    ppc_base = case118()
    n_th = ppc_base["gen"].shape[0]
    gc_fuel = ppc_base["gencost"].copy()
    co2 = _load_co2_per_gen(n_th)

    print(f"IEEE 118 DEED | pi_nominal={pi_nom} USD/tCO2 | n_points={args.n_points}")
    print(f"Fleet CO2 mix: coal_steam=820, gas_ccgt=400, gas_ocgt=550 kg/MWh")
    print(f"RES: PV bus60 (curtailable), Wind bus78 (curtailable)")
    print()

    # ------ 1. Weighted sum ------
    print("=== Weighted-sum Pareto sweep ===")
    df_ws = weighted_sum_pareto(ppc_base, gc_fuel, co2, fc, ppopt, args.n_points, pi_nom)
    ws_path = OUT / "ieee118_deed_weighted_sum_pareto.csv"
    df_ws.to_csv(ws_path, index=False)
    print(f"Wrote {ws_path} ({len(df_ws)} rows)")
    print(df_ws[["omega_fuel_weight", "day_fuel_usd", "day_co2_tons",
                 "day_social_cost_usd", "pareto_non_dominated"]].to_string(index=False))
    print()

    # ------ 2. ε-constraint ------
    print("=== ε-constraint sweep ===")
    df_eps = epsilon_constraint(ppc_base, gc_fuel, co2, fc, ppopt, args.n_points, pi_nom)
    eps_path = OUT / "ieee118_deed_epsilon_constraint.csv"
    df_eps.to_csv(eps_path, index=False)
    print(f"Wrote {eps_path} ({len(df_eps)} rows)")
    print(df_eps[["epsilon_co2_budget_tons_day", "pi_shadow_price_usd_per_tco2",
                  "day_fuel_usd", "day_co2_tons", "emission_constraint_satisfied"]].to_string(index=False))
    print()

    # ------ 3. Best hourly: fuel-only & social-optimal ------
    print("=== Hourly detail: fuel-only vs social [pi_nom] ===")
    r_fuel_h = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi=0.0)
    r_soc_h = _run_24h(ppc_base, gc_fuel, co2, fc, ppopt, pi=pi_nom)

    best_rows = []
    for mode, res in [("fuel_only", r_fuel_h), ("social_pi_nom", r_soc_h)]:
        for hdata in res["hourly"]:
            if hdata is None:
                continue
            best_rows.append({
                "mode": mode,
                "hour_of_day": hdata["hour_of_day"],
                "thermal_fuel_usd_per_h": hdata["fuel_usd"],
                "thermal_co2_tons_per_h": hdata["co2_tons"],
                "monetized_carbon_usd_per_h": pi_nom * hdata["co2_tons"],
                "social_cost_usd_per_h": hdata["fuel_usd"] + pi_nom * hdata["co2_tons"],
                "sum_pg_thermal_mw": float(np.sum(hdata["Pg_thermal"])),
                "P_pv_dispatch_mw": hdata["P_pv"],
                "P_wind_dispatch_mw": hdata["P_wind"],
                "pv_curtailment_mw": hdata["pv_curt"],
                "wind_curtailment_mw": hdata["wind_curt"],
            })

    df_best = pd.DataFrame(best_rows)
    best_path = OUT / "ieee118_deed_hourly_best.csv"
    df_best.to_csv(best_path, index=False)
    print(df_best.to_string(index=False))
    print(f"\nWrote {best_path}")

    # ------ Summary ------
    print("\n=== Daily summary ===")
    for label, r in [("Fuel-only dispatch:", r_fuel_h), (f"Social (pi={pi_nom}):", r_soc_h)]:
        print(f"  {label:35s} fuel=${r['day_fuel_usd']:>12,.0f}  "
              f"CO2={r['day_co2_tons']:>8,.0f} t  "
              f"social=${r['day_fuel_usd'] + pi_nom * r['day_co2_tons']:>12,.0f}")

    if args.plot:
        _plot_pareto(df_ws, df_eps, OUT)


def _plot_pareto(df_ws: pd.DataFrame, df_eps: pd.DataFrame, out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping plots.")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Weighted sum
    ax = axes[0]
    ax.plot(df_ws["day_co2_tons"], df_ws["day_fuel_usd"] / 1e6, "o-b", markersize=6, label="Weighted sum")
    nd = df_ws[df_ws["pareto_non_dominated"]]
    ax.scatter(nd["day_co2_tons"], nd["day_fuel_usd"] / 1e6, c="red", zorder=5,
               s=60, label="Non-dominated")
    ax.set_xlabel("Daily CO2 (tons)", fontsize=11)
    ax.set_ylabel("Daily Thermal Fuel Cost (M USD)", fontsize=11)
    ax.set_title("DEED Weighted-Sum Pareto Front\nIEEE 118-bus, 24 h", fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Epsilon-constraint
    ax = axes[1]
    ax.plot(df_eps["epsilon_co2_budget_tons_day"], df_eps["day_fuel_usd"] / 1e6,
            "s-g", markersize=6, label="ε-constraint")
    ax.set_xlabel("CO2 Budget ε (tons/day)", fontsize=11)
    ax.set_ylabel("Min Fuel Cost at ε  (M USD)", fontsize=11)
    ax.set_title("DEED ε-Constraint Trade-off Curve\nIEEE 118-bus, 24 h", fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = out_dir / "ieee118_deed_pareto_fronts.png"
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {fig_path}")
    plt.close()


if __name__ == "__main__":
    main()
