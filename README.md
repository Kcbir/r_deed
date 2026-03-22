# RMS — IEEE 118 DEED / OPF baseline

This repository is consolidated on **IEEE 118-bus** data and scripts only.

## Layout

| Path | Purpose |
|------|---------|
| `datasets/ieee118/` | Network (CDF/PSP), `gencost`, default thermal dispatch; **RES:** `ieee118_res_buses.csv`, `res_forecast_hourly_24h.csv` |
| `scripts/ieee118_thermal_benchmark.py` | Writes `outputs/ieee118_thermal_benchmark_summary.csv` |
| `scripts/ieee118_res_forecast_build.py` | Regenerates `res_forecast_hourly_24h.csv` from `archive/` |
| `scripts/ieee118_system_cost_benchmark.py` | Thermal + RES O&M **component** costs → `outputs/ieee118_system_cost_benchmark.csv` |
| `scripts/ieee118_vanilla_dcopf.py` | **Vanilla DC OPF** (min fuel, `rundcopf`) + curtailable RES → `outputs/ieee118_vanilla_dcopf_*.csv` |
| `scripts/ieee118_deed.py` | **True DEED**: weighted-sum Pareto + ε-constraint trade-off → `outputs/ieee118_deed_*.csv` |
| `scripts/ieee118_validate_acdc.py` | **Sanity checks** + AC vs DC OPF comparison → `outputs/ieee118_acdc_*.csv` |
| `requirements.txt` | **NumPy 1.x + PYPOWER** (needed for DC OPF) |
| `docs/` | **`STRATEGY.md`** (why / DEED story), **`DATA_AND_RUNBOOK.md`** (datasets, scripts, outputs) |
| `archive/non_ieee118_raw/` | Raw PV/meteo CSVs used to **build** the RES forecast (see docs) |

## Quick run

```bash
conda activate aniate   # Python 3.10, NumPy 1.26.4, PYPOWER 5.1.19
python3 scripts/ieee118_thermal_benchmark.py
python3 scripts/ieee118_res_forecast_build.py
python3 scripts/ieee118_system_cost_benchmark.py
python3 scripts/ieee118_vanilla_dcopf.py
python3 scripts/ieee118_deed.py --n-points 20 --plot
python3 scripts/ieee118_validate_acdc.py --plot
git tag rms-v2-deed   # after a reproducible commit
```

> **Environment:** Use `conda activate aniate` (not base). Base conda has NumPy 2.x which is incompatible with PYPOWER.

## Key results (May 13, 24 h, IEEE 118-bus)

| Mode | Fuel $/day | CO₂ t/day | Notes |
|------|-----------|-----------|-------|
| MATPOWER default | ~$3,152,000 | ~95,000 | Fixed dispatch baseline |
| Fuel-only OPF (π=0) | $2,942,000 | 79,498 | 7% cheaper than default |
| Social OPF (π=$85/tCO₂) | $3,955,000 | 54,678 | 31% less CO₂ |
| AC eval (at DC dispatch) | $3,075,000 | 82,122 | DC undercounts by ~4.5% (133 MW losses) |

## Documentation (long-form)

- **`docs/STRATEGY.md`** — objectives, scale, economics story.
- **`docs/DATA_AND_RUNBOOK.md`** — every dataset, script, output, tuning knobs.

## Citation

- IEEE 118: UW / IEEE test case archives; MATPOWER `case118.m` for default dispatch and `gencost`.
