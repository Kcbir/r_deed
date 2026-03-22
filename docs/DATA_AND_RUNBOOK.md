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
| `ieee118_res_buses.csv` | RES: **bus 60** PV Pmax **150 MW**, **bus 78** wind Pmax **400 MW**, Pd from CDF. |
| `ieee118_res_economics.csv` | RES: **fuel 0**, **variable O&M \$/MWh**, **curtailment penalty \$/MWh**. |
| `ieee118_deed_params.csv` | **`carbon_price_usd_per_tco2`**, **`thermal_co2_kg_per_mwh_default`**, **`res_operational_co2_kg_per_mwh`**. |
| `ieee118_thermal_co2_kg_per_mwh.csv` | Per-generator **operational CO₂** (kg/MWh) with **`fuel_type`** column (coal_steam=820, gas_ccgt=400, gas_ocgt=550). |
| `res_forecast_hourly_24h.csv` | **24 h** `p_pv_mw`, `p_wind_mw`, p.u., profile dates, `wind_source_date` provenance. |

---

## 3. RES forecast — columns & provenance

Built by **`scripts/ieee118_res_forecast_build.py`** from:

- **PV:** `archive/non_ieee118_raw/carbon_neutral_dataset_5sec (1).csv` — `PV Output (kW)`, **first calendar day** (2025-05-13), hourly **mean**; scaled to **Pmax=150 MW**.
- **Wind:** `archive/non_ieee118_raw/Test.csv` — `WS_100m`, day **`2017-05-13`**, **ensemble mean across 4 locations** (Location 1–4); 15‑min → **hourly mean**; power curve **vin=3, vr=12, vout=25** m/s, **Pmax_wind=400 MW**. Re-indexed to synthetic date **2025-05-13**.

> **Synthetic date alignment:** Both PV and wind are treated as **2025-05-13** (May 13) so all 24 hours share the same calendar day. This is explicitly synthetic — PV data is real logger data; wind data is from 2017 reindexed to the same date.

Key capacity factors (May 13): PV CF ≈ **32%** (avg 48 MW / 150 MW), Wind CF ≈ **9.5%** (avg 38 MW / 400 MW).

| Column | Meaning |
|--------|---------|
| `Timestamp` | Hour start (**PV** profile, synthetic 2025-05-13). |
| `hour_of_day` | 0–23 (aligns PV + wind rows). |
| `profile_date_pv` | Date of PV data (2025-05-13). |
| `profile_date_wind` | Synthetic date 2025-05-13 (wind re-indexed from 2017-05-13). |
| `wind_source_date` | Original raw date of wind data (**2017-05-13**) for provenance. |
| `ws_ensemble_m_s` | Ensemble-mean wind speed at 100m across all 4 locations. |
| `p_pv_mw`, `p_wind_mw` | Available power (MW). |
| `pv_pu_of_pmax`, `wind_pu_of_pmax` | ÷ Pmax (150 MW PV, 400 MW wind). |

**Note:** Both PV and wind are paired by `hour_of_day` for one synthetic 24 h horizon on May 13.

### 3.1 Data-driven shapes — is the archive enough? Another dataset?

- **You want real ramps, clouds, night, etc.:** the archive **is** the **data-driven** source (5 s PV / meteo wind); **no extra “real-time” feed is required** for research — **historical logger** data is still **real** data, just not live SCADA.
- **You do *not* need another dataset** unless you need: **joint** PV+wind same weather day, **many days** of scenarios, **sub-hourly** native series, or a **different region** — then add files and document them in **`archive/non_ieee118_raw/README.md`**.

---

## 4. Scripts

| Script | Reads | Writes |
|--------|--------|--------|
| **`ieee118_thermal_benchmark.py`** | `ieee118_gen_dispatch_default.csv` | `outputs/ieee118_thermal_benchmark_summary.csv` |
| **`ieee118_res_forecast_build.py`** | Archive CSVs | `datasets/ieee118/res_forecast_hourly_24h.csv` |
| **`ieee118_system_cost_benchmark.py`** | Default dispatch, RES economics, deed_params, co2, forecast | `outputs/ieee118_system_cost_benchmark.csv` |
| **`ieee118_vanilla_dcopf.py`** | PYPOWER `case118`, forecast, deed_params, co2 | `outputs/ieee118_vanilla_dcopf_hourly_fuelopf.csv` + summary |
| **`ieee118_deed.py`** | Same as vanilla + deed_params | `outputs/ieee118_deed_weighted_sum_pareto.csv`, `ieee118_deed_epsilon_constraint.csv`, `ieee118_deed_hourly_best.csv` |
| **`ieee118_validate_acdc.py`** | Same as vanilla + gen_dispatch_default | `outputs/ieee118_validation_sanity.csv`, `ieee118_acdc_comparison_hourly.csv`, `ieee118_acdc_comparison_summary.csv` |

```bash
cd /path/to/RMS
pip install -r requirements.txt   # or: conda activate aniate
python3 scripts/ieee118_thermal_benchmark.py
python3 scripts/ieee118_res_forecast_build.py
python3 scripts/ieee118_system_cost_benchmark.py
python3 scripts/ieee118_vanilla_dcopf.py
python3 scripts/ieee118_deed.py --n-points 20 --plot
python3 scripts/ieee118_validate_acdc.py --plot
```

> **Python environment:** Use `conda activate aniate` (Python 3.10, NumPy 1.26.4, PYPOWER 5.1.19). The base conda env has NumPy 2.x which is incompatible with PYPOWER.

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

This is the **first real optimization** step: **minimize total thermal fuel cost** (quadratic `gencost`) subject to **DC power flow** and limits, with **RES treated as curtailable injections** (Pmin=0, Pmax=P_avail).

