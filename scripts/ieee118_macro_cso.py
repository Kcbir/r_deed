#!/usr/bin/env python3
"""
IEEE 118 Macro-Level DEED — Chameleon Swarm Optimization (CSO).

Zones
-----
  Zone 1 (Thermal)  : buses  1–49   | 21 gens, no RES
  Zone 2 (PV)       : buses 50–73   | 12 gens + PV  @ bus 60  (150 MW)
  Zone 3 (Wind)     : buses 74–118  | 21 gens + wind @ bus 78 (400 MW)

CSO Algorithm
-------------
Chameleon Swarm Optimization mimics chameleon foraging & colour-change behaviour:
  • Population of N chameleons, each =  a candidate Pg dispatch vector (54 dims).
  • Four phases each generation:
      1. Exploration (local branch foraging)  — random walk near personal best.
      2. Exploitation (directed to food)      — move towards global best g_best.
      3. Social rotation (colour change)      — chameleon rotates towards zone leader.
      4. Lévy flight escape                   — occasional long jumps to escape local optima.
  • Fitness = weighted sum: w_f * C_fuel + (1-w_f) * pi * E_co2  (daily totals).

For each omega ∈ {0, 0.25, 0.5, 0.75, 1.0} (fuel weight), solve the 24-h horizon:
  Each hour: CSO finds optimal Pg for all 54 thermal generators given that hour's
  RES availability.  Power balance enforced by projecting onto feasible set.

Outputs
-------
  outputs/ieee118_cso_pareto.csv           — per-omega daily Pareto point
  outputs/ieee118_cso_hourly_detail.csv    — per-hour dispatch at each omega
  outputs/ieee118_cso_zone_summary.csv     — per-zone fuel/CO2 breakdown (at omega=1.0)

Usage
-----
  python3 scripts/ieee118_macro_cso.py
  python3 scripts/ieee118_macro_cso.py --pop 30 --iters 100 --n-omega 9 --plot
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import math
import numpy as np
import pandas as pd
from pypower.api import case118
from pypower.idx_gen import PG, PMAX, PMIN
from pypower.totcost import totcost

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT  = ROOT / "outputs"

# ---------------------------------------------------------------------------
# Zone map
# ---------------------------------------------------------------------------
ZONES = {
    1: {"name": "Thermal",  "bus_min": 1,  "bus_max": 49},
    2: {"name": "PV",       "bus_min": 50, "bus_max": 73},
    3: {"name": "Wind",     "bus_min": 74, "bus_max": 118},
}

def _bus_to_zone(bus_id: int) -> int:
    b = int(bus_id)
    if b <= 49:  return 1
    if b <= 73:  return 2
    return 3


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_system() -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Returns (gen_pmin, gen_pmax, gencost, total_load_mw) for the 54 thermal gens."""
    ppc = case118()
    gen  = ppc["gen"]
    gc   = ppc["gencost"]
    load = float(ppc["bus"][:, 2].sum())
    pmin = gen[:, PMIN].copy()
    pmax = gen[:, PMAX].copy()
    return pmin, pmax, gc, load


def _load_co2() -> np.ndarray:
    df = pd.read_csv(DATA / "ieee118_thermal_co2_kg_per_mwh.csv").sort_values("gen_idx")
    return df["co2_kg_per_mwh"].values.astype(float)


def _load_forecast() -> pd.DataFrame:
    return pd.read_csv(DATA / "res_forecast_hourly_24h.csv")


def _load_params() -> dict[str, float]:
    p = pd.read_csv(DATA / "ieee118_deed_params.csv")
    return dict(zip(p["param"], p["value"].astype(float)))


# ---------------------------------------------------------------------------
# Fitness (single hour)
# ---------------------------------------------------------------------------

def _fitness_hour(
    Pg: np.ndarray,          # shape (n_thermal,)
    gc: np.ndarray,
    co2: np.ndarray,
    pi: float,               # effective carbon price (USD/tCO2)
    omega: float,            # fuel weight [0,1]
) -> float:
    """Weighted-sum DEED objective for one hour (one dispatch vector)."""
    tc    = totcost(gc, Pg)
    fuel  = float(np.sum(tc))
    emis  = float(np.sum(co2 * Pg) / 1000.0)          # tCO2/h
    if omega == 1.0:
        return fuel
    if omega == 0.0:
        return pi * emis
    return omega * fuel + (1.0 - omega) * pi * emis


