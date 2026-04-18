#!/usr/bin/env python3
"""
TAO Daily P&L + Yield/Flow with Bittensor
"""

import os
import csv
import json
import smtplib
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

try:
    import bittensor as bt
except Exception:
    bt = None


# =========================
# CONFIG
# =========================

COLDKEY = os.getenv("TAO_COLDKEY", "YOUR_COLDKEY")
TAOSTATS_KEY = os.getenv("TAOSTATS_KEY", "YOUR_TAOSTATS_KEY")
RECIPIENT = os.getenv("TAO_REPORT_RECIPIENT", "allen@nhpcorp.com")

ZOHO_EMAIL = os.getenv("ZOHO_EMAIL", "YOUR_ZOHO_EMAIL")
ZOHO_PASS = os.getenv("ZOHO_PASS", "YOUR_ZOHO_PASSWORD")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.zoho.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

HISTORY_FILE = "bt_history.csv"
SNAPSHOT_FILE = "snapshot.json"

TAOSTATS_BASE = "https://api.taostats.io/api"
HEADERS = {
    "accept": "application/json",
    "Authorization": TAOSTATS_KEY,
    "Content-Type": "application/json",
    "User-Agent": "tao-dashboard/1.0",
}


# =========================
# HELPERS
# =========================

def safe_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def tao_price() -> float:
    url = f"{TAOSTATS_BASE}/price/latest"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        for key in ("price", "tao_price", "usd", "value"):
            if key in data:
                return safe_float(data[key])

    if isinstance(data, list) and data:
        item = data[0]
        for key in ("price", "tao_price", "usd", "value"):
            if key in item:
                return safe_float(item[key])

    raise ValueError(f"Unexpected TAO price response: {data}")


def get_delegations() -> List[dict]:
    url = f"{TAOSTATS_BASE}/delegation/v1?nominator={COLDKEY}&limit=100"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "items", "delegations"):
            if key in data and isinstance(data[key], list):
                return data[key]

    return []


def build_positions(delegations: List[dict], tao_usd: float) -> List[dict]:
    """
    Tries to be resilient to Taostats field naming drift.
    """
    positions = []

    for row in delegations:
        netuid = row.get("netuid", row.get("subnet_id", 0))
        validator = (
            row.get("validator_name")
            or row.get("validator")
            or row.get("display_name")
            or row.get("hotkey_name")
            or "unknown"
        )

        tao_staked = safe_float(
            row.get("tao_staked", row.get("stake", row.get("amount", 0.0)))
        )

        cost_basis = safe_float(
            row.get("cost_basis_usd", row.get("cost_basis", row.get("total_cost", 0.0)))
        )

        if tao_staked <= 0:
            continue

        current_value = tao_staked * tao_usd
        pnl_usd = current_value - cost_basis
        pnl_pct = (pnl_usd / cost_basis * 100.0) if cost_basis > 0 else 0.0

        positions.append(
            {
                "netuid": int(netuid),
                "validator": validator,
                "tao_staked": tao_staked,
                "cost_basis_usd": cost_basis,
                "current_value_usd": current_value,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
            }
        )

    positions.sort(key=lambda x: x["current_value_usd"], reverse=True)
    return positions


def get_bt_data(netuid: int) -> Tuple[Optional[float], Optional[float]]:
    """
    Returns:
      subnet_stake_tao, subnet_em_epoch

    Important:
    - Explicitly binds to finney subtensor
    - Never returns fake zero values on failure
    """
    if bt is None:
        print(f"BT ERROR SN{netuid}: bittensor is not installed in this environment")
        return None, None

    try:
        sub = bt.Subtensor(network="finney")
        mg = bt.metagraph(netuid=netuid, subtensor=sub, lite=True)

        stake = float(mg.total_stake) / 1e9

        emissions = getattr(mg, "emissions", None)
        if emissions is None:
            raise Exception(f"SN{netuid}: missing emissions on metagraph")

        try:
            em_proxy = float(emissions.sum())
        except Exception:
            em_proxy = float(sum(emissions))

        print(f"DEBUG SN{netuid}: stake={stake:,.4f}, emissions_epoch={em_proxy:.6f}")
        return stake, em_proxy

    except Exception as e:
        print(f"BT ERROR SN{netuid}: {e}")
        traceback.print_exc()
        return None, None


