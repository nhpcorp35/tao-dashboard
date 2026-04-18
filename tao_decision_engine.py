#!/usr/bin/env python3

import json
import os
from datetime import datetime

import pandas as pd


HISTORY_FILE = "bt_history.csv"
POSITIONS_FILE = "cost_basis_debug.json"
OUTPUT_FILE = "tao_decisions.json"


def safe_float(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        raise Exception(f"❌ Missing {POSITIONS_FILE}. Run daily_email.py first.")

    with open(POSITIONS_FILE, "r") as f:
        data = json.load(f)

    rows = []
    for p in data:
        rows.append({
            "netuid": int(p.get("netuid", 0)),
            "validator": p.get("validator", "unknown"),
            "tao_staked": safe_float(p.get("tao_staked", 0)),
            "cost_basis_usd": safe_float(p.get("cost_basis_usd", 0)),
            "current_value_usd": safe_float(p.get("current_value_usd", 0)),
            "pnl_usd": safe_float(p.get("pnl_usd", 0)),
            "realized_pnl_usd": safe_float(p.get("realized_pnl_usd", 0)),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise Exception("❌ No open positions in cost_basis_debug.json")

    return df


def load_history():
    if not os.path.exists(HISTORY_FILE):
        raise Exception(f"❌ Missing {HISTORY_FILE}. Run daily_email.py first.")

    df = pd.read_csv(HISTORY_FILE)

    required = {
        "date",
        "netuid",
        "validator",
        "my_stake",
        "subnet_stake",
        "subnet_em_epoch",
    }
    missing = required - set(df.columns)
    if missing:
        raise Exception(f"❌ History schema mismatch. Missing: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["netuid"] = pd.to_numeric(df["netuid"], errors="coerce").fillna(0).astype(int)
    df["my_stake"] = pd.to_numeric(df["my_stake"], errors="coerce").fillna(0.0)
    df["subnet_stake"] = pd.to_numeric(df["subnet_stake"], errors="coerce").fillna(0.0)
    df["subnet_em_epoch"] = pd.to_numeric(df["subnet_em_epoch"], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["date"]).sort_values(["netuid", "date", "validator"])
    return df


def get_subnet_metrics(df, netuid):
    subnet_df = df[df["netuid"] == netuid].copy()

    valid = subnet_df[
        (subnet_df["subnet_stake"] > 0) &
        (subnet_df["subnet_em_epoch"] > 0)
    ].copy()

    if valid.empty:
        return {
            "subnet_stake": 0.0,
            "subnet_em_epoch": 0.0,
            "daily_subnet_em": 0.0,
            "apr_signal_pct": 0.0,
            "flow_24h": 0.0,
            "flow_7d": 0.0,
            "history_days": 0,
        }

    # Collapse to one row per day using last valid reading
    daily = (
        valid.groupby("date", as_index=False)
        .agg({
            "subnet_stake": "last",
            "subnet_em_epoch": "last",
        })
        .sort_values("date")
        .reset_index(drop=True)
    )

    latest = daily.iloc[-1]
    subnet_stake = safe_float(latest["subnet_stake"])
    em_epoch = safe_float(latest["subnet_em_epoch"])

    epochs_per_day = 20.0
    daily_subnet_em = em_epoch * epochs_per_day if em_epoch > 0 else 0.0

    apr_signal_pct = 0.0
    if subnet_stake > 0 and daily_subnet_em > 0:
        apr_signal_pct = (daily_subnet_em * 365.0 / subnet_stake) * 100.0

    flow_24h = 0.0
    flow_7d = 0.0

    if len(daily) >= 2:
        flow_24h = safe_float(daily.iloc[-1]["subnet_stake"]) - safe_float(daily.iloc[-2]["subnet_stake"])

    if len(daily) >= 8:
        flow_7d = safe_float(daily.iloc[-1]["subnet_stake"]) - safe_float(daily.iloc[-8]["subnet_stake"])
    elif len(daily) >= 2:
        flow_7d = safe_float(daily.iloc[-1]["subnet_stake"]) - safe_float(daily.iloc[0]["subnet_stake"])

    return {
        "subnet_stake": subnet_stake,
        "subnet_em_epoch": em_epoch,
        "daily_subnet_em": daily_subnet_em,
        "apr_signal_pct": apr_signal_pct,
        "flow_24h": flow_24h,
        "flow_7d": flow_7d,
        "history_days": len(daily),
    }


def get_position_yield_tao(position_tao, subnet_stake, daily_subnet_em):
    if position_tao <= 0 or subnet_stake <= 0 or daily_subnet_em <= 0:
        return 0.0
    return daily_subnet_em * (position_tao / subnet_stake)


def score_position(netuid, apr_signal_pct, flow_24h, flow_7d, pnl_pct, position_size, history_days):
    if netuid == 0:
        return {
            "score": 0,
            "action": "Hold",
            "reason": f"Root position at ${position_size:,.0f}; treated as core yield anchor, not ranked like alpha subnets.",
        }

    score = 0
    reasons = []

    if apr_signal_pct >= 80:
        score += 3
        reasons.append("very high subnet APR signal")
    elif apr_signal_pct >= 40:
        score += 2
        reasons.append("strong subnet APR signal")
    elif apr_signal_pct >= 18:
        score += 1
        reasons.append("healthy subnet APR signal")
    elif apr_signal_pct < 6:
        score -= 2
        reasons.append("weak subnet APR signal")
    elif apr_signal_pct < 12:
        score -= 1
        reasons.append("soft subnet APR signal")

    if history_days >= 2:
        if flow_24h > 50000:
            score += 1
            reasons.append("positive 24h flow")
        elif flow_24h < -50000:
            score -= 1
            reasons.append("negative 24h flow")

        if flow_7d > 150000:
            score += 2
            reasons.append("strong 7d capital inflow")
        elif flow_7d > 0:
            score += 1
            reasons.append("positive 7d flow")
        elif flow_7d < -150000:
            score -= 2
            reasons.append("strong 7d capital outflow")
        elif flow_7d < 0:
            score -= 1
            reasons.append("negative 7d flow")
    else:
        reasons.append("limited flow history")

    if position_size < 300 and score >= 3:
        action = "Buy / Add"
        reasons.append("position still small")
    elif position_size >= 1000 and score >= 3:
        action = "Hold"
        reasons.append("already meaningful size")
    elif score >= 2:
        action = "Hold"
    elif score <= -3:
        action = "Trim / Sell"
    elif score <= -1:
        action = "Watch"
    else:
        action = "Hold"

    if pnl_pct < -20 and action in ("Watch", "Trim / Sell"):
        reasons.append("deep unrealized loss")
    elif pnl_pct > 25 and action == "Watch":
        reasons.append("protect gains if conviction fades")

    return {
        "score": score,
        "action": action,
        "reason": "; ".join(reasons[:3]) if reasons else "balanced setup",
    }


def main():
    positions_df = load_positions()
    history_df = load_history()

    subnet_cache = {}
    for netuid in sorted(positions_df["netuid"].unique().tolist()):
        subnet_cache[netuid] = get_subnet_metrics(history_df, netuid)

    decisions = []

    for _, row in positions_df.iterrows():
        netuid = int(row["netuid"])
        validator = row["validator"]
        tao_staked = safe_float(row["tao_staked"])
        cost_basis_usd = safe_float(row["cost_basis_usd"])
        current_value_usd = safe_float(row["current_value_usd"])
        pnl_usd = safe_float(row["pnl_usd"])
        pnl_pct = (pnl_usd / cost_basis_usd * 100.0) if cost_basis_usd > 0 else 0.0

        subnet = subnet_cache[netuid]

        your_daily_yield_tao = get_position_yield_tao(
            tao_staked,
            subnet["subnet_stake"],
            subnet["daily_subnet_em"],
        )

        your_apr_proxy_pct = (
            (your_daily_yield_tao * 365.0 / tao_staked) * 100.0
            if tao_staked > 0 else 0.0
        )

        scored = score_position(
            netuid=netuid,
            apr_signal_pct=subnet["apr_signal_pct"],
            flow_24h=subnet["flow_24h"],
            flow_7d=subnet["flow_7d"],
            pnl_pct=pnl_pct,
            position_size=current_value_usd,
            history_days=subnet["history_days"],
        )

        decisions.append({
            "netuid": netuid,
            "name": validator,
            "action": scored["action"],
            "score": scored["score"],
            "reason": scored["reason"],
            "tao_staked": round(tao_staked, 6),
            "current_value_usd": round(current_value_usd, 2),
            "cost_basis_usd": round(cost_basis_usd, 2),
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 2),
            "your_daily_yield_tao": round(your_daily_yield_tao, 6),
            "your_apr_proxy_pct": round(your_apr_proxy_pct, 2),
            "subnet_stake": round(subnet["subnet_stake"], 4),
            "subnet_em_epoch": round(subnet["subnet_em_epoch"], 6),
            "daily_subnet_em": round(subnet["daily_subnet_em"], 4),
            "subnet_apr_signal_pct": round(subnet["apr_signal_pct"], 2),
            "flow_24h": round(subnet["flow_24h"], 2),
            "flow_7d": round(subnet["flow_7d"], 2),
            "history_days": int(subnet["history_days"]),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        })

    action_order = {
        "Buy / Add": 0,
        "Hold": 1,
        "Watch": 2,
        "Trim / Sell": 3,
    }

    decisions.sort(
        key=lambda x: (
            action_order.get(x["action"], 99),
            -x["score"],
            -x["current_value_usd"],
        )
    )

    with open(OUTPUT_FILE, "w") as f:
        json.dump(decisions, f, indent=2)

    print(f"Wrote {len(decisions)} decisions to {OUTPUT_FILE}")

    for d in decisions:
        print(
            f"SN{d['netuid']} | {d['name']} | {d['action']} | "
            f"Subnet APR {d['subnet_apr_signal_pct']:.2f}% | "
            f"24h {d['flow_24h']:+,.0f} | 7d {d['flow_7d']:+,.0f} | "
            f"${d['current_value_usd']:,.0f}"
        )


if __name__ == "__main__":
    main()