# ---------------------------------------------------------------------------
# Feasibility projection
# ---------------------------------------------------------------------------

def _project(Pg: np.ndarray, pmin: np.ndarray, pmax: np.ndarray,
             demand_mw: float, res_mw: float) -> np.ndarray:
    """
    Clip Pg to [Pmin, Pmax] and rescale to meet net load = demand - res.
    Uses proportional scaling so dispatch stays within bounds.
    """
    net = max(demand_mw - res_mw, 0.0)
    Pg  = np.clip(Pg, pmin, pmax)
    total = Pg.sum()
    if total < 1e-3:
        # distribute over available capacity proportionally to Pmax
        weights = pmax / pmax.sum()
        Pg = weights * net
        Pg = np.clip(Pg, pmin, pmax)
        return Pg
    # Scale to meet net load
    scale = net / total
    Pg_scaled = Pg * scale
    Pg_scaled = np.clip(Pg_scaled, pmin, pmax)
    # Small residual correction on slack (gen with most headroom)
    residual = net - Pg_scaled.sum()
    headroom_up   = pmax - Pg_scaled
    headroom_down = Pg_scaled - pmin
    if residual > 0:
        idx = int(np.argmax(headroom_up))
        Pg_scaled[idx] = min(pmax[idx], Pg_scaled[idx] + residual)
    elif residual < 0:
        idx = int(np.argmax(headroom_down))
        Pg_scaled[idx] = max(pmin[idx], Pg_scaled[idx] + residual)
    return np.clip(Pg_scaled, pmin, pmax)


# ---------------------------------------------------------------------------
# CSO core (one hour, one omega)
# ---------------------------------------------------------------------------

def _levy(size: int, beta: float = 1.5) -> np.ndarray:
    """Mantegna's algorithm for Lévy flight step."""
    sigma = (
        math.gamma(1 + beta) * np.sin(np.pi * beta / 2)
        / (math.gamma((1 + beta) / 2) * beta * 2 ** ((beta - 1) / 2))
    ) ** (1.0 / beta)
    u = np.random.randn(size) * sigma
    v = np.abs(np.random.randn(size))
    return u / (v ** (1.0 / beta))


def _cso_hour(
    pmin_th: np.ndarray,
    pmax_th: np.ndarray,
    gc: np.ndarray,
    co2: np.ndarray,
    demand_mw: float,
    res_mw: float,
    pi: float,
    omega: float,
    n_pop: int,
    n_iter: int,
    seed: int | None = None,
) -> tuple[np.ndarray, float]:
    """
    Run CSO for one hour.  Returns (best_Pg, best_fitness).
    """
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()

    n = len(pmin_th)
    net = max(demand_mw - res_mw, 0.0)

    # ── Initialise population ──────────────────────────────────────
    # Random Pg within [Pmin, Pmax], then project to balance
    pop    = rng.uniform(pmin_th, pmax_th, (n_pop, n))  # (N, n)
    pop    = np.array([_project(p, pmin_th, pmax_th, demand_mw, res_mw) for p in pop])
    fit    = np.array([_fitness_hour(p, gc, co2, pi, omega) for p in pop])

    pbest  = pop.copy()                  # personal bests
    pbest_fit = fit.copy()

    gbest_idx  = int(np.argmin(fit))
    gbest      = pop[gbest_idx].copy()
    gbest_fit  = float(fit[gbest_idx])

    # Zone leader = best agent within each zone for generators in that zone
    gen_zones  = np.array([_bus_to_zone(b) for b in
                           [case118()["gen"][i, 0] for i in range(n)]])

    # CSO hyper-params
    alpha  = 0.5   # exploration inertia
    beta_c = 1.5   # Lévy exponent
    p_levy = 0.1   # probability of Lévy escape

    for t in range(n_iter):
        w = 1.0 - 0.5 * t / n_iter   # linearly decreasing inertia

        for idx in range(n_pop):
            x = pop[idx].copy()

            # ── Phase 1: Exploration (local branch foraging) ──────
            r1 = rng.random(n)
            x_exp = x + w * r1 * (pbest[idx] - x) + alpha * rng.standard_normal(n) * (pmax_th - pmin_th) * 0.05

            # ── Phase 2: Exploitation (move to global best) ───────
            r2 = rng.random(n)
            x_exp = x_exp + (1.0 - w) * r2 * (gbest - x_exp)

            # ── Phase 3: Zone-leader social rotation ─────────────
            # Each generator dimension is nudged towards its zone leader
            for z in [1, 2, 3]:
                mask_z = gen_zones == z
                if mask_z.sum() == 0:
                    continue
                # zone leader = best pbest among agents in this zone (by zone-sub-fitness)
                zone_fits = np.array([
                    _fitness_hour(pbest[j][mask_z] if False else pbest[j],
                                  gc, co2, pi, omega)
                    for j in range(n_pop)
                ])
                z_leader_idx = int(np.argmin(zone_fits))
                z_leader     = pbest[z_leader_idx]
                r3 = rng.random(n)
                x_exp[mask_z] += 0.3 * r3[mask_z] * (z_leader[mask_z] - x_exp[mask_z])

            # ── Phase 4: Lévy flight escape ───────────────────────
            if rng.random() < p_levy:
                step = _levy(n, beta_c)
                x_exp += step * (gbest - x_exp) * 0.01 * (pmax_th - pmin_th)

            # ── Project & evaluate ────────────────────────────────
            x_new = _project(x_exp, pmin_th, pmax_th, demand_mw, res_mw)
            f_new = _fitness_hour(x_new, gc, co2, pi, omega)

            pop[idx]  = x_new
            fit[idx]  = f_new

            if f_new < pbest_fit[idx]:
                pbest[idx]     = x_new.copy()
                pbest_fit[idx] = f_new

            if f_new < gbest_fit:
                gbest     = x_new.copy()
                gbest_fit = f_new

    return gbest, gbest_fit


