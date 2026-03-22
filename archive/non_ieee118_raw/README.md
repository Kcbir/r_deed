# Archive — raw time series (data-driven RES shapes)

These files are **not** IEEE 118 network data. They are **realistic time series** (ramps, clouds, night, wind variability) used **only** to build **shape**, then **scaled** to the benchmark (**Pmax 400 MW** per resource on buses 60 / 78).  

**Canonical output:** `datasets/ieee118/res_forecast_hourly_24h.csv` (regenerate with `scripts/ieee118_res_forecast_build.py`).

---

## 1. Is this archive “enough”? Do you need another “real-time” dataset?

| Goal | This archive | You may need **more** data if… |
|------|----------------|--------------------------------|
| **Data-driven PV/wind shapes** (ramps, night, variability) | **Yes** — PV from logger output; wind from hub-height speed → power curve. | You want **sub-hourly** training data (≥15 min native) beyond what you resample. |
| **One 24 h horizon** for DEED/OPF experiments | **Yes** — script produces hourly `p_pv_mw`, `p_wind_mw`. | You need **many days** (seasons, scenarios) → add more days from the **same** archives or new sources. |
| **Physically joint PV + wind** (same storm, same day) | **Not from this pair alone** — current bundle pairs **different** calendar days by `hour_of_day` only. | You want **one meteorological day** → use a **single** dataset that has **PV + wind + time** aligned (same site/region, same timestamps), or **synthetic correlated** series. |
| **“Real-time” as in live grid API** | N/A. | Operational **SCADA/PMU** is a different project; for **research**, **logged** historical CSVs like these are the usual **data-driven** input. |

**Bottom line:** For **data-driven shapes** and **IEEE 118 scaling**, **you do not *have* to** add another dataset — the archive is the **source of truth** for that. Add **another** dataset only when you need **joint met**, **longer horizons**, **different region**, or **higher resolution** — not because “real-time” is missing (historical logger data **is** real data, just not live).

---

## 2. File index

| File | Role | Used for |
|------|------|----------|
| **`carbon_neutral_dataset_5sec (1).csv`** | Site-scale **5 s** time series | **PV shape:** column `PV Output (kW)`; optional context: `Solar Irradiance (W/m²)`, load, battery, etc. (not used by default forecast script). |
| **`Test.csv`** | Hourly / sub-hourly **meteo** | **Wind shape:** column `WS_100m` (m/s) → cubic power curve in script; `Time` parsed as **day-first** (`dd-mm-yyyy`). |

---

## 3. `carbon_neutral_dataset_5sec (1).csv`

| Column | Description |
|--------|----------------|
| `Timestamp` | Row time (first day in file used for **PV** profile: **2025-05-13** in current build). |
| `Solar Irradiance (W/m²)` | Irradiance (optional; script uses **`PV Output (kW)`** by default for shape). |
| `Temperature (°C)` | Ambient (not used in default RES build). |
| `PV Output (kW)` | **Primary input** for PV — resampled to **1 h mean**, normalized by **max hourly mean** that day, × **Pmax_pv = 400 MW**. |
| `Grid Voltage (V)` | Not used in RES forecast. |
| `Grid Frequency (Hz)` | Not used. |
| `Industrial Load Demand (kW)` | Not used in default RES forecast. |
| `SOC (%)` | Not used. |
| `Battery Charge/Discharge (kW)` | Not used. |
| `Fault Indicator (1/0)` | Not used. |
| `Stability Index` | Not used. |

**Resolution:** 5 s → script aggregates to **hourly** for `res_forecast_hourly_24h.csv`.  
**Scale:** kW at site → **MW** on IEEE 118 via **p.u. of daily peak** × **400 MW** (not a physical MW mapping from site to utility).

---

## 4. `Test.csv`

| Column | Description |
|--------|-------------|
| (first column) | Unnamed index — script may drop if unused. |
| `Time` | Timestamp (**day-first** parsing). Script filters **one day** — **2017-05-13** in current build. |
| `Location` | Site id. |
| `Temp_2m`, `RelHum_2m`, `DP_2m` | Meteo (not used in default wind build). |
| `WS_10m`, **`WS_100m`** | Wind speed — **100 m** used for **aggregate wind** power (`vin=3`, `vr=12`, `vout=25` m/s), **Pmax_wind = 400 MW**. |
| `WD_10m`, `WD_100m`, `WG_10m` | Direction / gust — not used in default script. |

**Resolution:** Rows can be **15‑minute** on the selected day; script averages to **hourly** for alignment with PV.

---

## 5. Limitations (read before publishing)

1. **PV day ≠ wind day** — different years/dates; pairing is **`hour_of_day` only** for a single 24 h table.  
2. **Site scale ≠ utility scale** — shapes are **scaled**, not physical interconnection.  
3. **Synthetic columns** — carbon-neutral file may include modeled/simulated columns; treat as **shape** unless you validate against a real plant.  
4. **Wind** — single **met tower** / **model** column; **not** a full wind farm SCADA.

---

## 6. If you add new raw files

1. Drop them here (or a subfolder).  
2. Update **`scripts/ieee118_res_forecast_build.py`** (or a new script) to read columns.  
3. Document **columns** in this README.  
4. Regenerate `datasets/ieee118/res_forecast_hourly_24h.csv` and update **`docs/DATA_AND_RUNBOOK.md`** §3.  

See also **`docs/STRATEGY.md`** (why) and **`docs/DATA_AND_RUNBOOK.md`** (commands + outputs).
