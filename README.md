# RMS — IEEE 118 DEED / OPF baseline

This repository is consolidated on **IEEE 118-bus** data and scripts only.

## Layout

| Path | Purpose |
|------|---------|
| `datasets/ieee118/` | Network (CDF/PSP), `gencost`, default thermal dispatch; **RES:** `ieee118_res_buses.csv`, `res_forecast_hourly_24h.csv` |
| `scripts/ieee118_thermal_benchmark.py` | Writes `outputs/ieee118_thermal_benchmark_summary.csv` |
| `scripts/ieee118_res_forecast_build.py` | Regenerates `res_forecast_hourly_24h.csv` from `archive/` |
| `scripts/ieee118_system_cost_benchmark.py` | Thermal + RES O&M **component** costs → `outputs/ieee118_system_cost_benchmark.csv` |
| `scripts/ieee118_vanilla_dcopf.py` | **Vanilla DC OPF** (min fuel, PYPOWER) + fixed RES → `outputs/ieee118_vanilla_dcopf_*.csv` |
| `requirements.txt` | **NumPy 1.x + PYPOWER** (needed for vanilla DC OPF) |
| `docs/` | **`STRATEGY.md`** (why / DEED story), **`DATA_AND_RUNBOOK.md`** (datasets, scripts, outputs) — **only two** long-form docs |
| `archive/non_ieee118_raw/` | Raw PV/meteo CSVs used to **build** the RES forecast (see docs) |

## Quick run

```bash
pip install -r requirements.txt
python3 scripts/ieee118_thermal_benchmark.py
python3 scripts/ieee118_res_forecast_build.py
python3 scripts/ieee118_system_cost_benchmark.py
python3 scripts/ieee118_vanilla_dcopf.py
python3 scripts/ieee118_vanilla_dcopf.py --carbon-price-for-opf 85   # optional: carbon in objective
git tag rms-v1-baseline   # after a reproducible commit (optional)
```

## Documentation (long-form)

- **`docs/STRATEGY.md`** — objectives, scale, economics story.
- **`docs/DATA_AND_RUNBOOK.md`** — every dataset, script, output, tuning knobs.

## Citation

- IEEE 118: UW / IEEE test case archives; MATPOWER `case118.m` for default dispatch and `gencost`.
