# Datasets

Canonical detail: **`docs/DATA_AND_RUNBOOK.md`**.

## Primary (use this)

**`ieee118/`** — IEEE 118-bus network files, generator costs, default MATPOWER dispatch, **RES bus/Pmax** (`ieee118_res_buses.csv`), and **24 h RES forecast** (`res_forecast_hourly_24h.csv`).  
See `ieee118/README.md` and `../docs/DATA_AND_RUNBOOK.md` (file list); `../docs/STRATEGY.md` for objectives and scale.

## Archive (raw inputs for RES forecast)

**`../archive/non_ieee118_raw/`** — PV logger + wind meteo CSVs used by `scripts/ieee118_res_forecast_build.py` (see `../docs/DATA_AND_RUNBOOK.md`).