def ensure_history_file() -> None:
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["date", "netuid", "validator", "my_stake", "subnet_stake", "subnet_em_epoch"]
            )


def append_history(positions: List[dict]) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    ensure_history_file()

    rows = []
    for p in positions:
        netuid = p["netuid"]
        subnet_stake, em_proxy = get_bt_data(netuid)

        if subnet_stake is None or em_proxy is None:
            print(f"SKIP SN{netuid}: failed Bittensor fetch")
            continue

        row = [
            today,
            netuid,
            p["validator"],
            p["tao_staked"],
            subnet_stake,
            em_proxy,
        ]
        rows.append(row)

    if not rows:
        raise Exception("❌ No valid Bittensor rows fetched — refusing to write zero/empty history")

    with open(HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"✓ Wrote {len(rows)}/{len(positions)} rows to {HISTORY_FILE}")
    return len(rows)


def load_history() -> pd.DataFrame:
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame()

    df = pd.read_csv(HISTORY_FILE)

    required = {"date", "netuid", "validator", "my_stake", "subnet_stake", "subnet_em_epoch"}
    missing = required - set(df.columns)
    if missing:
        raise Exception(f"❌ History schema mismatch. Missing columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["netuid"] = pd.to_numeric(df["netuid"], errors="coerce").fillna(0).astype(int)
    df["my_stake"] = pd.to_numeric(df["my_stake"], errors="coerce").fillna(0.0)
    df["subnet_stake"] = pd.to_numeric(df["subnet_stake"], errors="coerce").fillna(0.0)
    df["subnet_em_epoch"] = pd.to_numeric(df["subnet_em_epoch"], errors="coerce").fillna(0.0)

    if df["subnet_em_epoch"].sum() == 0:
        print("WARNING: all subnet_em_epoch values are zero in history")

    return df


def get_flows(df: pd.DataFrame, netuid: int) -> Tuple[float, float]:
    subnet_df = df[df["netuid"] == netuid].sort_values("date")
    if subnet_df.empty:
        return 0.0, 0.0

    daily = subnet_df.groupby("date", as_index=False)["subnet_stake"].last().sort_values("date")
    if len(daily) < 2:
        return 0.0, 0.0

    flow_24h = safe_float(daily.iloc[-1]["subnet_stake"]) - safe_float(daily.iloc[-2]["subnet_stake"])

    if len(daily) >= 8:
        flow_7d = safe_float(daily.iloc[-1]["subnet_stake"]) - safe_float(daily.iloc[-8]["subnet_stake"])
    else:
        flow_7d = safe_float(daily.iloc[-1]["subnet_stake"]) - safe_float(daily.iloc[0]["subnet_stake"])

    return flow_24h, flow_7d


def get_apr_metrics(df: pd.DataFrame, netuid: int, your_stake: float) -> Dict[str, float]:
    subnet_df = df[df["netuid"] == netuid].sort_values("date")
    if subnet_df.empty or your_stake <= 0:
        return {
            "daily_subnet_em": 0.0,
            "your_daily_yield_tao": 0.0,
            "apr_proxy_pct": 0.0,
        }

    latest = subnet_df.iloc[-1]
    subnet_stake = safe_float(latest["subnet_stake"])
    em_epoch = safe_float(latest["subnet_em_epoch"])

    if subnet_stake <= 0 or em_epoch <= 0:
        return {
            "daily_subnet_em": 0.0,
            "your_daily_yield_tao": 0.0,
            "apr_proxy_pct": 0.0,
        }

    epochs_per_day = 20.0  # ~72 min epochs
    daily_subnet_em = em_epoch * epochs_per_day
    share = your_stake / subnet_stake
    your_daily_yield_tao = daily_subnet_em * share
    apr_proxy_pct = (your_daily_yield_tao * 365.0 / your_stake) * 100.0 if your_stake > 0 else 0.0

    return {
        "daily_subnet_em": daily_subnet_em,
        "your_daily_yield_tao": your_daily_yield_tao,
        "apr_proxy_pct": apr_proxy_pct,
    }


def save_snapshot(tao_usd: float, positions: List[dict]) -> None:
    total_tao = sum(p["tao_staked"] for p in positions)
    total_usd = sum(p["current_value_usd"] for p in positions)
    total_cost = sum(p["cost_basis_usd"] for p in positions)

    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tao": round(tao_usd, 2),
        "total_tao": round(total_tao, 6),
        "total_usd": round(total_usd, 2),
        "total_cost": round(total_cost, 2),
    }

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"SNAPSHOT: {json.dumps(snapshot)}")


