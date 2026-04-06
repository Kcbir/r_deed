# DEED — Dynamic Economic Emission Dispatch

**Hierarchical ParetoFlow Optimization | Multi-Agent RL | Convex Optimization | Pareto Search**

A Python-based optimization engine for solving the Dynamic Economic Emission Dispatch problem across multi-generator power grids, built on the IEEE 118-bus benchmark. It computes the full Pareto frontier of non-dominated operating solutions — giving operators a rigorous, continuous menu of cost-emission trade-offs rather than a single fixed answer.

Full technical write-up, methodology, and results at **[kabir.codes](https://kabir.codes)**.

---

## What it does

Grid dispatch has a fundamental tension: minimizing fuel cost and minimizing carbon emissions are competing objectives, and the feasible space is non-convex. Classical OPF ignores this entirely.

This system handles it in two cooperating layers.

**Macro layer.** A population-based Pareto search (ParetoFlow / CSO) computes the exact non-dominated frontier across the cost-emission space. Every point on this frontier is a mathematically valid operating configuration — no scalarization, no collapsed objectives.

**Micro layer.** A cooperative multi-agent reinforcement learning system takes a selected Pareto target from the macro layer and translates it into per-generator dispatch setpoints in real time. Convex relaxations keep the search tractable; entropy regularization keeps exploration honest.

The two layers compose into a clean hierarchical dispatch engine: the macro layer sets the strategic trade-off, the micro layer executes it.

---

## Repository layout

```
scripts/
  ieee118_deed.py                    # Core DEED engine
  ieee118_macro_cso.py               # Macro-layer Pareto / CSO search
  ieee118_micro_marl.py              # Micro-layer cooperative MARL dispatch
  ieee118_validate_acdc.py           # AC/DC power flow validation
  ieee118_optimization_compare.py    # Solver benchmark comparisons
  ieee118_vanilla_dcopf.py           # Baseline DC-OPF reference
  ieee118_res_forecast_build.py      # Renewable generation forecasting
  ieee118_system_cost_benchmark.py   # System cost benchmarking
  ieee118_thermal_benchmark.py       # Thermal generator benchmarking
datasets/ieee118/                    # IEEE 118-bus case data and generator parameters
requirements.txt                     # Pinned dependencies
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

python scripts/ieee118_deed.py
python scripts/ieee118_macro_cso.py
python scripts/ieee118_micro_marl.py
```

Python 3.10+ recommended.

---

More details at **[kabir.codes](https://kabir.codes)**.