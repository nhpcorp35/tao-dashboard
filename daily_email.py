#!/usr/bin/env python3

import os
import csv
import json
import smtplib
import traceback
from collections import defaultdict
from datetime import datetime
from email.mime.text import MIMEText

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
TAOSTATS_KEY = os.getenv("TAOSTATS_KEY", "")
RECIPIENT = os.getenv("TAO_REPORT_RECIPIENT", "allen@nhpcorp.com")

ZOHO_EMAIL = os.getenv("ZOHO_EMAIL", "")
ZOHO_PASS = os.getenv("ZOHO_PASS", "")

HISTORY_FILE = "bt_history.csv"
SNAPSHOT_FILE = "snapshot.json"

BASE = "https://api.taostats.io/api"
HEADERS = {
    "accept": "application/json",
    "Authorization": TAOSTATS_KEY,
}


# =========================
# HELPERS
# =========================

def safe_float(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default


def fmt_usd(x):
    return f"${x:,.2f}"


def extract_amount(x):
    if x is None:
        return None

    try:
        if hasattr(x, "tao"):
            return float(x.tao)
    except Exception:
        pass

    try:
        if hasattr(x, "item"):
            v = x.item()
            if hasattr(v, "tao"):
                return float(v.tao)
            return float(v)
    except Exception:
        pass

    try:
        return float(x)
    except Exception:
        pass

    try:
        vals = []
        for v in x:
            if hasattr(v, "tao"):
                vals.append(float(v.tao))
            elif hasattr(v, "item"):
                iv = v.item()
                if hasattr(iv, "tao"):
                    vals.append(float(iv.tao))
                else:
                    vals.append(float(iv))
            else:
                vals.append(float(v))
        return float(sum(vals))
    except Exception:
        return None


def first_nonzero_attr(obj, names):
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            num = extract_amount(val)
            if num is not None and abs(num) > 0:
                return num, name
    return None, None


def normalize_tao_amount(x):
    """
    TaoStats amount fields are in raw 1e9 units in this payload.
    """
    v = safe_float(x, 0.0)
    if v <= 0:
        return 0.0
    if v > 1_000_000:
        return v / 1e9
    return v


def normalize_usd_amount(x):
    return safe_float(x, 0.0)


def event_sort_key(d):
    return (
        d.get("timestamp", ""),
        d.get("block_number", 0),
        d.get("extrinsic_id", ""),
        d.get("id", ""),
    )


# =========================
# TAO PRICE
# =========================

def tao_price():
    urls = [
        f"{BASE}/price/latest",
        f"{BASE}/price",
    ]

    last_err = None

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json()

            if isinstance(data, dict):
                for key in ("price", "tao_price", "usd", "value"):
                    if key in data:
                        return safe_float(data[key])

                for outer in ("data", "result"):
                    if outer in data and isinstance(data[outer], dict):
                        for key in ("price", "tao_price", "usd", "value"):
                            if key in data[outer]:
                                return safe_float(data[outer][key])

            if isinstance(data, list) and data:
                item = data[0]
                for key in ("price", "tao_price", "usd", "value"):
                    if key in item:
                        return safe_float(item[key])

        except Exception as e:
            last_err = e

    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, "r") as f:
                snap = json.load(f)
            if "tao" in snap:
                print("Using snapshot fallback price")
                return safe_float(snap["tao"])
        except Exception:
            pass

    raise Exception(f"❌ Failed to fetch TAO price. Last error: {last_err}")


# =========================
# TAOSTATS DELEGATION EVENTS
# =========================

def get_delegations():
    url = f"{BASE}/delegation/v1?nominator={COLDKEY}&limit=100"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "results", "items", "delegations"):
            if key in data and isinstance(data[key], list):
                return data[key]

    return []