# ---------------------------------------------------------------------------
# Run 24 h at one omega
# ---------------------------------------------------------------------------

def _run_24h_cso(
    pmin_th: np.ndarray,
    pmax_th: np.ndarray,
    gc: np.ndarray,
    co2: np.ndarray,
    fc: pd.DataFrame,
    demand_mw: float,
    pi_nom: float,
    omega: float,
    n_pop: int,
    n_iter: int,
    verbose: bool = True,
) -> dict:
    """Solve all 24 hours.  Returns daily totals + hourly list."""
    if omega == 1.0:
        pi_eff = 0.0
    elif omega == 0.0:
        pi_eff = pi_nom * 10.0    # strong carbon weight
    else:
        pi_eff = (1.0 - omega) / omega * pi_nom

    day_fuel = day_co2 = day_pv_curt = day_wind_curt = 0.0
    hourly   = []

    ppc_gen  = case118()["gen"]
    gen_zones = np.array([_bus_to_zone(b) for b in ppc_gen[:, 0]])

    for _, row in fc.iterrows():
        hod   = int(row["hour_of_day"])
        p_pv  = float(row["p_pv_mw"])
        p_wd  = float(row["p_wind_mw"])
        res   = p_pv + p_wd

        best_pg, best_fit = _cso_hour(
            pmin_th, pmax_th, gc, co2,
            demand_mw, res, pi_eff, omega,
            n_pop, n_iter, seed=hod * 1000 + int(omega * 100)
        )

        # Post-metrics (always in fuel-only terms for comparison)
        tc   = totcost(gc, best_pg)
        fuel = float(np.sum(tc))
        co2h = float(np.sum(co2 * best_pg) / 1000.0)
        pg_sum = float(best_pg.sum())
        pv_disp  = min(p_pv,  max(0.0, demand_mw - pg_sum))
        wd_disp  = min(p_wd,  max(0.0, demand_mw - pg_sum - pv_disp))
        pv_curt  = p_pv  - pv_disp
        wd_curt  = p_wd  - wd_disp

        day_fuel     += fuel
        day_co2      += co2h
        day_pv_curt  += pv_curt
        day_wind_curt+= wd_curt

        # Per-zone breakdown
        z_fuel = {z: float(np.sum(totcost(gc, best_pg)[gen_zones == z])) for z in [1,2,3]}
        z_co2  = {z: float(np.sum(co2[gen_zones == z] * best_pg[gen_zones == z]) / 1000.0)
                  for z in [1,2,3]}
        z_pg   = {z: float(best_pg[gen_zones == z].sum()) for z in [1,2,3]}

        hourly.append({
            "hour_of_day": hod, "omega": omega, "pi_eff": pi_eff,
            "thermal_fuel_usd": fuel, "thermal_co2_tons": co2h,
            "thermal_pg_mw": pg_sum,
            "p_pv_available_mw": p_pv, "p_wind_available_mw": p_wd,
            "pv_curtailment_mw": pv_curt, "wind_curtailment_mw": wd_curt,
            "zone1_fuel_usd": z_fuel[1], "zone2_fuel_usd": z_fuel[2], "zone3_fuel_usd": z_fuel[3],
            "zone1_co2_tons": z_co2[1],  "zone2_co2_tons": z_co2[2],  "zone3_co2_tons": z_co2[3],
            "zone1_pg_mw": z_pg[1],      "zone2_pg_mw": z_pg[2],      "zone3_pg_mw": z_pg[3],
        })
        if verbose:
            print(f"  ω={omega:.2f} h={hod:2d}: fuel={fuel:>10,.0f} co2={co2h:>7.1f}t "
                  f"Z1={z_pg[1]:.0f}/{z_pg[2]:.0f}/{z_pg[3]:.0f} MW "
                  f"PV_curt={pv_curt:.1f} WD_curt={wd_curt:.1f}")

    social = day_fuel + pi_nom * day_co2
    return {
        "omega": omega, "pi_eff": pi_eff,
        "day_fuel_usd": day_fuel, "day_co2_tons": day_co2,
        "day_social_usd": social,
        "day_pv_curtailment_mwh": day_pv_curt,
        "day_wind_curtailment_mwh": day_wind_curt,
        "hourly": hourly,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="IEEE 118 Macro DEED — Chameleon Swarm Optimization (3-zone)"
    )
    parser.add_argument("--pop",     type=int,   default=20,
                        help="Swarm population size (default 20)")
    parser.add_argument("--iters",   type=int,   default=80,
                        help="Iterations per hour (default 80)")
    parser.add_argument("--n-omega", type=int,   default=5,
                        help="Number of omega trade-off points (default 5)")
    parser.add_argument("--plot",    action="store_true",
                        help="Generate figures (requires matplotlib)")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    pmin, pmax, gc, demand = _load_system()
    co2  = _load_co2()
    fc   = _load_forecast()
    prms = _load_params()
    pi_nom = float(prms["carbon_price_usd_per_tco2"])

    n_gen = len(pmin)
    ppc_gen = case118()["gen"]

    print("=" * 70)
    print(f"IEEE 118 Macro DEED — Chameleon Swarm Optimization")
    print(f"Zones: Z1(thermal, buses 1-49) | Z2(PV, buses 50-73) | Z3(wind, buses 74-118)")
    print(f"pop={args.pop}  iters={args.iters}  n_omega={args.n_omega}  pi_nom={pi_nom} USD/tCO2")
    print(f"54 thermal gens | demand={demand:.0f} MW | RES: PV(bus60,150MW) + Wind(bus78,400MW)")
    print("=" * 70)

    omegas = np.linspace(0.0, 1.0, args.n_omega)
    pareto_rows = []
    all_hourly  = []
    t0 = time.time()

    for omega in omegas:
        print(f"\n--- omega={omega:.3f} (fuel weight) ---")
        result = _run_24h_cso(pmin, pmax, gc, co2, fc, demand, pi_nom, omega,
                              args.pop, args.iters, verbose=True)
        pareto_rows.append({
            "omega": omega,
            "day_fuel_usd": result["day_fuel_usd"],
            "day_co2_tons": result["day_co2_tons"],
            "day_social_usd": result["day_social_usd"],
            "day_pv_curtailment_mwh": result["day_pv_curtailment_mwh"],
            "day_wind_curtailment_mwh": result["day_wind_curtailment_mwh"],
            "pi_eff": result["pi_eff"],
        })
        all_hourly.extend(result["hourly"])

    elapsed = time.time() - t0
    print(f"\nCSO completed in {elapsed:.1f}s")

    # Save
    df_pareto = pd.DataFrame(pareto_rows)
    df_hourly = pd.DataFrame(all_hourly)

    p_path = OUT / "ieee118_cso_pareto.csv"
    h_path = OUT / "ieee118_cso_hourly_detail.csv"
    df_pareto.to_csv(p_path, index=False)
    df_hourly.to_csv(h_path, index=False)

    # Zone breakdown at omega=1 (fuel-only)
    fuel_only_hourly = df_hourly[df_hourly["omega"] == 1.0]
    if len(fuel_only_hourly) == 0:
        fuel_only_hourly = df_hourly[df_hourly["omega"] == df_hourly["omega"].max()]
    zone_summary = pd.DataFrame([{
        "zone": 1, "zone_name": "Thermal",
        "day_fuel_usd": fuel_only_hourly["zone1_fuel_usd"].sum(),
        "day_co2_tons": fuel_only_hourly["zone1_co2_tons"].sum(),
        "day_pg_mwh":   fuel_only_hourly["zone1_pg_mw"].sum(),
    }, {
        "zone": 2, "zone_name": "PV",
        "day_fuel_usd": fuel_only_hourly["zone2_fuel_usd"].sum(),
        "day_co2_tons": fuel_only_hourly["zone2_co2_tons"].sum(),
        "day_pg_mwh":   fuel_only_hourly["zone2_pg_mw"].sum(),
    }, {
        "zone": 3, "zone_name": "Wind",
        "day_fuel_usd": fuel_only_hourly["zone3_fuel_usd"].sum(),
        "day_co2_tons": fuel_only_hourly["zone3_co2_tons"].sum(),
        "day_pg_mwh":   fuel_only_hourly["zone3_pg_mw"].sum(),
    }])
    z_path = OUT / "ieee118_cso_zone_summary.csv"
    zone_summary.to_csv(z_path, index=False)

    print(f"\nWrote {p_path}")
    print(f"Wrote {h_path}")
    print(f"Wrote {z_path}")

    print("\n=== Pareto Front (CSO) ===")
    print(df_pareto.to_string(index=False))
    print("\n=== Zone Summary at omega=1.0 (Fuel-only) ===")
    print(zone_summary.to_string(index=False))

    if args.plot:
        _plot(df_pareto, df_hourly, OUT)


