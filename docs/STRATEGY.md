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

**Vanilla economic dispatch (implemented, Stage 1):** **`scripts/ieee118_vanilla_dcopf.py`** runs **PYPOWER `rundcopf`** on **`case118`**: **minimum thermal fuel cost** under **DC** power flow, with **curtailable RES** injections (Pmin=0, Pmax=P_avail). Thermal CO₂ and monetized carbon post-processed. See **`docs/DATA_AND_RUNBOOK.md` §8**.

**True DEED (implemented, Stage 2):** **`scripts/ieee118_deed.py`** runs the full multi-objective problem:
- **Weighted-sum Pareto sweep**: $\omega \in [0,1]$ maps to effective carbon price $\pi_{\mathrm{eff}} = \frac{\omega}{1-\omega} \cdot \pi_{\mathrm{nom}}$, sweeping 24 h dispatch for each trade-off point.
- **ε-constraint**: binary search for shadow price $\pi^*$ such that $E_{\mathrm{CO_2}}(\pi^*) \approx \varepsilon$.

**Sanity + AC/DC comparison (implemented):** **`scripts/ieee118_validate_acdc.py`**: 4/4 sanity checks pass; DC OPF underestimates cost by ~4.5% vs AC because it ignores ~133 MW transmission losses. See **`docs/DATA_AND_RUNBOOK.md` §10**.

---

## Economics stack (defaults)

| Layer | What |
|-------|------|
| **Thermal** | Polynomial fuel cost from MATPOWER; default **`Pg`** in `ieee118_gen_dispatch_default.csv`. |
| **Thermal CO₂** | `ieee118_thermal_co2_kg_per_mwh.csv` — heterogeneous: coal_steam=**820**, gas_ccgt=**400**, gas_ocgt=**550** kg/MWh (12/7/35 units). |
| **Carbon price** | `ieee118_deed_params.csv` → `carbon_price_usd_per_tco2` = **$85/tCO₂** (tunable SCC / shadow price). |
| **RES** | Bus **60** PV Pmax **150 MW**, bus **78** wind Pmax **400 MW**; curtailable (Pmin=0); `ieee118_res_economics.csv` — fuel **0**, variable O&M **\$/MWh**. |

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