def build_positions(delegations, tao_usd):
    """
    Rebuild current positions from DELEGATE / UNDELEGATE event history
    using average-cost accounting.
    """
    events = sorted(delegations, key=event_sort_key)

    book = defaultdict(lambda: {
        "netuid": 0,
        "validator": "unknown",
        "delegate_ss58": "",
        "tao_staked": 0.0,
        "cost_basis_usd": 0.0,
        "realized_pnl_usd": 0.0,
    })

    for d in events:
        action = (d.get("action") or "").upper().strip()
        netuid = int(d.get("netuid", 0))
        validator = d.get("delegate_name") or d.get("validator_name") or d.get("validator") or "unknown"
        delegate_ss58 = (d.get("delegate") or {}).get("ss58", "")

        key = (netuid, delegate_ss58 or validator)

        tao_amt = normalize_tao_amount(d.get("amount", 0))
        usd_amt = normalize_usd_amount(d.get("usd", 0))

        pos = book[key]
        pos["netuid"] = netuid
        pos["validator"] = validator
        pos["delegate_ss58"] = delegate_ss58

        if tao_amt <= 0:
            continue

        # Buy / add
        if action == "DELEGATE":
            pos["tao_staked"] += tao_amt
            pos["cost_basis_usd"] += usd_amt

        # Reduce / sell
        elif action == "UNDELEGATE":
            current_qty = pos["tao_staked"]
            current_cost = pos["cost_basis_usd"]

            if current_qty <= 0:
                continue

            sell_qty = min(tao_amt, current_qty)
            avg_cost_per_tao = current_cost / current_qty if current_qty > 0 else 0.0
            removed_cost = avg_cost_per_tao * sell_qty

            proceeds = usd_amt
            pos["realized_pnl_usd"] += (proceeds - removed_cost)

            pos["tao_staked"] = max(0.0, current_qty - sell_qty)
            pos["cost_basis_usd"] = max(0.0, current_cost - removed_cost)

    positions = []

    for _, p in book.items():
        tao = p["tao_staked"]
        if tao <= 0:
            continue

        current_value = tao * tao_usd
        cost_basis = p["cost_basis_usd"]
        pnl_usd = current_value - cost_basis
        pnl_pct = (pnl_usd / cost_basis * 100.0) if cost_basis > 0 else 0.0

        positions.append({
            "netuid": p["netuid"],
            "validator": p["validator"],
            "tao_staked": tao,
            "cost_basis_usd": cost_basis,
            "current_value_usd": current_value,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "realized_pnl_usd": p["realized_pnl_usd"],
        })

    positions.sort(key=lambda x: x["current_value_usd"], reverse=True)

    debug = []
    for p in positions:
        debug.append({
            "netuid": p["netuid"],
            "validator": p["validator"],
            "tao_staked": round(p["tao_staked"], 6),
            "cost_basis_usd": round(p["cost_basis_usd"], 2),
            "current_value_usd": round(p["current_value_usd"], 2),
            "pnl_usd": round(p["pnl_usd"], 2),
            "realized_pnl_usd": round(p["realized_pnl_usd"], 2),
        })

    with open("delegations_raw.json", "w") as f:
        json.dump(events, f, indent=2)
    print("Wrote delegations_raw.json")

    with open("cost_basis_debug.json", "w") as f:
        json.dump(debug, f, indent=2)
    print("Wrote cost_basis_debug.json")

    found_cost = sum(1 for p in positions if p["cost_basis_usd"] > 0)
    print(f"COST BASIS FOUND: {found_cost}/{len(positions)} positions")

    return positions


# =========================
# BITTENSOR SUBNET DATA
# =========================

def get_bt_data(netuid):
    if bt is None:
        print(f"BT ERROR SN{netuid}: bittensor not installed")
        return None, None

    try:
        sub = bt.Subtensor(network="finney")

        try:
            meta_info = sub.get_metagraph_info(netuid=netuid)
        except Exception:
            meta_info = None

        if meta_info is not None:
            stake, stake_src = first_nonzero_attr(
                meta_info,
                [
                    "total_stake",
                    "stake",
                    "alpha_stake",
                    "tao_stake",
                    "alpha_in",
                    "tao_in",
                ],
            )

            em, em_src = first_nonzero_attr(
                meta_info,
                [
                    "emission",
                    "subnet_emission",
                    "emissions",
                    "alpha_out_emission",
                    "alpha_in_emission",
                    "tao_in_emission",
                ],
            )

            if stake is not None and em is not None:
                print(
                    f"DEBUG SN{netuid}: "
                    f"stake={stake:.4f}, em={em:.6f}, "
                    f"src=meta_info.{stake_src}/meta_info.{em_src}"
                )
                return stake, em

        try:
            mg = bt.metagraph(netuid=netuid, subtensor=sub, lite=False)
        except TypeError:
            mg = bt.metagraph(netuid=netuid, subtensor=sub)

        total_stake_obj = getattr(mg, "total_stake", None)
        if total_stake_obj is None:
            total_stake_obj = getattr(mg, "stake", None)

        emission_obj = getattr(mg, "emission", None)
        if emission_obj is None:
            emission_obj = getattr(mg, "emissions", None)

        stake = extract_amount(total_stake_obj)
        em = extract_amount(emission_obj)

        if stake is None or em is None:
            stake_attrs = [a for a in dir(mg) if "stake" in a.lower()]
            em_attrs = [a for a in dir(mg) if "em" in a.lower()]
            raise Exception(
                f"unable to parse metagraph fields; "
                f"stake_attrs={stake_attrs[:10]} em_attrs={em_attrs[:10]}"
            )

        print(
            f"DEBUG SN{netuid}: "
            f"stake={stake:.4f}, em={em:.6f}, "
            f"src=metagraph.total_stake/metagraph.emission, "
            f"stake_type={type(total_stake_obj)}, em_type={type(emission_obj)}"
        )
        return stake, em

    except Exception as e:
        print(f"BT ERROR SN{netuid}: {e}")
        traceback.print_exc()
        return None, None


