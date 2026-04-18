#!/usr/bin/env python3
"""TAO Daily P&L + Yield/Flow with Bittensor"""

import json
import os
import smtplib
import time
import re
import csv
import pandas as pd
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import bittensor as bt
import traceback

# Config
COLDKEY      = '5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb'
TAOSTATS_KEY = 'tao-d4074cce-4fc4-4b65-9ca0-421464b75d66:d5a5343b'
RECIPIENT    = 'allen@nhpcorp.com'
ZOHO_EMAIL   = 'luke443@zohomail.com'
ZOHO_PASS    = '@aMk351818!!'
ZOHO_SMTP    = 'smtp.zoho.com'
ZOHO_PORT    = 587

SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), 'snapshot.json')
HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'bt_history.csv')
HEADERS = {'Authorization': TAOSTATS_KEY}
BASE    = 'https://api.taostats.io/api'

_subnet_names = {}

def get_subnet_name(netuid):
    if netuid in _subnet_names:
        return _subnet_names[netuid]
    try:
        r = requests.get(f'https://taostats.io/subnets/{netuid}', timeout=8)
        match = re.search(r'<title>([\d.]+) · SN\d+ · ([^·<]+?) ·', r.text)
        name = match.group(2).strip() if match else f'SN{netuid}'
        _subnet_names[netuid] = name
        return name
    except:
        return f'SN{netuid}'

def get_bt_data(netuid):
    try:
#        sub = bt.Subtensor(network='finney')
        stake = float(mg.total_stake) / 1e9
        mg = bt.Metagraph(netuid=netuid, lite=True)
        em_proxy = float(mg.emissions.sum())  # TOTAL TAO emitted to subnet LAST EPOCH ONLY (72min)
        print(f'DEBUG SN{netuid}: stake={stake:,.0f}T, emissions_epoch={em_proxy:.4f}TAO (72min epoch), incentive_sum={float(mg.incentive.sum()):.4f} (norm)')
        return stake, em_proxy
    except Exception as e:
        print(f'BT ERROR SN{netuid}: {e}')
        import traceback
        traceback.print_exc()
        return 0.0, 0.0

def append_history(positions):
    today = datetime.now().strftime('%Y-%m-%d')
    rows = []
    for p in positions:
        netuid = p['netuid']
        subnet_stake, em_proxy = get_bt_data(netuid)
        row = [today, netuid, p['validator'], p['tao_staked'], subnet_stake, em_proxy]
        rows.append(row)
    with open(HISTORY_FILE, 'a') as f:
        writer = csv.writer(f)
        if os.path.getsize(HISTORY_FILE) == 0:
            writer.writerow(['date', 'netuid', 'validator', 'my_stake', 'subnet_stake', 'subnet_em_epoch'])
        writer.writerows(rows)

def get_flows(netuid):
    if not os.path.exists(HISTORY_FILE):
        return 0, 0
    df = pd.read_csv(HISTORY_FILE)
    subnet_df = df[df['netuid'] == netuid].sort_values('date').tail(8)
    if len(subnet_df) < 2:
        return 0, 0
    flow24 = subnet_df.iloc[-1]['subnet_stake'] - subnet_df.iloc[-2]['subnet_stake']
    flow7 = subnet_df.iloc[-1]['subnet_stake'] - subnet_df.iloc[0]['subnet_stake'] if len(subnet_df) >= 8 else 0
    return flow24, flow7

