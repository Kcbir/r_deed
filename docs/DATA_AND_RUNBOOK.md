# Data & runbook — files, scripts, outputs

Use this as the **single map** for **datasets**, **Python scripts**, and **CSV outputs**. Pair with **`docs/STRATEGY.md`** for *why*.

**Edit this file** when you add/rename files, columns, or commands.

---

## 1. Folder roles

| Path | Role |
|------|------|
| **`datasets/ieee118/`** | All **canonical** IEEE 118 inputs (network, costs, dispatch, RES, economics, CO₂). |
| **`archive/non_ieee118_raw/`** | **Raw** PV + wind/meteo time series — **data-driven shapes**; full manifest → **`archive/non_ieee118_raw/README.md`**. |
| **`scripts/`** | Runnable **`.py`** benchmarks. |
| **`outputs/`** | **Generated** summaries + **vanilla DC OPF** hourly results (safe to delete; regenerate). |

---

## 2. `datasets/ieee118/` — file list

| File | Purpose |
|------|---------|
| `ieee118cdf.txt` | Network (IEEE CDF). |
| `ieee118psp.txt` | Extra bus/name fields. |
| `ieee118_generator_cost_usd.csv` | Thermal **\(a,b,c\)** (MATPOWER `gencost`, USD). |
| `ieee118_gen_dispatch_default.csv` | Default **`Pg_MW`**, per-unit **hourly fuel \$** at that dispatch. |
| `ieee118_res_buses.csv` | RES: **bus 60** PV, **bus 78** wind, **Pmax 400 MW** each, **Pd** from CDF. |
| `ieee118_res_economics.csv` | RES: **fuel 0**, **variable O&M \$/MWh**, **curtailment penalty \$/MWh**. |
| `ieee118_deed_params.csv` | **`carbon_price_usd_per_tco2`**, **`thermal_co2_kg_per_mwh_default`**, **`res_operational_co2_kg_per_mwh`**. |
| `ieee118_thermal_co2_kg_per_mwh.csv` | Per-generator **operational CO₂** (kg/MWh). |
| `res_forecast_hourly_24h.csv` | **24 h** `p_pv_mw`, `p_wind_mw`, p.u., profile dates. |

---

## 3. RES forecast — columns & provenance

Built by **`scripts/ieee118_res_forecast_build.py`** from:

- **PV:** `archive/non_ieee118_raw/carbon_neutral_dataset_5sec (1).csv` — `PV Output (kW)`, **first calendar day**, hourly **mean**.
- **Wind:** `archive/non_ieee118_raw/Test.csv` — `WS_100m`, day **`2017-05-13`**, 15‑min → **hourly mean**; power curve **vin=3, vr=12, vout=25** m/s, **Pmax_wind=400 MW**.

| Column | Meaning |
|--------|---------|
| `Timestamp` | Hour start (**PV** profile). |
| `hour_of_day` | 0–23 (aligns PV + wind rows). |
| `profile_date_pv` | Date of PV raw day. |
| `profile_date_wind` | **`2017-05-13`** for wind. |
| `p_pv_mw`, `p_wind_mw` | Available power (MW). |
| `pv_pu_of_pmax`, `wind_pu_of_pmax` | ÷ 400 MW. |

**Caveat:** PV and wind are **not** the same meteorological day; pairing is **`hour_of_day` only** for one 24 h horizon.

### 3.1 Data-driven shapes — is the archive enough? Another dataset?

- **You want real ramps, clouds, night, etc.:** the archive **is** the **data-driven** source (5 s PV / meteo wind); **no extra “real-time” feed is required** for research — **historical logger** data is still **real** data, just not live SCADA.
- **You do *not* need another dataset** unless you need: **joint** PV+wind same weather day, **many days** of scenarios, **sub-hourly** native series, or a **different region** — then add files and document them in **`archive/non_ieee118_raw/README.md`**.

---

## 4. Scripts

| Script | Reads | Writes |
|--------|--------|--------|
| **`ieee118_thermal_benchmark.py`** | `ieee118_gen_dispatch_default.csv` | `outputs/ieee118_thermal_benchmark_summary.csv` |
| **`ieee118_res_forecast_build.py`** | Archive CSVs | `datasets/ieee118/res_forecast_hourly_24h.csv` |
| **`ieee118_system_cost_benchmark.py`** | Default dispatch, RES economics, `ieee118_deed_params.csv`, `ieee118_thermal_co2_kg_per_mwh.csv`, `res_forecast_hourly_24h.csv` | `outputs/ieee118_system_cost_benchmark.csv` |
| **`ieee118_vanilla_dcopf.py`** | PYPOWER `case118`, `res_forecast_hourly_24h.csv`, optional carbon-weighted objective | `outputs/ieee118_vanilla_dcopf_hourly_{fuelopf,socialopf}.csv`, matching `*_summary_*.csv` |

```bash
cd /path/to/RMS
pip install -r requirements.txt
python3 scripts/ieee118_thermal_benchmark.py
python3 scripts/ieee118_res_forecast_build.py
python3 scripts/ieee118_system_cost_benchmark.py
python3 scripts/ieee118_vanilla_dcopf.py
```

---

## 5. Outputs (typical meaning)

### `outputs/ieee118_thermal_benchmark_summary.csv`