# =========================
# HISTORY
# =========================

def ensure_history_file():
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "date",
                "netuid",
                "validator",
                "my_stake",
                "subnet_stake",
                "subnet_em_epoch",
            ])


def append_history(positions):
    today = datetime.now().strftime("%Y-%m-%d")
    ensure_history_file()

    rows = []
    bt_cache = {}

    unique_netuids = sorted({int(p["netuid"]) for p in positions})

    for netuid in unique_netuids:
        bt_cache[netuid] = get_bt_data(netuid)

    for p in positions:
        stake, em = bt_cache.get(p["netuid"], (None, None))

        if stake is None or em is None:
            print(f"SKIP SN{p['netuid']}: failed BT fetch")
            continue

        rows.append([
            today,
            p["netuid"],
            p["validator"],
            p["tao_staked"],
            stake,
            em,
        ])

    if not rows:
        raise Exception("❌ No valid BT rows")

    with open(HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"✓ wrote {len(rows)} rows")


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame()

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

    return df


def get_flows(df, netuid):
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


def get_apr_metrics(df, netuid, your_stake):
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

    epochs_per_day = 20.0
    daily_subnet_em = em_epoch * epochs_per_day
    share = your_stake / subnet_stake
    your_daily_yield_tao = daily_subnet_em * share
    apr_proxy_pct = (your_daily_yield_tao * 365.0 / your_stake) * 100.0 if your_stake > 0 else 0.0

    return {
        "daily_subnet_em": daily_subnet_em,
        "your_daily_yield_tao": your_daily_yield_tao,
        "apr_proxy_pct": apr_proxy_pct,
    }


def save_snapshot(tao_usd, positions):
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


# =========================
# EMAIL BODY
# =========================

def build_email_body(tao_usd, positions, df):
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
        lines.append(f"    P&L:      {fmt_usd(p['pnl_usd'])} ({p['pnl_pct']:.1f}%)")
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
        lines.append(f"Est. daily subnet em: {metrics['daily_subnet_em']:.4f} TAO (epoch x20)")
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
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


def send_email(subject, body):
    if not ZOHO_EMAIL or not ZOHO_PASS:
        print("EMAIL SKIPPED: missing ZOHO_EMAIL or ZOHO_PASS")
        return False

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = ZOHO_EMAIL
    msg["To"] = RECIPIENT

    try:
        with smtplib.SMTP("smtp.zoho.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(ZOHO_EMAIL, ZOHO_PASS)
            server.sendmail(ZOHO_EMAIL, [RECIPIENT], msg.as_string())

        print("✓ Email sent")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"EMAIL AUTH FAILED: {e}")
        print("TIP: verify ZOHO_EMAIL is the full Zoho mailbox address and ZOHO_PASS is the Zoho SMTP/app password.")
        return False

    except Exception as e:
        print(f"EMAIL SEND FAILED: {e}")
        traceback.print_exc()
        return False


# =========================
# MAIN
# =========================

def main():
    tao = tao_price()
    print(f"TAO: ${tao:.2f}")

    delegations = get_delegations()
    print(f"DELEGATIONS: {len(delegations)}")

    positions = build_positions(delegations, tao)
    print(f"POSITIONS: {len(positions)}")

    append_history(positions)
    df = load_history()

    subject = f"TAO Portfolio — {datetime.now().strftime('%Y-%m-%d')}"
    body = build_email_body(tao, positions, df)

    email_ok = send_email(subject, body)
    if not email_ok:
        with open("last_tao_report.txt", "w") as f:
            f.write(body)
        print("Saved report locally to last_tao_report.txt")

    save_snapshot(tao, positions)


if __name__ == "__main__":
    main()