| Item | Detail |
|------|--------|
| **Solver** | `pypower.rundcopf` on **`pypower.case118()`** |
| **Objective** | Minimize \(\sum_i \left(a_i P_i^2 + b_i P_i + c_i\right)\) over **thermal** units only; RES rows have **zero** fuel coefficients. |
| **RES** | Extra generators at **bus 60** (PV, Pmax=150 MW) and **bus 78** (wind, Pmax=400 MW) with **`Pmin=0, Pmax=P^{\mathrm{avail}}`** → curtailment allowed by the optimizer. |
| **CO₂ mix** | coal_steam=820, gas_ccgt=400, gas_ocgt=550 kg/MWh (heterogeneous). |
| **What it is not** | **AC** OPF, valve-point effects, network losses in DC objective, ramp constraints, emissions in objective. |

**Dependencies:** `requirements.txt` (**NumPy 1.x** — PYPOWER incompatible with NumPy 2.x). Use `conda activate aniate`.

**Outputs**

- `outputs/ieee118_vanilla_dcopf_hourly_fuelopf.csv` — fuel-only OPF + post-process emissions (`thermal_tons_co2_per_h`, `monetized_carbon_usd_per_h`, `thermal_social_cost_usd_per_h`).
- `outputs/ieee118_vanilla_dcopf_summary_fuelopf.csv` — daily sums.

**Commands**

```bash
python3 scripts/ieee118_vanilla_dcopf.py
python3 scripts/ieee118_vanilla_dcopf.py --hour 12
```

**Interpretation:** Thermal $/h here is **not** MATPOWER default `Pg` — DC OPF re-dispatches thermal with curtailable RES.  
**Benchmark:** OPF at hour 6 costs $118,262/h vs MATPOWER default $131,322/h (**10% cheaper** — confirms optimizer is working).

---

## 9. DEED — Dynamic Economic Emission Dispatch

True multi-objective formulation. Two methods in **`scripts/ieee118_deed.py`**:

### 9.1 Weighted-sum Pareto

$$\min_{P_g} \; \omega \cdot C_{\mathrm{fuel}} + (1-\omega) \cdot \pi_{\mathrm{eff}} \cdot E_{\mathrm{CO_2}}$$

where $\pi_{\mathrm{eff}} = \frac{\omega}{1-\omega} \cdot \pi_{\mathrm{nom}}$ and $\omega \in [0,1]$. Sweeps $n$ points to produce the Pareto front.

### 9.2 ε-constraint

$$\min_{P_g} C_{\mathrm{fuel}} \quad \text{s.t.} \quad E_{\mathrm{CO_2}} \leq \varepsilon$$

Implemented via binary search over shadow carbon price $\pi^*$ such that $E_{\mathrm{CO_2}}(\pi^*) \approx \varepsilon$.

**Verified results (10 points, May 13):**

| MODE | Fuel $/day | CO₂ t/day | Social $/day |
|------|-----------|-----------|-------------|
| Fuel-only (ω=1, π=0) | $2,942,000 | 79,498 | $9,699,000 |
| Social (π=$85/tCO₂) | $3,955,000 | 54,678 | $8,603,000 |
| Min-emission (ω=0) | $2,942,000 | 79,498 | — |

> 31% CO₂ reduction at $85/tCO₂ carbon price, at cost of 34% higher fuel spend.

**Outputs:**
- `outputs/ieee118_deed_weighted_sum_pareto.csv`
- `outputs/ieee118_deed_epsilon_constraint.csv`
- `outputs/ieee118_deed_hourly_best.csv`
- `outputs/ieee118_deed_pareto_fronts.png` (with `--plot`)

```bash
python3 scripts/ieee118_deed.py --n-points 20 --plot
```

---

## 10. Sanity Checks & AC vs DC Comparison

Script: **`scripts/ieee118_validate_acdc.py`**

### Sanity checks (4/4 PASS)

| Check | Result |
|-------|--------|
| Baseline cost match (PYPOWER vs stored CSV) | 0.0000% delta — PASS |
| OPF improves on MATPOWER default (hour 6) | $118,262 vs $131,322 (ratio 0.90) — PASS |
| Generator limits (hour 12) | 0 violations — PASS |
| Power balance DC (hour 12) | Pg=Pd=4242 MW, 0.000% imbalance — PASS |

### AC vs DC comparison

Methodology: run DC OPF → fix dispatch → re-evaluate under AC power flow (Newton-Raphson).

| Metric | Value |
|--------|-------|
| DC fuel/day | $2,942,000 |
| AC fuel/day (at DC dispatch) | $3,075,000 |
| AC−DC delta | +$133,000 (+4.5%) |
| Mean AC transmission losses | 133 MW |

> DC OPF systematically **underestimates** cost by ~4.5% because it ignores I²R losses.

**Outputs:**
- `outputs/ieee118_validation_sanity.csv`
- `outputs/ieee118_acdc_comparison_hourly.csv`
- `outputs/ieee118_acdc_comparison_summary.csv`
- `outputs/ieee118_acdc_comparison.png` (with `--plot`)

```bash
python3 scripts/ieee118_validate_acdc.py --plot
```

---

## 11. Reproducibility (Stage 1)

| Item | Location |
|------|-----------|
| **Pinned deps** | `requirements.txt` (exact versions). Install: `pip install -r requirements.txt`. |
| **Git** | `git init` once; tag releases e.g. `git tag rms-v1-baseline` after a commit that matches your paper run. |
| **Ignore** | `.gitignore` — Python caches, venvs (not datasets). |

Regenerate all benchmark outputs after changing data or scripts so tags stay meaningful.
