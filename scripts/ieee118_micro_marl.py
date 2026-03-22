#!/usr/bin/env python3
"""
IEEE 118 Micro-Level DEED — Multi-Agent Reinforcement Learning (MARL).

Architecture
------------
  • 3 zones → 3 independent RL agents (one per zone).
  • Each agent controls all generators in its zone.
  • Inter-zone coupling: zone agents observe each other's net-export signal
    and must collectively meet the system-wide power balance.

RL Formulation (per agent / zone)
----------------------------------
  State  s_z(t)  = [demand_fraction, res_available_pu, last_Pg_pu, net_export_from_other_zones]
  Action a_z(t)  = Δ Pg_pu per generator in zone (continuous, clipped to [-0.1, +0.1] pu/step)
  Reward r_z(t)  = - (zone_fuel_cost + zone_co2_penalty) + coordination_bonus
                   where coordination_bonus = -alpha * (system_imbalance)^2

Algorithm: Multi-Agent Deep Deterministic Policy Gradient (MADDPG) — tabular-
approximated via Q-table with linear function approximation (no external DL deps).
Specifically we implement a lightweight **Q-learning with linear approximation**
(compatible with numpy-only envs) per agent, sharing global state info from
other agents' actions (the MARL "centralized critic" insight without a neural net).

Training
--------
  • 24-h daily horizon = episodic environment.
  • Each episode: iterate hours 0→23, each step = one hour.
  • Train for `n_episodes` episodes.
  • After training: run one greedy episode (evaluation).

State features (per zone agent, length = 6 + 2*others):
  [demand_fraction, res_pu_own, hour_sin, hour_cos,
   zone_pg_pu_last,  net_export_pu_last,
   neighbour_zone_pg_pu_last × 2]

Action space
  Continuous vector ∈ [-1,1]^{n_gens_zone} mapped to [Pmin, Pmax].
  Greedy action = argmax over discretised grid for eval; gaussian noise for exploration.

Outputs
-------
  outputs/ieee118_marl_training_curve.csv      — per-episode reward
  outputs/ieee118_marl_eval_hourly.csv         — greedy-episode hourly dispatch
  outputs/ieee118_marl_zone_summary.csv        — per-zone daily fuel/CO2 (eval)

Usage
-----
  python3 scripts/ieee118_micro_marl.py
  python3 scripts/ieee118_micro_marl.py --episodes 500 --plot
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pypower.api import case118
from pypower.idx_gen import PG, PMAX, PMIN
from pypower.totcost import totcost

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "ieee118"
OUT  = ROOT / "outputs"

# ---------------------------------------------------------------------------
# Zone definitions (identical to macro script)
# ---------------------------------------------------------------------------

def _bus_to_zone(bus_id: int) -> int:
    b = int(bus_id)
    if b <= 49:  return 1
    if b <= 73:  return 2
    return 3


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class ZonalDEEDEnv:
    """
    3-zone dispatch environment for one 24-h day.

    Each step() call advances one hour. Three agents submit actions simultaneously.
    Reward = negative of combined fuel+carbon cost, minus imbalance penalty.
    """

    def __init__(
        self,
        pmin_th: np.ndarray,  # (54,)
        pmax_th: np.ndarray,
        gc: np.ndarray,       # gencost (54, 7)
        co2: np.ndarray,      # (54,)
        demand_mw: float,
        fc: pd.DataFrame,
        pi_nom: float,
        co2_weight: float = 0.3,
    ):
        self.pmin   = pmin_th
        self.pmax   = pmax_th
        self.gc     = gc
        self.co2    = co2
        self.demand = demand_mw
        self.fc     = fc.reset_index(drop=True)
        self.pi     = pi_nom
        self.co2_w  = co2_weight   # weight on CO2 in reward (0=pure fuel, 1=pure CO2)

        ppc_gen = case118()["gen"]
        self.gen_zones = np.array([_bus_to_zone(b) for b in ppc_gen[:, 0]])
        self.n_total   = len(pmin_th)

        # Per-zone generator indices
        self.zone_idx = {z: np.where(self.gen_zones == z)[0] for z in [1, 2, 3]}
        self.n_gens   = {z: len(self.zone_idx[z]) for z in [1, 2, 3]}

        # State dims per agent: 4 own + 2 neighbour exports
        self.state_dim = 6

        self._step_idx = 0
        self._pg       = np.zeros(self.n_total)

    def reset(self) -> dict[int, np.ndarray]:
        self._step_idx = 0
        # Initialise Pg proportionally to Pmax
        weights = self.pmax / self.pmax.sum()
        self._pg = weights * self.demand
        self._pg = np.clip(self._pg, self.pmin, self.pmax)
        return self._get_states()

    def _get_states(self) -> dict[int, np.ndarray]:
        row = self.fc.iloc[self._step_idx]
        h   = int(row["hour_of_day"])
        p_pv  = float(row["p_pv_mw"])
        p_wd  = float(row["p_wind_mw"])
        res   = p_pv + p_wd

        demand_frac = self.demand / (self.pmax.sum() + 1e-6)
        res_pu      = res / (p_pv + 400.0 + 1e-6)   # normalised
        hour_sin    = np.sin(2 * np.pi * h / 24)
        hour_cos    = np.cos(2 * np.pi * h / 24)

        states = {}
        for z in [1, 2, 3]:
            idx = self.zone_idx[z]
            zone_pg_pu = self._pg[idx].sum() / (self.pmax[idx].sum() + 1e-6)
            # Net export from other zones (their Pg - their load fraction)
            other_export = 0.0
            for oz in [1, 2, 3]:
                if oz == z:
                    continue
                oidx = self.zone_idx[oz]
                other_export += self._pg[oidx].sum()
            other_export_pu = other_export / (self.demand + 1e-6)
            states[z] = np.array([
                demand_frac, res_pu, hour_sin, hour_cos,
                zone_pg_pu, other_export_pu
            ], dtype=np.float32)
        return states

    def step(
        self,
        actions: dict[int, np.ndarray],  # zone → Pg_pu for each gen in that zone
    ) -> tuple[dict[int, np.ndarray], dict[int, float], bool]:
        """
        actions[z] = array shape (n_gens_z,) in [0,1] representing Pg_pu within zone z.
        Returns (next_states, rewards, done).
        """
        row   = self.fc.iloc[self._step_idx]
        p_pv  = float(row["p_pv_mw"])
        p_wd  = float(row["p_wind_mw"])
        res   = p_pv + p_wd

        # Map actions → Pg
        new_pg = self._pg.copy()
        for z, a in actions.items():
            idx   = self.zone_idx[z]
            a_clp = np.clip(a, 0.0, 1.0)
            new_pg[idx] = self.pmin[idx] + a_clp * (self.pmax[idx] - self.pmin[idx])

        # Power balance: net thermal needed = demand - res
        net_demand = max(self.demand - res, 0.0)
        total_th   = new_pg.sum()
        # Scale to balance (preserve zone proportions)
        if total_th > 0:
            new_pg = new_pg * (net_demand / total_th)
        new_pg = np.clip(new_pg, self.pmin, self.pmax)

        # Residual imbalance after clipping
        imbalance = abs(new_pg.sum() - net_demand)

        self._pg = new_pg

        # Compute rewards
        tc_all    = totcost(self.gc, new_pg)
        total_co2 = float(np.sum(self.co2 * new_pg) / 1000.0)
        rewards   = {}
        for z in [1, 2, 3]:
            idx      = self.zone_idx[z]
            zone_tc  = float(np.sum(tc_all[idx]))
            zone_co2 = float(np.sum(self.co2[idx] * new_pg[idx]) / 1000.0)
            # Negative cost → reward (agent minimises cost)
            reward = -(
                (1.0 - self.co2_w) * zone_tc
                + self.co2_w * self.pi * zone_co2
            )
            # Coordination penalty shared across all agents
            reward -= 10.0 * imbalance
            rewards[z] = float(reward)

        self._step_idx += 1
        done   = self._step_idx >= len(self.fc)
        states = self._get_states() if not done else {z: np.zeros(self.state_dim) for z in [1,2,3]}

        return states, rewards, done, {
            "hour": int(row["hour_of_day"]),
            "fuel_usd": float(np.sum(tc_all)),
            "co2_tons": total_co2,
            "imbalance_mw": imbalance,
            "pg": new_pg.copy(),
            "p_pv": p_pv, "p_wd": p_wd,
        }


# ---------------------------------------------------------------------------
# Linear Q-agent (per zone)
# ---------------------------------------------------------------------------

class LinearQAgent:
    """
    Linear function approximation Q-agent.
    Continuous state → discretised action (k_bins per generator dim).
    Feature = state concat action_bin_id (one-hot per gen).
    """

    def __init__(
        self,
        state_dim: int,
        n_gens: int,
        k_bins: int = 5,
        lr: float = 0.01,
        gamma: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
    ):
        self.state_dim = state_dim
        self.n_gens    = n_gens
        self.k_bins    = k_bins
        self.lr        = lr
        self.gamma     = gamma
        self.eps       = epsilon_start
        self.eps_end   = epsilon_end
        self.eps_decay = 0.995

        # action bin centres [0..k_bins-1] → Pg_pu = bin / (k_bins-1)
        self.action_bins = np.linspace(0.0, 1.0, k_bins)

        # Weight matrix: (state_dim + n_gens * k_bins,) → scalar Q
        feat_dim    = state_dim + n_gens * k_bins
        self.W      = np.zeros(feat_dim)

    def _featurise(self, state: np.ndarray, action_indices: np.ndarray) -> np.ndarray:
        # One-hot encode discrete actions per generator
        one_hot = np.zeros(self.n_gens * self.k_bins)
        for g, a in enumerate(action_indices):
            one_hot[g * self.k_bins + int(a)] = 1.0
        return np.concatenate([state, one_hot])

    def act(self, state: np.ndarray, explore: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns (action_pu, action_indices).
        Greedy action = argmax Q over all action combinations per generator 
        (factored: each generator independently maximises Q).
        """
        if explore and np.random.random() < self.eps:
            idx = np.random.randint(0, self.k_bins, self.n_gens)
        else:
            # Factored greedy: pick best bin per generator independently
            idx = np.zeros(self.n_gens, dtype=int)
            for g in range(self.n_gens):
                best_q  = -np.inf
                best_b  = 0
                base_idx = idx.copy()
                for b in range(self.k_bins):
                    base_idx[g] = b
                    feat = self._featurise(state, base_idx)
                    q    = float(self.W @ feat)
                    if q > best_q:
                        best_q = q
                        best_b = b
                idx[g] = best_b
        a_pu = self.action_bins[idx]
        return a_pu, idx

    def update(
        self,
        state: np.ndarray,
        action_idx: np.ndarray,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> float:
        # Q(s,a) estimate
        feat   = self._featurise(state, action_idx)
        q_curr = float(self.W @ feat)

        # TD target
        if done:
            target = reward
        else:
            # Greedy next action (no exploration)
            _, next_idx = self.act(next_state, explore=False)
            next_feat   = self._featurise(next_state, next_idx)
            q_next      = float(self.W @ next_feat)
            target      = reward + self.gamma * q_next

        td_err      = target - q_curr
        self.W     += self.lr * td_err * feat

        # Decay epsilon
        if self.eps > self.eps_end:
            self.eps *= self.eps_decay

        return float(abs(td_err))


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train_marl(
    env: ZonalDEEDEnv,
    n_episodes: int,
    k_bins: int,
    verbose_every: int = 50,
) -> tuple[list[LinearQAgent], list[dict]]:
    """Train 3 zone agents.  Returns (agents, training_log)."""
    agents = {
        z: LinearQAgent(
            state_dim=env.state_dim,
            n_gens=env.n_gens[z],
            k_bins=k_bins,
            lr=0.02,
            gamma=0.95,
            epsilon_start=1.0,
            epsilon_end=0.05,
        )
        for z in [1, 2, 3]
    }

    log = []
    for ep in range(n_episodes):
        states = env.reset()
        ep_reward = {1: 0.0, 2: 0.0, 3: 0.0}
        ep_fuel   = 0.0
        ep_co2    = 0.0
        ep_imb    = 0.0
        steps     = 0
        done      = False

        prev_act_idx = {z: np.zeros(env.n_gens[z], dtype=int) for z in [1,2,3]}

        while not done:
            # Each agent acts
            actions_pu  = {}
            actions_idx = {}
            for z in [1, 2, 3]:
                a_pu, a_idx = agents[z].act(states[z], explore=True)
                actions_pu[z]  = a_pu
                actions_idx[z] = a_idx

            next_states, rewards, done, info = env.step(actions_pu)

            # Update each agent
            for z in [1, 2, 3]:
                agents[z].update(
                    states[z], actions_idx[z],
                    rewards[z], next_states[z], done
                )
                ep_reward[z] += rewards[z]

            ep_fuel += info["fuel_usd"]
            ep_co2  += info["co2_tons"]
            ep_imb  += info["imbalance_mw"]
            steps   += 1
            states  = next_states

        log.append({
            "episode": ep,
            "ep_reward_z1": ep_reward[1],
            "ep_reward_z2": ep_reward[2],
            "ep_reward_z3": ep_reward[3],
            "ep_total_reward": sum(ep_reward.values()),
            "ep_fuel_usd": ep_fuel,
            "ep_co2_tons": ep_co2,
            "ep_imbalance_sum_mw": ep_imb,
            "eps_z1": agents[1].eps,
        })

        if (ep + 1) % verbose_every == 0:
            print(f"  ep {ep+1:4d}/{n_episodes} | "
                  f"fuel=${ep_fuel:>10,.0f} | co2={ep_co2:>7.0f}t | "
                  f"imb={ep_imb:.1f} MW | eps={agents[1].eps:.3f}")

    return agents, log


# ---------------------------------------------------------------------------
# Greedy evaluation
# ---------------------------------------------------------------------------

def evaluate_marl(
    agents: dict[int, LinearQAgent],
    env: ZonalDEEDEnv,
) -> list[dict]:
    """Run one greedy episode; return per-hour info."""
    states = env.reset()
    hourly = []
    done   = False

    while not done:
        actions_pu = {}
        for z in [1, 2, 3]:
            a_pu, _ = agents[z].act(states[z], explore=False)
            actions_pu[z] = a_pu

        next_states, rewards, done, info = env.step(actions_pu)

        pg   = info["pg"]
        tc   = totcost(env.gc, pg)
        z_fuel = {z: float(np.sum(tc[env.zone_idx[z]])) for z in [1,2,3]}
        z_co2  = {z: float(np.sum(env.co2[env.zone_idx[z]] * pg[env.zone_idx[z]]) / 1000.0)
                  for z in [1,2,3]}
        z_pg   = {z: float(pg[env.zone_idx[z]].sum()) for z in [1,2,3]}

        hourly.append({
            "hour_of_day": info["hour"],
            "fuel_usd": info["fuel_usd"],
            "co2_tons": info["co2_tons"],
            "imbalance_mw": info["imbalance_mw"],
            "p_pv_available_mw": info["p_pv"],
            "p_wind_available_mw": info["p_wd"],
            "zone1_fuel_usd": z_fuel[1], "zone2_fuel_usd": z_fuel[2], "zone3_fuel_usd": z_fuel[3],
            "zone1_co2_tons": z_co2[1],  "zone2_co2_tons": z_co2[2],  "zone3_co2_tons": z_co2[3],
            "zone1_pg_mw": z_pg[1],      "zone2_pg_mw": z_pg[2],      "zone3_pg_mw": z_pg[3],
        })
        states = next_states

    return hourly


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="IEEE 118 Micro MARL — Multi-Agent RL per zone"
    )
    parser.add_argument("--episodes",      type=int,   default=300,
                        help="Training episodes (default 300)")
    parser.add_argument("--bins",          type=int,   default=5,
                        help="Action discretisation bins per generator (default 5)")
    parser.add_argument("--co2-weight",    type=float, default=0.3,
                        help="CO2 penalty weight in reward (0=pure fuel, 1=pure CO2, default 0.3)")
    parser.add_argument("--plot",          action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    ppc   = case118()
    pmin  = ppc["gen"][:, PMIN].copy()
    pmax  = ppc["gen"][:, PMAX].copy()
    gc    = ppc["gencost"].copy()
    demand= float(ppc["bus"][:, 2].sum())
    co2   = pd.read_csv(DATA / "ieee118_thermal_co2_kg_per_mwh.csv").sort_values("gen_idx")["co2_kg_per_mwh"].values.astype(float)
    fc    = pd.read_csv(DATA / "res_forecast_hourly_24h.csv")
    prms  = dict(zip(pd.read_csv(DATA / "ieee118_deed_params.csv")["param"],
                     pd.read_csv(DATA / "ieee118_deed_params.csv")["value"].astype(float)))
    pi_nom = float(prms["carbon_price_usd_per_tco2"])

    print("=" * 70)
    print(f"IEEE 118 Micro DEED — Multi-Agent Reinforcement Learning")
    print(f"Zones: Z1(thermal) | Z2(PV) | Z3(wind)")
    print(f"n_gens: Z1={np.sum([_bus_to_zone(b)<=1 for b in ppc['gen'][:,0].astype(int)])}"
          f" / Z2={np.sum([_bus_to_zone(b)==2 for b in ppc['gen'][:,0].astype(int)])}"
          f" / Z3={np.sum([_bus_to_zone(b)==3 for b in ppc['gen'][:,0].astype(int)])}")
    print(f"episodes={args.episodes}  bins={args.bins}  co2_weight={args.co2_weight}  pi_nom={pi_nom}")
    print("=" * 70)

    env = ZonalDEEDEnv(pmin, pmax, gc, co2, demand, fc, pi_nom, args.co2_weight)

    print("\n--- Training ---")
    t0 = time.time()
    agents, log = train_marl(env, args.episodes, args.bins, verbose_every=max(1, args.episodes//10))
    elapsed = time.time() - t0
    print(f"Training done in {elapsed:.1f}s")

    print("\n--- Greedy Evaluation ---")
    eval_hourly = evaluate_marl(agents, env)

    df_log     = pd.DataFrame(log)
    df_hourly  = pd.DataFrame(eval_hourly)

    day_fuel  = df_hourly["fuel_usd"].sum()
    day_co2   = df_hourly["co2_tons"].sum()
    day_social= day_fuel + pi_nom * day_co2

    print(f"\nEval: fuel=${day_fuel:,.0f}  co2={day_co2:.0f}t  social=${day_social:,.0f}")
    print(f"Mean hourly imbalance: {df_hourly['imbalance_mw'].mean():.2f} MW")

    zone_summary = pd.DataFrame([{
        "zone": z, "zone_name": ["Thermal","PV","Wind"][z-1],
        "day_fuel_usd": df_hourly[f"zone{z}_fuel_usd"].sum(),
        "day_co2_tons": df_hourly[f"zone{z}_co2_tons"].sum(),
        "day_pg_mwh":   df_hourly[f"zone{z}_pg_mw"].sum(),
    } for z in [1,2,3]])

    # Save
    log_path  = OUT / "ieee118_marl_training_curve.csv"
    h_path    = OUT / "ieee118_marl_eval_hourly.csv"
    z_path    = OUT / "ieee118_marl_zone_summary.csv"
    df_log.to_csv(log_path, index=False)
    df_hourly.to_csv(h_path, index=False)
    zone_summary.to_csv(z_path, index=False)

    print(f"\nWrote {log_path}")
    print(f"Wrote {h_path}")
    print(f"Wrote {z_path}")
    print("\n=== Zone Summary (MARL eval) ===")
    print(zone_summary.to_string(index=False))

    if args.plot:
        _plot(df_log, df_hourly, OUT)


def _plot(df_log: pd.DataFrame, df_hourly: pd.DataFrame, out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Training curve
    ax = axes[0]
    ax.plot(df_log["episode"], df_log["ep_fuel_usd"] / 1e6, "b-", lw=0.8, alpha=0.6)
    # Rolling mean
    roll = df_log["ep_fuel_usd"].rolling(20, min_periods=1).mean()
    ax.plot(df_log["episode"], roll / 1e6, "r-", lw=2, label="Rolling mean (20ep)")
    ax.set_xlabel("Episode"); ax.set_ylabel("Daily Fuel Cost (M USD)")
    ax.set_title("MARL Training Curve\nDaily Fuel vs Episode")
    ax.legend(); ax.grid(True, alpha=0.3)

    # Greedy: per-zone stacked generation
    ax = axes[1]
    h = df_hourly.sort_values("hour_of_day")
    ax.bar(h["hour_of_day"], h["zone1_pg_mw"], label="Z1 Thermal", color="#d62728")
    ax.bar(h["hour_of_day"], h["zone2_pg_mw"], bottom=h["zone1_pg_mw"].values,
           label="Z2 + PV", color="#ff7f0e")
    ax.bar(h["hour_of_day"], h["zone3_pg_mw"],
           bottom=h["zone1_pg_mw"].values + h["zone2_pg_mw"].values,
           label="Z3 + Wind", color="#2ca02c")
    ax.set_xlabel("Hour of Day"); ax.set_ylabel("Generation (MW)")
    ax.set_title("Zonal Dispatch (Greedy Eval)\nMARL")
    ax.legend(); ax.grid(True, alpha=0.2)

    # CO2 per zone (pie)
    ax = axes[2]
    z_co2 = [df_hourly[f"zone{z}_co2_tons"].sum() for z in [1,2,3]]
    ax.pie(z_co2, labels=["Z1 Thermal","Z2 PV","Z3 Wind"],
           autopct="%1.1f%%", colors=["#d62728","#ff7f0e","#2ca02c"])
    ax.set_title(f"Daily CO₂ by Zone\nMARL (total {sum(z_co2):.0f} t)")

    plt.tight_layout()
    fig_path = out_dir / "ieee118_marl_results.png"
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    print(f"Wrote {fig_path}")
    plt.close()


if __name__ == "__main__":
    main()
