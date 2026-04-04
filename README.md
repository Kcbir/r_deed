# RMS — Resource Management System

**Hierarchical DEED & ParetoFlow Optimization for Real-Time Grid Dispatch**

A research-grade power systems engine built on the IEEE 118-bus benchmark. RMS tackles the Dynamic Economic Emission Dispatch (DEED) problem as a two-layer optimization: a macroscopic Pareto search that maps the full fuel-vs-emission trade-off frontier, and a cooperative multi-agent reinforcement learning layer that executes real-time, constraint-satisfying dispatch decisions derived from that frontier.

For full technical write-up, methodology, and results, visit **[kabir.codes](https://kabir.codes)**.

---

## What it does

The core problem is non-trivial: power grid dispatch must simultaneously minimize fuel cost and carbon emissions, subject to hard physical constraints, across a continuous and non-convex operating space. Standard single-objective solvers collapse this trade-off into a scalar, discarding information. RMS does not.

**Macro layer (ParetoFlow / CSO).** A population-based Pareto search computes the exact non-dominated frontier across the cost-emission space. Operating points on this frontier are mathematically guaranteed to be Pareto-optimal — no improvement in one objective is possible without degrading the other.

**Micro layer (MARL).** A cooperative multi-agent RL system takes a selected Pareto target and translates it into per-generator dispatch setpoints. Convex relaxations of the AC power flow equations make the constraint set tractable; entropy regularization in the policy search prevents premature convergence and keeps routing decisions mathematically bounded.

---

## Repository layout

```
scripts/
  ieee118_deed.py               # Core DEED engine
  ieee118_macro_cso.py          # Macro-layer Pareto / CSO search
  ieee118_micro_marl.py         # Micro-layer cooperative MARL dispatch
  ieee118_validate_acdc.py      # AC/DC power flow validation
  ieee118_optimization_compare.py  # Solver benchmark comparisons
  ieee118_vanilla_dcopf.py      # Baseline DC-OPF reference
  ieee118_res_forecast_build.py # Renewable generation forecasting
  ieee118_system_cost_benchmark.py
  ieee118_thermal_benchmark.py
datasets/                       # IEEE 118-bus case data
outputs/                        # Pareto fronts, dispatch traces, plots
docs/
```

---

## Stack

| Library | Role |
|---|---|
| `PYPOWER 5.1.19` | AC/DC power flow solver, IEEE 118-bus case |
| `NumPy 1.26.4` | Numerical core, matrix operations |
| `SciPy 1.17.1` | Convex relaxations, optimization primitives |
| `pandas 3.0.1` | Dataset handling, results logging |

---

## Quickstart

```bash
git clone https://github.com/Kcbir/RMS.git
cd RMS
pip install -r requirements.txt

# Run the full DEED pipeline
python scripts/ieee118_deed.py

# Run the macro-layer Pareto search
python scripts/ieee118_macro_cso.py

# Run the micro-layer MARL dispatch
python scripts/ieee118_micro_marl.py
```

---

## Further reading

Architecture details, mathematical formulations, and experimental results are documented at **[kabir.codes](https://kabir.codes)**.

---

*Python 3.10+ recommended. Pinned dependencies in `requirements.txt` for full reproducibility.*