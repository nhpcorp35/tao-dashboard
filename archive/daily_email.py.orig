#!/usr/bin/env python3
"""
TAO Daily P&L Email
Runs via cron at 9 AM EST — sends portfolio snapshot with daily P&L
"""

import json
import os
import smtplib
import time
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# ── Config ───────────────────────────────────────────────────────────────────
COLDKEY      = '5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb'
TAOSTATS_KEY = 'tao-3ab43b1a-25ef-4d3f-a677-03523704008a:7ec8aee8'
RECIPIENT    = 'allen@nhpcorp.com'
ZOHO_EMAIL   = 'luke443@zohomail.com'
ZOHO_PASS    = '@aMk351818!!'
ZOHO_SMTP    = 'smtp.zoho.com'
ZOHO_PORT    = 587

SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), 'snapshot.json')
HEADERS = {'Authorization': TAOSTATS_KEY}
BASE    = 'https://api.taostats.io/api'

# ── Subnet Name Cache ─────────────────────────────────────────────────────────
import re

_subnet_names: dict[int, str] = {}

def get_subnet_name(netuid: int) -> str:
    """Fetch subnet name from taostats page title. Caches per run."""
    if netuid in _subnet_names:
        return _subnet_names[netuid]
    try:
        r = requests.get(f"https://taostats.io/subnets/{netuid}", timeout=8)
        # Parse name from <title>... · SN3 · τemplar · taostats ...</title>
        match = re.search(r'<title>[^<]*·\s*SN\d+\s*·\s*([^·<]+?)·', r.text)
        name = match.group(1).strip() if match else ''
        _subnet_names[netuid] = name
        return name
    except Exception:
        _subnet_names[netuid] = ''
        return ''