def get_apr_metrics(netuid, your_stake):
    """Return spot_apr, smooth_apr (or None if <7d data)"""
    if not os.path.exists(HISTORY_FILE):
        return 0, None
    df = pd.read_csv(HISTORY_FILE)
    df_net = df[df['netuid'] == netuid]
    if len(df_net) < 1:
        return 0, None
    subnet_stake, em_proxy = get_bt_data(netuid)
    share = your_stake / subnet_stake if subnet_stake > 0 else 0
    EPOCHS_PER_DAY = 20
    spot_daily_pct = (em_proxy * EPOCHS_PER_DAY * share / your_stake * 100) if your_stake > 0 else 0
    spot_apr = spot_daily_pct * 365

    daily_em = df_net.groupby('date')['subnet_em_epoch'].mean()
    daily_stake = df_net.groupby('date')['subnet_stake'].mean()
    if len(daily_em) < 7:
        return spot_apr, None
    smooth_em_epoch = daily_em.tail(7).mean()
    avg_subnet_stake = daily_stake.tail(7).mean()
    avg_share = your_stake / avg_subnet_stake if avg_subnet_stake > 0 else 0
    smooth_daily_pct = (smooth_em_epoch * EPOCHS_PER_DAY * avg_share / your_stake * 100) if your_stake > 0 else 0
    smooth_apr = smooth_daily_pct * 365
    return spot_apr, smooth_apr

def get_top_rotation(top=5):
    if not os.path.exists(HISTORY_FILE):
        return {'inflows': [], 'outflows': [], 'apr': []}
    df = pd.read_csv(HISTORY_FILE)
    dates = sorted(df['date'].unique())
    if len(dates) < 2:
        inflows = outflows = []
    else:
        today_date = dates[-1]
        yest_date = dates[-2]
        today_df = df[df['date'] == today_date]
        yest_df = df[df['date'] == yest_date]
        today_stakes = today_df.groupby('netuid')['subnet_stake'].last()
        yest_stakes = yest_df.groupby('netuid')['subnet_stake'].last()
        common_netuids = today_stakes.index.union(yest_stakes.index)
        flow24 = today_stakes.reindex(common_netuids, fill_value=0) - yest_stakes.reindex(common_netuids, fill_value=0)
        inflows = [{'netuid': int(idx), 'flow24': float(val)} for idx, val in flow24.nlargest(top).items()]
        outflows = [{'netuid': int(idx), 'flow24': float(val)} for idx, val in flow24.nsmallest(top).items()]
    # APR proxy: top current stakes
    current_stakes = df.loc[df['date'] == dates[-1]].groupby('netuid')['subnet_stake'].last().nlargest(top)
    if current_stakes.empty:
        current_stakes = df.groupby('netuid')['subnet_stake'].mean().nlargest(top)  # fallback avg stake
    apr = [{'netuid': int(idx), 'subnet_stake': float(val)} for idx, val in current_stakes.items()]
    return {'inflows': inflows, 'outflows': outflows, 'apr': apr}

# Existing P&L (unchanged)
def tao_price():
    d = requests.get(f'{BASE}/price/latest/v1?asset=tao', headers=HEADERS, timeout=10).json()
    return float(d['data'][0]['price']) if d.get('data') else 0.0

def get_delegations():
    d = requests.get(f'{BASE}/delegation/v1?nominator={COLDKEY}&limit=100', headers=HEADERS, timeout=10).json()
    return d['data'] if d.get('data') else []

def build_positions(txns):
    positions = {}
    for tx in sorted(txns, key=lambda x: x['timestamp']):
        key = (tx['netuid'], tx['delegate']['ss58'])
        amt = int(tx['amount']) / 1e9
        usd = float(tx['usd'])
        if tx['action'] == 'DELEGATE':
            positions.setdefault(key, {'netuid': tx['netuid'], 'validator': tx['delegate_name'], 'tao_staked': 0, 'cost_usd': 0})
            positions[key]['tao_staked'] += amt
            positions[key]['cost_usd'] += usd
        elif tx['action'] == 'UNDELEGATE':
            if key in positions:
                positions[key]['tao_staked'] = max(0, positions[key]['tao_staked'] - amt)
                positions[key]['cost_usd'] = max(0, positions[key]['cost_usd'] - usd)
    return [v for v in positions.values() if v['tao_staked'] > 0.001]

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

