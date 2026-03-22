# Scripts (IEEE 118 only)

Full map: **`docs/DATA_AND_RUNBOOK.md`**. Strategy: **`docs/STRATEGY.md`**.

## `ieee118_thermal_benchmark.py`

Aggregates **thermal** cost at **MATPOWER default** dispatch for all 54 generators.

```bash
cd /path/to/RMS
python3 scripts/ieee118_thermal_benchmark.py
```

Writes `outputs/ieee118_thermal_benchmark_summary.csv`.

**Inputs:** `datasets/ieee118/ieee118_gen_dispatch_default.csv`

## `ieee118_system_cost_benchmark.py`

**Thermal** (MATPOWER default fuel) + **RES variable O&M** on the 24 h forecast (full uptake).  
Reads `ieee118_res_economics.csv`. Does **not** solve joint DEED — see `docs/STRATEGY.md`.

```bash
python3 scripts/ieee118_system_cost_benchmark.py
```

Writes `outputs/ieee118_system_cost_benchmark.csv`.

## `ieee118_res_forecast_build.py`

Builds `datasets/ieee118/res_forecast_hourly_24h.csv` from archived PV logger + wind meteo CSVs. See **`docs/DATA_AND_RUNBOOK.md`**.

```bash
python3 scripts/ieee118_res_forecast_build.py
```

## `ieee118_vanilla_dcopf.py`

**PYPOWER** `rundcpf` on **`case118`**: minimize **thermal fuel** (quadratic `gencost`) with **DC** OPF; **fixed RES** at buses 60/78 from `res_forecast_hourly_24h.csv` (`Pmin=Pmax=P_avail`).

Requires **`pip install -r requirements.txt`** (NumPy 1.x + PYPOWER).

```bash
python3 scripts/ieee118_vanilla_dcopf.py
python3 scripts/ieee118_vanilla_dcopf.py --hour 12
```

Writes `outputs/ieee118_vanilla_dcopf_hourly_fuelopf.csv` (and `_socialopf` if `--carbon-price-for-opf`). Emissions columns + pinned deps: **`docs/DATA_AND_RUNBOOK.md` §8–9**.

Legacy microgrid / multi-feeder dispatch scripts were removed when the repo was consolidated to **IEEE 118 only**.