def fmt_usd(x: float) -> str:
    return f"${x:,.2f}"


def fmt_pct(x: float) -> str:
    return f"{x:.1f}%"


def build_email_body(tao_usd: float, positions: List[dict], df: pd.DataFrame) -> str:
    total_tao = sum(p["tao_staked"] for p in positions)
    total_usd = sum(p["current_value_usd"] for p in positions)
    total_cost = sum(p["cost_basis_usd"] for p in positions)
    pnl_usd = total_usd - total_cost

    lines = []
    lines.append(f"TAO Portfolio — {datetime.now().strftime('%A, %B %d, %Y')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("TAO PRICE")
    lines.append(f"  Current:  {fmt_usd(tao_usd)}")
    lines.append("")
    lines.append("PORTFOLIO SNAPSHOT")
    lines.append(f"  TAO Staked:       {total_tao:.4f} TAO")
    lines.append(f"  Current Value:    {fmt_usd(total_usd)}")
    lines.append(f"  Total Cost Basis: {fmt_usd(total_cost)}")
    lines.append(f"  Unrealized P&L:   {fmt_usd(pnl_usd)}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("ACTIVE POSITIONS")
    lines.append("")

    for p in positions:
        lines.append(f"  SN{p['netuid']} — {p['validator']}")
        lines.append(f"    Staked:   {p['tao_staked']:.4f} TAO  ({fmt_usd(p['current_value_usd'])})")
        lines.append(f"    Cost:     {fmt_usd(p['cost_basis_usd'])}")
        lines.append(f"    P&L:      {fmt_usd(p['pnl_usd'])} ({fmt_pct(p['pnl_pct'])})")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("SUBNET FLOW + YIELD (ESTIMATES)")
    lines.append("")

    for p in positions:
        metrics = get_apr_metrics(df, p["netuid"], p["tao_staked"])
        flow_24h, flow_7d = get_flows(df, p["netuid"])

        your_daily_yield_usd = metrics["your_daily_yield_tao"] * tao_usd

        lines.append(f"SN{p['netuid']} — {p['validator']}")
        lines.append(f"Stake: {p['tao_staked']:.4f} TAO")
        lines.append(
            f"Est. daily subnet em: {metrics['daily_subnet_em']:.4f} TAO (epoch x20)"
        )
        lines.append(
            f"Est. your daily yield: {metrics['your_daily_yield_tao']:.6f} TAO / {fmt_usd(your_daily_yield_usd)}"
        )
        lines.append(f"Est. APR proxy: {metrics['apr_proxy_pct']:.2f}%")
        lines.append(f"24h flow (derived): {flow_24h:+,.2f} TAO")
        lines.append(f"7d flow (derived): {flow_7d:+,.2f} TAO")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("Generated by daily_email.py")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}")

    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = ZOHO_EMAIL
    msg["To"] = RECIPIENT

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(ZOHO_EMAIL, ZOHO_PASS)
        server.sendmail(ZOHO_EMAIL, [RECIPIENT], msg.as_string())

    print("✓ Email sent")


def main() -> None:
    tao_usd = tao_price()
    print(f"TAO: ${tao_usd:.2f} (Taostats)")

    delegations = get_delegations()
    print(f"DELEGATIONS: {len(delegations)} txns fetched")

    positions = build_positions(delegations, tao_usd)
    print(f"POSITIONS: {len(positions)} active ({sum(p['tao_staked'] for p in positions):.4f} TAO total)")

    append_history(positions)
    df = load_history()

    body = build_email_body(tao_usd, positions, df)
    subject = f"TAO Portfolio — {datetime.now().strftime('%Y-%m-%d')}"
    send_email(subject, body)

    save_snapshot(tao_usd, positions)


if __name__ == "__main__":
    main()