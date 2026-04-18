#!/usr/bin/env python3
\"\"\"TAO Daily P&L + Yield/Flow Prototype with Bittensor lib\"\"\"

import json
import os
import smtplib
import time
import re
import csv
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import bittensor as bt

# ── Config ───────────────────────────────────────────────────────────────────
COLDKEY      = '5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb'
TAOSTATS_KEY = 'tao-d4074cce-4fc4-4b65-9ca0-421464b75d66:d5a5343b'  # Pro key
RECIPIENT    = 'allen@nhpcorp.com'
ZOHO_EMAIL   = 'luke443@zohomail.com'
ZOHO_PASS    = '@aMk351818!!'
ZOHO_SMTP    = 'smtp.zoho.com'
ZOHO_PORT    = 587

SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), 'snapshot.json')
HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'bt_history.csv')
HEADERS = {'Authorization': TAOSTATS_KEY}
BASE    = 'https://api.taostats.io/api'

# ── Subnet Name Cache ─────────────────────────────────────────────────────────
_subnet_names: dict[int, str] = {}

def get_subnet_name(netuid: int) -> str:
    if netuid in _subnet_names:
        return _subnet_names[netuid]
    try:
        r = requests.get(f"https://taostats.io/subnets/{netuid}", timeout=8)
        match = re.search(r'<title>([\\d.]+)\\s*·\\s*SN\\d+\\s*·\\s*([^·<]+?)·', r.text)
        name = match.group(2).strip() if match else ''
        _subnet_names[netuid] = name
        return name
    except Exception:
        _subnet_names[netuid] = ''
        return ''

# ── Bittensor Chain Data ─────────────────────────────────────────────────────
def get_bt_subnet_data(netuid: int) -> tuple[float, float]:
    \"\"\"subnet_stake (TAO), subnet_daily_em_proxy (TAO, last tau ~1d)\"\"\"
    try:
        sub = bt.subtensor(network='finney')
        stake = float(sub.get_subnet_stake(netuid)) / 1e9
        mg = bt.metagraph(netuid=netuid)
        em_proxy = float(mg.incentive.sum())  # subnet emissions last tau (~daily)
        return stake, em_proxy
    except Exception as e:
        print(f'BT error netuid={netuid}: {e}')
        return 0.0, 0.0

# ── History Append ───────────────────────────────────────────────────────────
def append_history(netuid: int, validator: str, my_stake: float, subnet_stake: float):
    today = datetime.now().strftime('%Y-%m-%d')
    row = [today, netuid, validator, f'{my_stake:.4f}', f'{subnet_stake:.1f}']
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['date', 'netuid', 'validator', 'my_stake', 'subnet_stake'])
        writer.writerow(row)

def get_flows(netuid: int) -> tuple[float, float]:
    \"\"\"24h/7d subnet stake delta from history (negative = outflow)\"\"\"
    if not os.path.isfile(HISTORY_FILE):
        return 0.0, 0.0
    df = pd.read_csv(HISTORY_FILE)
    subnet_df = df[df['netuid'] == netuid].tail(8)  # last 8 days
    if len(subnet_df) < 2:
        return 0.0, 0.0
    flow24 = float(subnet_df.iloc[-1]['subnet_stake']) - float(subnet_df.iloc[-2]['subnet_stake'])
    flow7 = float(subnet_df.iloc[-1]['subnet_stake']) - float(subnet_df.iloc[0]['subnet_stake']) if len(subnet_df) >= 7 else 0.0
    return flow24, flow7

# ── Taostats Helpers (existing) ──────────────────────────────────────────────
def api(endpoint, params=None, retries=3, delay=5):
    url = f\"{BASE}/{endpoint}\"
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except:
            time.sleep(delay)
    return None

def tao_price():
    d = api('price/latest/v1', {'asset': 'tao'})
    if d and d.get('data'):
        p = d['data'][0]
        return float(p['price'])
    return 0

