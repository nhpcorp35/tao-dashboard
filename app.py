#!/usr/bin/env python3
"""
TAO Portfolio Dashboard — Flask app
Pulls live on-chain data via Taostats API
"""

from flask import Flask, render_template, jsonify
import json, os, time, requests
from datetime import datetime

app = Flask(__name__)

COLDKEY       = '5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb'
TAOSTATS_KEY  = os.environ.get('TAOSTATS_API_KEY', 'tao-3ab43b1a-25ef-4d3f-a677-03523704008a:7ec8aee8')
SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), 'snapshot.json')
BASE          = 'https://api.taostats.io/api'
HEADERS       = {'Authorization': TAOSTATS_KEY}

_cache = {'data': None, 'ts': 0}
CACHE_TTL = 300  # 5 min

def api(endpoint, params=None, retries=3):
    url = f"{BASE}/{endpoint}"
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
            if r.status_code == 429:
                time.sleep(5 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                return None
            time.sleep(3)
    return None

def fetch_portfolio():
    now = time.time()
    if _cache['data'] and (now - _cache['ts']) < CACHE_TTL:
        return _cache['data']

    # TAO price
    price_data = api('price/latest/v1', {'asset': 'tao'})
    tao = 0.0
    chg_24h = chg_7d = chg_30d = 0.0
    if price_data and price_data.get('data'):
        p = price_data['data'][0]
        tao     = float(p['price'])
        chg_24h = float(p.get('percent_change_24h', 0))
        chg_7d  = float(p.get('percent_change_7d', 0))
        chg_30d = float(p.get('percent_change_30d', 0))

    # Delegation history
    del_data = api('delegation/v1', {'nominator': COLDKEY, 'limit': 100})
    txns = del_data['data'] if del_data and del_data.get('data') else []

    # Build positions
    positions = {}
    for tx in sorted(txns, key=lambda x: x['timestamp']):
        key  = (tx['netuid'], tx['delegate']['ss58'])
        name = tx['delegate_name']
        amt_tao   = int(tx['amount']) / 1e9
        amt_alpha = int(tx['alpha'])  / 1e9
        cost_usd  = float(tx['usd'])

        if tx['action'] == 'DELEGATE':
            if key not in positions:
                positions[key] = {
                    'netuid':     tx['netuid'],
                    'validator':  name,
                    'hotkey':     tx['delegate']['ss58'],
                    'tao_staked': 0.0,
                    'alpha_held': 0.0,
                    'cost_usd':   0.0,
                    'first_stake': tx['timestamp'][:10],
                }
            positions[key]['tao_staked'] += amt_tao
            positions[key]['alpha_held'] += amt_alpha
            positions[key]['cost_usd']   += cost_usd
        elif tx['action'] == 'UNDELEGATE':
            if key in positions:
                positions[key]['tao_staked'] = max(0, positions[key]['tao_staked'] - amt_tao)
                positions[key]['alpha_held'] = max(0, positions[key]['alpha_held'] - amt_alpha)
                positions[key]['cost_usd']   = max(0, positions[key]['cost_usd']   - cost_usd)

    active = [v for v in positions.values() if v['tao_staked'] > 0.001]

    # Totals
    total_tao    = sum(p['tao_staked'] for p in active)
    total_cost   = sum(p['cost_usd']   for p in active)
    total_usd    = total_tao * tao
    unrealized   = total_usd - total_cost
    ytd_pct      = ((total_usd / total_cost) - 1) * 100 if total_cost > 0 else 0

    # Daily P&L from snapshot
    daily_usd = daily_pct = None
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                snap = json.load(f)
            if snap.get('date') != datetime.utcnow().strftime('%Y-%m-%d'):
                prev_val  = snap.get('total_tao_staked', total_tao) * snap.get('tao', tao)
                daily_usd = total_usd - prev_val
                daily_pct = ((tao / snap['tao']) - 1) * 100 if snap.get('tao') else chg_24h
        except:
            pass

    # Enrich positions with current values
    for p in active:
        val = p['tao_staked'] * tao
        p['current_usd'] = val
        p['pnl_usd']     = val - p['cost_usd']
        p['pnl_pct']     = ((val / p['cost_usd']) - 1) * 100 if p['cost_usd'] > 0 else 0

    active.sort(key=lambda x: x['tao_staked'], reverse=True)

    result = {
        'tao':         tao,
        'chg_24h':     chg_24h,
        'chg_7d':      chg_7d,
        'chg_30d':     chg_30d,
        'total_tao':   total_tao,
        'total_usd':   total_usd,
        'total_cost':  total_cost,
        'unrealized':  unrealized,
        'ytd_pct':     ytd_pct,
        'daily_usd':   daily_usd,
        'daily_pct':   daily_pct if daily_pct is not None else chg_24h,
        'positions':   active,
        'updated':     datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        'coldkey':     COLDKEY[:12] + '...' + COLDKEY[-6:],
    }
    _cache['data'] = result
    _cache['ts']   = now
    return result

@app.route('/')
def dashboard():
    data = fetch_portfolio()
    return render_template('dashboard.html', d=data)

@app.route('/api/data')
def api_data():
    return jsonify(fetch_portfolio())

@app.route('/api/refresh')
def api_refresh():
    _cache['ts'] = 0
    return jsonify({'ok': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    app.run(host='0.0.0.0', port=port, debug=False)
