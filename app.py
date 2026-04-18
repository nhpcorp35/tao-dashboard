#!/usr/bin/env python3
"""
TAO Portfolio Dashboard — Flask app
# Luke test 2026-04-12: OpenClaw edits here → git push → your git pull ~/tao-dashboard/app.py
Pulls live on-chain data via Taostats API
Rate limit: 5 requests/min — be very conservative
"""

from flask import Flask, render_template, jsonify
import json, os, time, requests, logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('tao-dash')

COLDKEY       = '5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb'
TAOSTATS_KEY  = os.environ.get('TAOSTATS_API_KEY', '')
SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), 'snapshot.json')
BASE          = 'https://api.taostats.io/api'
HEADERS       = {'Authorization': TAOSTATS_KEY} if TAOSTATS_KEY else {}

# Cache for 1 hour — Taostats is flaky + strict 5 req/min limit
_cache = {'data': None, 'ts': 0}
CACHE_TTL = 3600

# Track API calls to stay under 5/min
_rate = {'calls': [], 'MAX': 4}  # leave 1 call headroom


def _rate_ok():
    """Check if we can make an API call without exceeding 4/min."""
    now = time.time()
    _rate['calls'] = [t for t in _rate['calls'] if now - t < 60]
    return len(_rate['calls']) < _rate['MAX']


def _rate_record():
    _rate['calls'].append(time.time())


def api(endpoint, params=None):
    """Single-try API call with rate limit awareness."""
    if not TAOSTATS_KEY:
        log.error("TAOSTATS_API_KEY not set!")
        return None

    if not _rate_ok():
        wait = 60 - (time.time() - _rate['calls'][0])
        log.warning(f"Rate limit: waiting {wait:.0f}s before {endpoint}")
        time.sleep(max(wait, 1))

    url = f"{BASE}/{endpoint}"
    try:
        _rate_record()
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if r.status_code == 429:
            retry_after = int(r.headers.get('Retry-After', 60))
            log.warning(f"429 from {endpoint}, backing off {retry_after}s")
            time.sleep(retry_after)
            # One retry
            _rate_record()
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"API error {endpoint}: {e}")
        return None


def _load_snapshot():
    """Load last-known-good snapshot for fallback."""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE) as f:
                return json.load(f)
        except:
            pass
    return None


def fetch_portfolio():
    now = time.time()
    if _cache['data'] and (now - _cache['ts']) < CACHE_TTL:
        return _cache['data']

    api_failed = False

    # TAO price — 1 API call
    price_data = api('price/latest/v1', {'asset': 'tao'})
    tao = 0.0
    chg_24h = chg_7d = chg_30d = 0.0
    if price_data and price_data.get('data'):
        p = price_data['data'][0]
        tao     = float(p['price'])
        chg_24h = float(p.get('percent_change_24h', 0))
        chg_7d  = float(p.get('percent_change_7d', 0))
        chg_30d = float(p.get('percent_change_30d', 0))
    else:
        api_failed = True

    # Small delay between calls to be respectful
    time.sleep(2)

    # Delegation history — 1 API call
    del_data = api('delegation/v1', {'nominator': COLDKEY, 'limit': 100})
    txns = del_data['data'] if del_data and del_data.get('data') else []

    if not txns:
        api_failed = True

    # If API failed, fall back to snapshot
    if api_failed:
        snap = _load_snapshot()
        if snap and _cache['data']:
            # Return stale cache with warning
            log.warning("API failed, returning stale cache")
            _cache['data']['stale'] = True
            _cache['data']['error'] = 'API unavailable — showing cached data'
            return _cache['data']
        elif snap:
            # Build minimal result from snapshot
            log.warning("API failed, no cache — using snapshot fallback")
            return {
                'tao':         snap.get('tao', 0),
                'chg_24h':     0, 'chg_7d': 0, 'chg_30d': 0,
                'total_tao':   snap.get('total_tao_staked', 0),
                'total_usd':   snap.get('total_usd_value', 0),
                'total_cost':  snap.get('total_cost_usd', 0),
                'unrealized':  snap.get('total_usd_value', 0) - snap.get('total_cost_usd', 0),
                'ytd_pct':     0,
                'daily_usd':   None,
                'daily_pct':   0,
                'positions':   [],
                'updated':     f"{snap.get('date', '?')} (snapshot — API unavailable)",
                'coldkey':     COLDKEY[:12] + '...' + COLDKEY[-6:],
                'stale':       True,
                'error':       'API unavailable — showing last snapshot data',
            }

    # Build positions from delegation history
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
    snap = _load_snapshot()
    if snap:
        try:
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
        'stale':       False,
        'error':       None,
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

@app.route('/api/health')
def api_health():
    """Quick health check — tests API connectivity without burning rate limit."""
    return jsonify({
        'api_key_set': bool(TAOSTATS_KEY),
        'cache_age_s': int(time.time() - _cache['ts']) if _cache['data'] else None,
        'cache_ttl':   CACHE_TTL,
        'rate_calls_last_min': len([t for t in _rate['calls'] if time.time() - t < 60]),
        'has_data':    _cache['data'] is not None,
        'stale':       _cache['data'].get('stale', False) if _cache['data'] else None,
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    app.run(host='0.0.0.0', port=port, debug=False)

