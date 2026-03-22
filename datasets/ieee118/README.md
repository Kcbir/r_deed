# IEEE 118-bus dataset (canonical bundle)

All **main** project data for the classic DEED / OPF pipeline lives here. Long-form: **`docs/DATA_AND_RUNBOOK.md`** · **`docs/STRATEGY.md`**.

| File | Description |
|------|-------------|
| `ieee118cdf.txt` | IEEE Common Data Format — network (UW archive / 1961 case). |
| `ieee118psp.txt` | PSAP-style bus names / extra fields (same case). |
| `ieee118_generator_cost_usd.csv` | Quadratic fuel cost \(aP^2+bP+c\) per thermal unit (MATPOWER `case118` `gencost`, USD interpretation). |
| `ieee118_gen_dispatch_default.csv` | Default active power `Pg` (MW) per unit from MATPOWER `case118.m` + per-unit cost and **hourly** cost at that dispatch. |
| `ieee118_res_buses.csv` | **Author-added** RES: PV at bus **60**, wind at bus **78**, **Pmax = 400 MW** each (`docs/DATA_AND_RUNBOOK.md`). |
| `ieee118_res_economics.csv` | RES **fuel (0)**, **variable O&M \$/MWh**, optional **curtailment penalty** (`docs/DATA_AND_RUNBOOK.md` §6). |
| `ieee118_deed_params.csv` | **Carbon price** (USD/tCO₂), default thermal **kg CO₂/MWh** fallback, RES operational CO₂ (0). |
| `ieee118_thermal_co2_kg_per_mwh.csv` | Per-generator **operational** CO₂ intensity (kg/MWh); author default **520** unless you have plant data. |
| `res_forecast_hourly_24h.csv` | 24 h hourly **available** PV/wind (MW) + p.u. of Pmax; built from `archive/non_ieee118_raw/` via `scripts/ieee118_res_forecast_build.py`. |

**Base:** MATPOWER `case118.m` — CDF conversion noted in MATPOWER docs.

Run `python3 scripts/ieee118_thermal_benchmark.py` to regenerate `outputs/ieee118_thermal_benchmark_summary.csv`.

Run `python3 scripts/ieee118_res_forecast_build.py` to regenerate `res_forecast_hourly_24h.csv`.

Run `python3 scripts/ieee118_system_cost_benchmark.py` → `outputs/ieee118_system_cost_benchmark.csv` (fuel + **monetized thermal CO₂** + RES O&M **components**; see `docs/DATA_AND_RUNBOOK.md` §5).

**RES:** PSTCA/MATPOWER do not ship PV/wind time series. Provenance / **hour-of-day alignment** caveat: **`docs/DATA_AND_RUNBOOK.md`** §3. Raw CSVs: `archive/non_ieee118_raw/`.
