#!/usr/bin/env python3
"""
IEEE 118 Optimization Comparison
=================================
Loads outputs from:
  1. Vanilla DC-OPF (ieee118_vanilla_dcopf.py)
  2. CSO macro-DEED (ieee118_macro_cso.py)
  3. MARL micro-DEED (ieee118_micro_marl.py)

Produces a side-by-side summary table and figures.

Usage
-----
  python3 scripts/ieee118_optimization_compare.py
  python3 scripts/ieee118_optimization_compare.py --plot
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT  = ROOT / "outputs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_vanilla() -> dict | None:
    """Load best available vanilla DC-OPF summary (fuel-only or social)."""
    for fname in [
        "ieee118_vanilla_dcopf_summary_fuelopf.csv",
        "ieee118_vanilla_dcopf_summary_socialopf.csv",
    ]:
        f = OUT / fname
        if f.exists():
            df = pd.read_csv(f)
            return {"label": "Vanilla DC-OPF", "_path": str(f), "_df": df}
    return None


def _load_cso() -> dict | None:
    """Load CSO Pareto summary and pick the 50/50 balanced point."""
    f = OUT / "ieee118_cso_pareto.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    # Select omega closest to 0.5 (balanced)
    df["omega_dist"] = (df["omega"] - 0.5).abs()
    row = df.loc[df["omega_dist"].idxmin()]
    return {"label": "CSO Macro (ω=0.5)", "_path": str(f), "_row": row}


def _load_cso_zone() -> pd.DataFrame | None:
    f = OUT / "ieee118_cso_zone_summary.csv"
    return pd.read_csv(f) if f.exists() else None


def _load_marl() -> dict | None:
    f = OUT / "ieee118_marl_eval_hourly.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    return {"label": "MARL Micro", "_path": str(f), "_df": df}


def _load_marl_zone() -> pd.DataFrame | None:
    f = OUT / "ieee118_marl_zone_summary.csv"
    return pd.read_csv(f) if f.exists() else None


# ---------------------------------------------------------------------------
# Build comparison table
# ---------------------------------------------------------------------------

def build_summary(vanilla, cso, marl, pi_nom: float = 85.0) -> pd.DataFrame:
    rows = []

    if vanilla:
        v_df = vanilla["_df"]
        v_fuel  = float(v_df["thermal_fuel_usd_per_day"].iloc[0])
        v_co2   = float(v_df["thermal_tons_co2_per_day"].iloc[0])
        v_social = float(v_df["thermal_social_usd_per_day_fuel_plus_monetized"].iloc[0])
        rows.append({
            "Method": "Vanilla DC-OPF",
            "Daily Fuel (USD)": v_fuel,
            "Daily CO2 (t)":    v_co2,
            "Social Cost (USD)": v_social,
            "Avg Hourly Imbalance (MW)": 0.0,
        })

    if cso:
        r = cso["_row"]
        c_fuel   = float(r["day_fuel_usd"])
        c_co2    = float(r["day_co2_tons"])
        c_social = float(r["day_social_usd"]) if "day_social_usd" in r else c_fuel + pi_nom * c_co2
        rows.append({
            "Method": "CSO Macro (ω≈0.5)",
            "Daily Fuel (USD)": c_fuel,
            "Daily CO2 (t)":    c_co2,
            "Social Cost (USD)": c_social,
            "Avg Hourly Imbalance (MW)": 0.0,   # CSO uses projection → 0
        })

    if marl:
        m_df   = marl["_df"]
        m_fuel = float(m_df["fuel_usd"].sum())
        m_co2  = float(m_df["co2_tons"].sum())
        m_social = m_fuel + pi_nom * m_co2
        m_imb  = float(m_df["imbalance_mw"].mean())
        rows.append({
            "Method": "MARL Micro",
            "Daily Fuel (USD)": m_fuel,
            "Daily CO2 (t)":    m_co2,
            "Social Cost (USD)": m_social,
            "Avg Hourly Imbalance (MW)": m_imb,
        })

    df = pd.DataFrame(rows)
    return df


def build_zone_comparison(cso_zone: pd.DataFrame | None, marl_zone: pd.DataFrame | None) -> pd.DataFrame | None:
    rows = []
    for zone_id in [1, 2, 3]:
        zone_name = ["Thermal","PV","Wind"][zone_id-1]
        row = {"zone": zone_id, "zone_name": zone_name}
        if cso_zone is not None:
            cz = cso_zone[cso_zone["zone"] == zone_id]
            if not cz.empty:
                row["cso_fuel_usd"] = float(cz["day_fuel_usd"].iloc[0])
                row["cso_co2_tons"] = float(cz["day_co2_tons"].iloc[0])
                row["cso_pg_mwh"]   = float(cz["day_pg_mwh"].iloc[0])
        if marl_zone is not None:
            mz = marl_zone[marl_zone["zone"] == zone_id]
            if not mz.empty:
                row["marl_fuel_usd"] = float(mz["day_fuel_usd"].iloc[0])
                row["marl_co2_tons"] = float(mz["day_co2_tons"].iloc[0])
                row["marl_pg_mwh"]   = float(mz["day_pg_mwh"].iloc[0])
        rows.append(row)
    return pd.DataFrame(rows) if rows else None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Vanilla / CSO / MARL dispatch results"
    )
    parser.add_argument("--pi", type=float, default=85.0,
                        help="Carbon price USD/tCO2 for social cost (default 85)")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()

    vanilla   = _load_vanilla()
    cso       = _load_cso()
    marl      = _load_marl()
    cso_zone  = _load_cso_zone()
    marl_zone = _load_marl_zone()

    available = [x["label"] for x in [vanilla, cso, marl] if x is not None]
    print(f"\nAvailable results: {available}")

    if not available:
        print("No outputs found. Run the component scripts first:\n"
              "  python3 scripts/ieee118_vanilla_dcopf.py\n"
              "  python3 scripts/ieee118_macro_cso.py\n"
              "  python3 scripts/ieee118_micro_marl.py")
        return

    summary = build_summary(vanilla, cso, marl, args.pi)
    zone_df  = build_zone_comparison(cso_zone, marl_zone)

    print("\n" + "=" * 80)
    print("             IEEE 118 — Dispatch Optimization Comparison")
    print("=" * 80)
    print(summary.to_string(index=False, float_format=lambda x: f"{x:,.0f}"))

    if zone_df is not None and not zone_df.empty:
        print("\n--- Per-Zone Breakdown ---")
        print(zone_df.to_string(index=False))

    # Save
    summary_path = OUT / "ieee118_optimization_comparison.csv"
    summary.to_csv(summary_path, index=False)
    print(f"\nWrote {summary_path}")

    if zone_df is not None:
        zone_path = OUT / "ieee118_zone_comparison.csv"
        zone_df.to_csv(zone_path, index=False)
        print(f"Wrote {zone_path}")

    if args.plot and len(available) >= 2:
        _plot(summary, zone_df, OUT, args.pi)


def _plot(summary: pd.DataFrame, zone_df: pd.DataFrame | None, out_dir: Path, pi: float) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    n = len(summary)
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"][:n]
    methods = summary["Method"].tolist()

    fig, axes = plt.subplots(1, 3, figsize=(16, 6))

    ax = axes[0]
    vals = summary["Daily Fuel (USD)"].values / 1e6
    bars = ax.bar(methods, vals, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_ylabel("Daily Fuel Cost (M USD)")
    ax.set_title("Fuel Cost Comparison")
    ax.grid(True, axis="y", alpha=0.3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v + 0.01, f"${v:.2f}M",
                ha="center", va="bottom", fontsize=9)

    ax = axes[1]
    vals = summary["Daily CO2 (t)"].values / 1000.0
    bars = ax.bar(methods, vals, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_ylabel("Daily CO₂ (kt)")
    ax.set_title("CO₂ Emissions Comparison")
    ax.grid(True, axis="y", alpha=0.3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v + 0.3, f"{v:.1f}kt",
                ha="center", va="bottom", fontsize=9)

    ax = axes[2]
    vals = summary["Social Cost (USD)"].values / 1e6
    bars = ax.bar(methods, vals, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_ylabel(f"Social Cost (M USD)  @${pi}/tCO₂")
    ax.set_title("Social Cost Comparison")
    ax.grid(True, axis="y", alpha=0.3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v + 0.01, f"${v:.2f}M",
                ha="center", va="bottom", fontsize=9)

    plt.suptitle("IEEE 118-Bus — Dispatch Optimization Method Comparison\n(May 13, 2025 synthetic forecast)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout()

    fig_path = out_dir / "ieee118_optimization_comparison.png"
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {fig_path}")
    plt.close()


if __name__ == "__main__":
    main()
