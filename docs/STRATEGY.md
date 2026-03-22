# Strategy — what this repo is for

## Goal

**Single benchmark path:** **IEEE 118-bus** transmission case for **DEED / OPF–style** work: **thermal fuel cost** (MATPOWER `gencost`), **operational CO₂** (author defaults), **aggregated PV + wind** at two buses with a **24 h** availability forecast.

- **Network & thermal:** from **UW PSTCA / MATPOWER** `case118` (CDF + `gencost` + default `Pg`).
- **RES time series:** **not** in PSTCA — built from **`archive/non_ieee118_raw/`** and documented as **author-added**.

Everything below is the **intended mental model**; **files, scripts, and numbers** live in **`docs/DATA_AND_RUNBOOK.md`**.

---

## Why \$3.15 M/day (118-bus) vs **\$0.6–\$46/day** (archived site CSV)

**Not the same “apple.”**

| | IEEE 118 benchmark | Archived site logger |
|--|-------------------|----------------------|
| **Scale** | Total load **~4242 MW** (bulk system) | **~0.064 MW** average load (**~64 kW**) |
| **Order of magnitude** | \(\sim 4.2\times 10^3\) MW | \(\sim 6.4\times 10^{-2}\) MW |

So **\$/day** differs by **~4–5 orders of magnitude** before economics. Same **math** (e.g. \$/MWh × MWh), different **MWh/day**.

**How to compare fairly:** use **\$/MWh**, or **scale** one system to match the other’s load base, or **report separately** (benchmark vs field). Never add or ratio those **\$** without stating **same MW·h base**.

---

## What we optimize (DEED-style)

Classic **DEED** is usually **multi-objective**:

1. **Fuel / operating cost** — quadratic thermal \(aP^2+bP+c\) per unit (`ieee118_generator_cost_usd.csv`).
2. **Emissions** — here **CO₂** as **kg/MWh × MWh** (per unit), plus optional **monetized** term \(\pi\) **USD/tCO₂**.

Common formulations: **weighted sum** \( \omega_1 C_{\mathrm{fuel}} + \omega_2 E \), **ε-constraint**, or **monetized carbon** \( C_{\mathrm{fuel}} + \pi \cdot \mathrm{tons}_{\mathrm{CO_2}} \).

**Renewables (hourly dispatch model):** **fuel = 0**, **operational CO₂ = 0** (lifecycle LCA is separate). Optional **linear** variable O&M (or LCOE proxy) **\$/MWh** on RES energy. The **environmental** lever next to **\$M/day fuel** is **thermal CO₂ + \(\pi\)**, not inflating RES O&M.

**Joint dispatch:** a real solver **minimizes** your objective subject to **balance & limits**; RES **displaces** thermal. The **benchmark scripts** use **fixed MATPOWER thermal P** + **forecast RES** — they report **components**, not one **optimal** coupled DEED solution.

**Vanilla economic dispatch (implemented):** **`scripts/ieee118_vanilla_dcopf.py`** runs **PYPOWER `rundcpf`** on **`case118`**: **minimum thermal fuel cost** under **DC** power flow, with **fixed RES** injections from the hourly forecast (**full uptake**). This **does** re-dispatch thermal against **network constraints** (DC), unlike the fixed-`Pg` CSV benchmark. **Stage 2:** hourly **thermal CO₂** and **monetized carbon** (from `ieee118_deed_params.csv` + `ieee118_thermal_co2_kg_per_mwh.csv`); optional **`--carbon-price-for-opf`** to put carbon in the **OPF objective**. See **`docs/DATA_AND_RUNBOOK.md` §8–9**.

---

## Economics stack (defaults)

| Layer | What |
|-------|------|
| **Thermal** | Polynomial fuel cost from MATPOWER; default **`Pg`** in `ieee118_gen_dispatch_default.csv`. |
| **Thermal CO₂** | `ieee118_thermal_co2_kg_per_mwh.csv` (default **520 kg/MWh** illustrative per unit — replace with plant data). |
| **Carbon price** | `ieee118_deed_params.csv` → `carbon_price_usd_per_tco2` (tunable SCC / shadow price). |
| **RES** | Buses **60** (PV), **78** (wind), **Pmax 400 MW** each; **`ieee118_res_economics.csv`** — fuel **0**, variable O&M **\$/MWh**, optional curtailment penalty. |

Full LCOE (CAPEX, discounting) is **not** embedded unless you collapse it to one **\$/MWh**.

---

## Isolated cost formulas (no OPF coupling)

Per hour \(h\), thermal unit \(i\):

\[
C^{\mathrm{th}}_{i,h} = a_i P_{i,h}^2 + b_i P_{i,h} + c_i .
\]

RES (accounting only):

\[
C^{\mathrm{res}}_{h} = c_{\mathrm{pv}} P^{\mathrm{pv}}_{h} + c_{\mathrm{w}} P^{\mathrm{w}}_{h}
\quad\text{(with your \$/MWh from CSV).}
\]

Coupling (balance, losses, limits) is a **separate** optimization step.

---

## References (external)

- IEEE 118 / MATPOWER: [MATPOWER `case118`](https://github.com/MATPOWER/matpower).
- PSTCA: [UW PSTCA](https://labs.ece.uw.edu/pstca/).

**Edit this file** when the **research story** changes (objectives, scale, what “benchmark” means).