# ── Helpers ───────────────────────────────────────────────────────────────────
def api(endpoint, params=None, retries=3, delay=5):
    url = f"{BASE}/{endpoint}"
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
            if r.status_code == 429:
                time.sleep(delay * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                print(f"API error {endpoint}: {e}")
                return None
            time.sleep(delay)
    return None

def tao_price():
    d = api('price/latest/v1', {'asset': 'tao'})
    if d and d.get('data'):
        p = d['data'][0]
        return {
            'price':    float(p['price']),
            'chg_24h':  float(p.get('percent_change_24h', 0)),
            'chg_7d':   float(p.get('percent_change_7d', 0)),
            'chg_30d':  float(p.get('percent_change_30d', 0)),
        }
    return {'price': 0, 'chg_24h': 0, 'chg_7d': 0, 'chg_30d': 0}

def get_delegations():
    d = api('delegation/v1', {'nominator': COLDKEY, 'limit': 100})
    if d and d.get('data'):
        return d['data']
    return []

def build_positions(txns):
    """
    Reconstruct current positions from delegation history.
    Returns dict keyed by (netuid, delegate_ss58) → position info.
    """
    positions = {}
    for tx in sorted(txns, key=lambda x: x['timestamp']):
        key = (tx['netuid'], tx['delegate']['ss58'])
        name = tx['delegate_name']
        amt_tao  = int(tx['amount']) / 1e9
        amt_alpha = int(tx['alpha']) / 1e9
        cost_usd = float(tx['usd'])

        if tx['action'] == 'DELEGATE':
            if key not in positions:
                positions[key] = {
                    'netuid': tx['netuid'],
                    'validator': name,
                    'hotkey': tx['delegate']['ss58'],
                    'tao_staked': 0.0,
                    'alpha_held': 0.0,
                    'cost_usd': 0.0,
                    'first_stake': tx['timestamp'][:10],
                }
            positions[key]['tao_staked'] += amt_tao
            positions[key]['alpha_held'] += amt_alpha
            positions[key]['cost_usd']   += cost_usd

        elif tx['action'] == 'UNDELEGATE':
            if key in positions:
                positions[key]['tao_staked'] = max(0, positions[key]['tao_staked'] - amt_tao)
                positions[key]['alpha_held'] = max(0, positions[key]['alpha_held'] - amt_alpha)
                positions[key]['cost_usd']   = max(0, positions[key]['cost_usd'] - cost_usd)

    # Filter out closed positions
    return {k: v for k, v in positions.items() if v['tao_staked'] > 0.001}

def load_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    return None

def save_snapshot(data):
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg['From']    = ZOHO_EMAIL
        msg['To']      = RECIPIENT
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(ZOHO_SMTP, ZOHO_PORT) as s:
            s.starttls()
            s.login(ZOHO_EMAIL, ZOHO_PASS)
            s.send_message(msg)
        print(f"✓ Email sent to {RECIPIENT}")
        return True
    except Exception as e:
        print(f"✗ Email failed: {e}")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    print(f"Running TAO daily email — {now.strftime('%Y-%m-%d %H:%M')}")

    # 1. TAO price
    price_data = tao_price()
    tao = price_data['price']
    print(f"TAO: ${tao:.2f}")

    # 2. Build positions from delegation history
    txns = get_delegations()
    positions = build_positions(txns)
    print(f"Active positions: {len(positions)}")

    # 3. Load yesterday's snapshot for daily P&L
    yesterday = load_snapshot()
    today_total_cost = sum(p['cost_usd'] for p in positions.values())
    today_total_tao  = sum(p['tao_staked'] for p in positions.values())
    today_total_usd  = today_total_tao * tao

    # Daily P&L = change in USD value of TAO holdings due to price movement
    # (doesn't yet account for alpha accrual - coming when API supports it)
    if yesterday and yesterday.get('tao'):
        prev_tao   = yesterday['tao']
        prev_total = yesterday.get('total_tao_staked', today_total_tao) * prev_tao
        daily_pnl_usd = today_total_usd - prev_total
        daily_pnl_pct = ((tao / prev_tao) - 1) * 100
    else:
        daily_pnl_usd = None
        daily_pnl_pct = price_data['chg_24h']

    unrealized_pnl     = today_total_usd - today_total_cost
    ytd_pnl_usd        = unrealized_pnl
    ytd_pnl_pct        = ((today_total_usd / today_total_cost) - 1) * 100 if today_total_cost > 0 else 0

    # 4. Save today's snapshot
    save_snapshot({
        'date': now.strftime('%Y-%m-%d'),
        'tao': tao,
        'total_tao_staked': today_total_tao,
        'total_usd_value': today_total_usd,
        'total_cost_usd': today_total_cost,
    })

    # 5. Build email
    arrow_24h = '▲' if price_data['chg_24h'] >= 0 else '▼'
    arrow_7d  = '▲' if price_data['chg_7d']  >= 0 else '▼'

    if daily_pnl_usd is not None:
        pnl_sign = '+' if daily_pnl_usd >= 0 else ''
        pnl_line = f"{pnl_sign}${daily_pnl_usd:,.2f} ({pnl_sign}{daily_pnl_pct:.2f}%)"
    else:
        sign = '+' if price_data['chg_24h'] >= 0 else ''
        pnl_line = f"{sign}{price_data['chg_24h']:.2f}% (price-based)"

    unreal_sign = '+' if unrealized_pnl >= 0 else ''

    body = f"""TAO Portfolio — {now.strftime('%A, %B %d, %Y')}
{'━'*56}

TAO PRICE
  Current:  ${tao:,.2f}
  24h:      {arrow_24h} {abs(price_data['chg_24h']):.2f}%
  7d:       {arrow_7d} {abs(price_data['chg_7d']):.2f}%
  30d:      {'▲' if price_data['chg_30d'] >= 0 else '▼'} {abs(price_data['chg_30d']):.2f}%

{'━'*56}

PORTFOLIO SNAPSHOT
  TAO Staked:       {today_total_tao:.4f} TAO
  Current Value:    ${today_total_usd:,.2f}
  Total Cost Basis: ${today_total_cost:,.2f}
  Unrealized P&L:   {unreal_sign}${unrealized_pnl:,.2f}

DAILY P&L
  {pnl_line}

YTD P&L (since first stake 2026-03-06)
  {'+' if ytd_pnl_usd >= 0 else ''}${ytd_pnl_usd:,.2f}  ({'+' if ytd_pnl_pct >= 0 else ''}{ytd_pnl_pct:.2f}%)

{'━'*56}

ACTIVE POSITIONS
"""

    # Sort by tao_staked desc
    sorted_pos = sorted(positions.values(), key=lambda x: x['tao_staked'], reverse=True)
    for p in sorted_pos:
        current_val = p['tao_staked'] * tao
        pos_pnl     = current_val - p['cost_usd']
        pos_pnl_pct = ((current_val / p['cost_usd']) - 1) * 100 if p['cost_usd'] > 0 else 0
        sign = '+' if pos_pnl >= 0 else ''
        
        # YTD P&L (same as overall, since all positions opened in 2026)
        ytd_pos_pnl = pos_pnl
        ytd_pos_pct = pos_pnl_pct
        ytd_sign = '+' if ytd_pos_pnl >= 0 else ''
        
        sn_name = get_subnet_name(int(p['netuid']))
        sn_label = f"SN{p['netuid']} {sn_name}" if sn_name else f"SN{p['netuid']}"
        
        body += f"""
  {sn_label} — {p['validator']}
    Staked:   {p['tao_staked']:.4f} TAO  (${current_val:,.2f})
    Cost:     ${p['cost_usd']:,.2f}
    P&L:      {sign}${pos_pnl:,.2f} ({sign}{pos_pnl_pct:.1f}%)
    YTD P&L:  {ytd_sign}${ytd_pos_pnl:,.2f} ({ytd_sign}{ytd_pos_pct:.1f}%)
    Since:    {p['first_stake']}
"""

    body += f"""
{'━'*56}

Full analysis: ask Luke "TAO analysis"
Address: {COLDKEY[:12]}...{COLDKEY[-6:]}
Generated: {now.strftime('%Y-%m-%d %H:%M EST')}
{'━'*56}
"""

    subject = f"TAO Portfolio — {now.strftime('%a %b %d')} | ${tao:,.2f} | {'+' if price_data['chg_24h'] >= 0 else ''}{price_data['chg_24h']:.1f}% 24h"
    send_email(subject, body)
    print(body)

if __name__ == '__main__':
    main()