- **`thermal_cost_usd_per_h`** — sum of thermal **fuel \$** at MATPOWER default **`Pg`** (~**\$131,322/h**).
- **`thermal_cost_usd_per_day_24h_constant`** — ×24 (~**\$3.15M/day**) if dispatch is **constant**.

### `outputs/ieee118_system_cost_benchmark.csv`

**Component** breakdown (not joint optimal DEED):

- Thermal **fuel** / day (same basis as above).
- **`thermal_tons_co2_per_day_24h`** — \(\sum_i (\mathrm{kgCO_2/MWh})_i \cdot P_i \cdot 24 / 1000\).
- **`monetized_thermal_carbon_usd_per_day`** — `carbon_price_usd_per_tco2 ×` tons.
- **RES variable O&M** on **forecast MWh** (full uptake: dispatch = available).
- **`sum_fuel_plus_monetized_carbon_usd_per_day`**, **`naive_sum_fuel_carbon_res_om_usd_per_day`**.

**Thermal-only anchor (from MATPOWER default dispatch):**

- \(C_{\mathrm{th,h}} \approx 131{,}322\) USD/h  
- \(C_{\mathrm{th,day}} \approx 3{,}151{,}728\) USD/day  

(Source: `ieee118_gen_dispatch_default.csv`, MATPOWER `case118.m` `mpc.gen` + `mpc.gencost`.)

---

## 6. What to change most often (tuning)

| Intent | Edit |
|--------|------|
| RES **\$/MWh**, curtailment | `ieee118_res_economics.csv` |
| Carbon **\$/tCO₂**, RES ops CO₂ | `ieee118_deed_params.csv` |
| Per-unit **kg CO₂/MWh** | `ieee118_thermal_co2_kg_per_mwh.csv` |
| RES **buses / Pmax** | `ieee118_res_buses.csv` + rebuild forecast logic if needed |
| **24 h shapes** | Raw files in `archive/…` then rerun **`ieee118_res_forecast_build.py`** |

---

## 7. Regenerate after edits

After changing **archive** raw data or **forecast** script logic:

```bash
python3 scripts/ieee118_res_forecast_build.py
python3 scripts/ieee118_system_cost_benchmark.py
```

After changing **thermal dispatch** source (if you ever replace `ieee118_gen_dispatch_default.csv`):

```bash
python3 scripts/ieee118_thermal_benchmark.py
python3 scripts/ieee118_system_cost_benchmark.py
```

---

## 8. Vanilla economic dispatch — DC OPF (PYPOWER)

This is the **first real optimization** step: **minimize total thermal fuel cost** (quadratic `gencost`) subject to **DC power flow** and limits, with **RES treated as fixed injections**.

| Item | Detail |
|------|--------|
| **Solver** | `pypower.rundcpf` on **`pypower.case118()`** |
| **Objective** | Minimize \(\sum_i \left(a_i P_i^2 + b_i P_i + c_i\right)\) over **thermal** units only; RES rows have **zero** fuel coefficients. |
| **RES** | Extra generators at **bus 60** (PV) and **bus 78** (wind) with **`P_{\min}=P_{\max}=P^{\mathrm{avail}}\)** from `res_forecast_hourly_24h.csv` → **full uptake**, not curtailment optimization. |
| **What it is not** | **AC** OPF, **valve-point** effects, **network losses** in the DC objective, **ramp constraints**, **OTS**, **emissions** in the objective (emissions can be **post-processed** from `Pg`). |

**Dependencies:** `requirements.txt` (**NumPy 1.x** — stock **PYPOWER** is not always compatible with NumPy 2.x).

**Outputs**

- `outputs/ieee118_vanilla_dcopf_hourly_fuelopf.csv` — fuel-only OPF + **post-process** emissions (`thermal_tons_co2_per_h`, `monetized_carbon_usd_per_h` using `carbon_price` from `ieee118_deed_params.csv`, `thermal_social_cost_usd_per_h` = fuel + monetized).  
- `outputs/ieee118_vanilla_dcopf_summary_fuelopf.csv` — daily sums.  
- `outputs/ieee118_vanilla_dcopf_hourly_socialopf.csv` / `_summary_socialopf.csv` — same, but OPF used **`--carbon-price-for-opf π`** (adds `π·e_i/1000` to each thermal **c1**). If all `e_i` are **equal**, dispatch may match fuel-only; **heterogeneous** `ieee118_thermal_co2_kg_per_mwh.csv` makes the modes differ.

**Commands**

```bash
python3 scripts/ieee118_vanilla_dcopf.py
python3 scripts/ieee118_vanilla_dcopf.py --hour 12
python3 scripts/ieee118_vanilla_dcopf.py --carbon-price-for-opf 85
```

**Interpretation:** Thermal **\$**/h here is **not** MATPOWER default `Pg` — DC OPF **re-dispatches** thermal with **fixed** RES.

---

## 9. Reproducibility (Stage 1)

| Item | Location |
|------|-----------|
| **Pinned deps** | `requirements.txt` (exact versions). Install: `pip install -r requirements.txt`. |
| **Git** | `git init` once; tag releases e.g. `git tag rms-v1-baseline` after a commit that matches your paper run. |
| **Ignore** | `.gitignore` — Python caches, venvs (not datasets). |

Regenerate all benchmark outputs after changing data or scripts so tags stay meaningful.