def _plot(df_p: pd.DataFrame, df_h: pd.DataFrame, out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Pareto front
    ax = axes[0]
    ax.plot(df_p["day_co2_tons"] / 1e3, df_p["day_fuel_usd"] / 1e6,
            "b-o", markersize=8, label="CSO Pareto")
    for _, row in df_p.iterrows():
        ax.annotate(f"ω={row['omega']:.2f}",
                    (row["day_co2_tons"]/1e3, row["day_fuel_usd"]/1e6),
                    textcoords="offset points", xytext=(5, 4), fontsize=7)
    ax.set_xlabel("Daily CO₂ (kt/day)")
    ax.set_ylabel("Daily Fuel Cost (M USD/day)")
    ax.set_title("CSO Pareto Front\n3-Zone IEEE 118")
    ax.legend(); ax.grid(True, alpha=0.3)

    # Per-zone generation stacked bar (omega=1)
    ax = axes[1]
    h1 = df_h[df_h["omega"] == df_h["omega"].max()].sort_values("hour_of_day")
    hours = h1["hour_of_day"].values
    ax.bar(hours, h1["zone1_pg_mw"], label="Z1 Thermal", color="#d62728")
    ax.bar(hours, h1["zone2_pg_mw"], bottom=h1["zone1_pg_mw"], label="Z2 + PV", color="#ff7f0e")
    ax.bar(hours, h1["zone3_pg_mw"],
           bottom=h1["zone1_pg_mw"].values + h1["zone2_pg_mw"].values,
           label="Z3 + Wind", color="#2ca02c")
    ax.set_xlabel("Hour of Day"); ax.set_ylabel("Generation (MW)")
    ax.set_title("Zonal Dispatch (ω=1.0 fuel-only)\nCSO")
    ax.legend(); ax.grid(True, alpha=0.2)

    # CO2 per hour per omega
    ax = axes[2]
    for om in sorted(df_h["omega"].unique()):
        sub = df_h[df_h["omega"] == om].sort_values("hour_of_day")
        ax.plot(sub["hour_of_day"], sub["thermal_co2_tons"],
                label=f"ω={om:.2f}", marker="o", markersize=4)
    ax.set_xlabel("Hour of Day"); ax.set_ylabel("Thermal CO₂ (t/h)")
    ax.set_title("Hourly CO₂ vs Trade-off Weight\nCSO")
    ax.legend(fontsize=7); ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = out_dir / "ieee118_cso_results.png"
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {fig_path}")
    plt.close()


if __name__ == "__main__":
    main()