def build_positions(txns):
    positions = {}
    for tx in sorted(txns, key=lambda x: x['timestamp']):
        key = (tx['netuid'], tx['delegate']['ss58'])
        amt_tao = int(tx['amount']) / 1e9
        cost_usd = float(tx['usd'])
        if tx['action'] == 'DELEGATE':
            if key not in positions:
                positions[key] = {'netuid': tx['netuid'], 'validator': tx['delegate_name'], 'tao_staked': 0, 'cost_usd': 0}
            positions[key]['tao_staked'] += amt_tao
            positions[key]['cost_usd'] += cost_usd
        elif tx['action'] == 'UNDELEGATE':
            if key in positions:
                positions[key]['tao_staked'] = max(0, positions[key]['tao_staked'] - amt_tao)
                positions[key]['cost_usd'] = max(0, positions[key]['cost_usd'] - cost_usd)
    return {k: v for k, v in positions.items() if v['tao_staked'] > 0.001}

def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From'] = ZOHO_EMAIL
    msg['To'] = RECIPIENT
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    with smtplib.SMTP(ZOHO_SMTP, ZOHO_PORT) as s:
        s.starttls()
        s.login(ZOHO_EMAIL, ZOHO_PASS)
        s.send_message(msg)
    print('✓ Email sent')

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    print(f'Prototype run: {now}')
    tao = tao_price()
    txns = api('delegation/v1', {'nominator': COLDKEY, 'limit': 100})['data'] if api('delegation/v1', {'nominator': COLDKEY, 'limit': 100'}) else []
    positions = build_positions(txns)
    sorted_pos = sorted(positions.values(), key=lambda x: x['tao_staked'], reverse=True)
    total_tao = sum(p['tao_staked'] for p in positions.values())
    total_cost = sum(p['cost_usd'] for p in positions.values())
    total_usd = total_tao * tao

    body = f'TAO Portfolio Prototype — {now.strftime("%A, %B %d")}\nTAO: ${tao:.2f}\n\nEXISTING P&L SNAPSHOT:\nTotal staked: {total_tao:.4f} TAO (${total_usd:,.0f})\nCost: ${total_cost:,.0f}\n\nNEW YIELD/FLOW:\n'
    for p in sorted_pos:
        netuid = p['netuid']
        subnet_stake, subnet_em_proxy = get_bt_subnet_data(netuid)
        share = p['tao_staked'] / subnet_stake if subnet_stake > 0 else 0
        pos_em_daily = subnet_em_proxy * share  # pro-rata (proxy = last tau ~daily)
        pos_yield_usd = pos_em_daily * tao
        pos_yield_pct = pos_em_daily / p['tao_staked'] * 100 if p['tao_staked'] > 0 else 0
        apr_proxy = (pos_em_daily / p['tao_staked'] * 365) * 100 if p['tao_staked'] > 0 else 0
        flow24, flow7d = get_flows(netuid)
        sn_name = get_subnet_name(netuid)
        body += f'SN{netuid} {sn_name} — {p["validator"]}\nStake: {p["tao_staked"]:.4f} TAO\nDaily em (proxy): {pos_em_daily:.6f} TAO (${pos_yield_usd:.2f}, {pos_yield_pct:.2f}%)\nAPR (proxy): {apr_proxy:.0f}%\n24h flow: {flow24:+.0f} TAO\n7d flow: {flow7d:+.0f} TAO\n\\n'
        append_history(netuid, p['validator'], p['tao_staked'], subnet_stake)

    # Snapshot
    snapshot = {'date': now.strftime('%Y-%m-%d'), 'tao': tao, 'positions': [{'netuid': p['netuid'], 'stake': p['tao_staked']} for p in sorted_pos]}
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(snapshot, f)
    print(body)
    send_email('TAO Prototype Yield/Flow', body)

if __name__ == '__main__':
    main()
