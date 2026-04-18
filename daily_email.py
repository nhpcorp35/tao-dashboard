#!/usr/bin/env python3

import os
import csv
import json
import smtplib
import traceback
from datetime import datetime
from email.mime.text import MIMEText

import pandas as pd
import requests

try:
    import bittensor as bt
except:
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

HEADERS = {
    "accept": "application/json",
    "Authorization": TAOSTATS_KEY
}


# =========================
# HELPERS
# =========================

def safe_float(x, default=0.0):
    try:
        return float(x)
    except:
        return default


# =========================
# PRICE FIX (IMPORTANT)
# =========================

def tao_price():
    urls = [
        "https://api.taostats.io/api/price/latest",
        "https://api.taostats.io/api/price",
    ]

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue

            data = r.json()

            if isinstance(data, dict):
                for key in ["price", "tao_price", "usd", "value"]:
                    if key in data:
                        return safe_float(data[key])

            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                for key in ["price", "tao_price", "usd", "value"]:
                    if key in item:
                        return safe_float(item[key])

        except:
            continue

    raise Exception("❌ Failed to fetch TAO price")


# =========================
# DELEGATIONS
# =========================

def get_delegations():
    url = f"https://api.taostats.io/api/delegation/v1?nominator={COLDKEY}&limit=100"
    r = requests.get(url, headers=HEADERS)
    return r.json()


def build_positions(delegations, tao_usd):
    positions = []

    for d in delegations:
        tao = safe_float(d.get("amount", 0))
        if tao <= 0:
            continue

        positions.append({
            "netuid": d.get("netuid", 0),
            "validator": d.get("validator", "unknown"),
            "tao_staked": tao
        })

    return positions


# =========================
# BITTENSOR FIXED
# =========================

def get_bt_data(netuid):
    if bt is None:
        print(f"BT ERROR SN{netuid}: bittensor not installed")
        return None, None

    try:
        sub = bt.Subtensor(network='finney')
        mg = bt.metagraph(netuid=netuid, subtensor=sub, lite=True)

        stake = float(mg.total_stake) / 1e9

        emissions = getattr(mg, "emissions", None)
        if emissions is None:
            raise Exception("missing emissions")

        try:
            em = float(emissions.sum())
        except:
            em = float(sum(emissions))

        print(f"DEBUG SN{netuid}: stake={stake:.2f}, em={em:.6f}")
        return stake, em

    except Exception as e:
        print(f"BT ERROR SN{netuid}: {e}")
        return None, None


# =========================
# HISTORY
# =========================

def append_history(positions):
    today = datetime.now().strftime('%Y-%m-%d')

    rows = []

    for p in positions:
        stake, em = get_bt_data(p["netuid"])

        if stake is None:
            print(f"SKIP SN{p['netuid']}")
            continue

        rows.append([
            today,
            p["netuid"],
            p["validator"],
            p["tao_staked"],
            stake,
            em
        ])

    if not rows:
        raise Exception("❌ No valid BT rows")

    write_header = not os.path.exists(HISTORY_FILE)

    with open(HISTORY_FILE, "a") as f:
        writer = csv.writer(f)

        if write_header:
            writer.writerow([
                "date", "netuid", "validator",
                "my_stake", "subnet_stake", "subnet_em_epoch"
            ])

        writer.writerows(rows)

    print(f"✓ wrote {len(rows)} rows")


def load_history():
    return pd.read_csv(HISTORY_FILE)


# =========================
# EMAIL
# =========================

def send_email(body):
    msg = MIMEText(body)
    msg["Subject"] = "TAO Report"
    msg["From"] = ZOHO_EMAIL
    msg["To"] = RECIPIENT

    server = smtplib.SMTP("smtp.zoho.com", 587)
    server.starttls()
    server.login(ZOHO_EMAIL, ZOHO_PASS)
    server.sendmail(ZOHO_EMAIL, [RECIPIENT], msg.as_string())
    server.quit()

    print("✓ Email sent")


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

    body = f"TAO Price: ${tao:.2f}\nPositions: {len(positions)}"

    send_email(body)


if __name__ == "__main__":
    main()