# Main
def main():
    now = datetime.now()
    tao = tao_price()
    txns = get_delegations()
    positions = build_positions(txns)
    sorted_pos = sorted(positions, key=lambda x: x['tao_staked'], reverse=True)
    total_tao = sum(p['tao_staked'] for p in positions)
    total_cost = sum(p['cost_usd'] for p in positions)
    total_usd = total_tao * tao

    # Existing P&L body (unchanged)
    body = f'''TAO Portfolio — {now.strftime('%A, %B %d, %Y')}
{ "━" * 56 }

TAO PRICE
  Current:  ${tao:,.2f}

PORTFOLIO SNAPSHOT
  TAO Staked:       {total_tao:.4f} TAO
  Current Value:    ${total_usd:,.2f}
  Total Cost Basis: ${total_cost:,.2f}
  Unrealized P&L:   ${total_usd - total_cost:,.2f}

{ "━" * 56 }

ACTIVE POSITIONS
'''
    for p in sorted_pos:
        current_val = p['tao_staked'] * tao
        pnl = current_val - p['cost_usd']
        pnl_pct = (pnl / p['cost_usd'] * 100) if p['cost_usd'] > 0 else 0
        sn_name = get_subnet_name(p['netuid'])
        body += f'''
  SN{p["netuid"]} {sn_name} — {p["validator"]}
    Staked:   {p["tao_staked"]:.4f} TAO  (${current_val:,.2f})
    Cost:     ${p["cost_usd"]:,.2f}
    P&L:      ${pnl:,.2f} ({pnl_pct:.1f}%)
'''

    # New Yield/Flow
    body += f'{ "━" * 56 }\n\nSUBNET FLOW + YIELD (ESTIMATES)\n'
    append_history(sorted_pos)
    for p in sorted_pos:
        subnet_stake, em_proxy = get_bt_data(p['netuid'])
        share = p['tao_staked'] / subnet_stake if subnet_stake > 0 else 0
        EPOCHS_PER_DAY = 20  # 24h / 72min epochs
        daily_em_subnet = em_proxy * EPOCHS_PER_DAY
        daily_em = daily_em_subnet * share  # your daily TAO
        yield_usd = daily_em * tao
        yield_pct = daily_em / p['tao_staked'] * 100 if p['tao_staked'] > 0 else 0
        apr_proxy = yield_pct * 365  # (directional epoch proxy)
        flow24, flow7d = get_flows(p['netuid'])
        sn_name = get_subnet_name(p['netuid'])
        body += f'''
SN{p["netuid"]} {sn_name} — {p["validator"]}
Stake: {p["tao_staked"]:.4f} TAO
Est. daily subnet em: {daily_em_subnet:.4f} TAO (epoch x24)
Est. your daily yield: {daily_em:.6f} TAO / ${yield_usd:.2f} ({yield_pct:.3f}%)
Est. APR proxy: {apr_proxy:.0f}% (dir., epoch-based)
24h flow (derived): {flow24:+,.0f} TAO
7d flow (derived): {flow7d:+,.0f} TAO
'''

    # Top Rotation
    top = get_top_rotation(5)
    body += f'{ "━" * 56 }\n\nTOP SUBNET ROTATION (MARKET VIEW)\n'
    body += 'INflows 24h:\n'
    for item in top['inflows']:
        body += f'  SN{item["netuid"]}: +{item["flow24"]:,.0f} TAO\n'
    body += '\nOUTflows 24h:\n'
    for item in top['outflows']:
        body += f'  SN{item["netuid"]}: {item["flow24"]:,.0f} TAO\n'
    body += '\nHigh Stake Subnets (APR proxy):\n'
    for item in top['apr']:
        body += f'  SN{item["netuid"]}: {item["subnet_stake"]:,.0f} TAO\n'

    body += f'''
Proxy values estimated from recent subnet incentive share & daily snapshots; flows derived from subnet stake deltas.

Full analysis: ask Luke "TAO analysis"
Generated: {now.strftime('%Y-%m-%d %H:%M EST')}
{ "━" * 56 }'''

    subject = f'TAO — {now.strftime("%a %b %d")} | ${tao:,.0f}'
    send_email(subject, body)
    # Save snapshot
    snapshot = {'date': now.strftime('%Y-%m-%d'), 'tao': tao, 'total_tao': total_tao, 'total_usd': total_usd, 'total_cost': total_cost}
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(snapshot, f)

if __name__ == '__main__':
    main()
