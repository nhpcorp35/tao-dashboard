#!/usr/bin/env python3
"""
TAO Portfolio Dashboard
Live alpha staking tracker with daily email integration
"""

from flask import Flask, render_template, jsonify
import json
import os
from datetime import datetime
import requests

app = Flask(__name__)
WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
POSITIONS_FILE = os.path.join(WORKSPACE, 'tao-dashboard', 'positions.json')

# Default positions (empty for now, will be populated on first deploy)
DEFAULT_POSITIONS = {
    "holdings": {
        "tao_total": 10000,
        "tao_deployed": 0,
        "tao_liquid": 10000
    },
    "deployments": [],  # [{subnet: 3, alpha_staked: 100, date: '2026-04-06'}]
    "last_updated": datetime.utcnow().isoformat()
}

def load_positions():
    """Load positions from file, or return defaults"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE) as f:
                return json.load(f)
        except:
            return DEFAULT_POSITIONS
    return DEFAULT_POSITIONS

def save_positions(data):
    """Save positions to file"""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_taostats_data():
    """Fetch live data from Taostats API"""
    try:
        # Get TAO price (simpler endpoint)
        price_r = requests.get('https://api.taostats.io/api/v1/network', timeout=3)
        price_r.raise_for_status()
        network = price_r.json()
        tao_price = network.get('tao_price', 319.66)
        
        return {
            'subnets': [],  # Skip for now, too slow
            'tao_price': tao_price,
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        print(f"Taostats fetch error: {e}")
        # Return fallback data so page doesn't hang
        return {
            'subnets': [],
            'tao_price': 319.66,
            'timestamp': datetime.utcnow().isoformat(),
            'error': 'Using cached price'
        }

@app.route('/')
def dashboard():
    """Main dashboard page"""
    positions = load_positions()
    taostats = get_taostats_data()
    
    # Calculate totals
    tao_deployed = positions['holdings']['tao_deployed']
    tao_price = taostats.get('tao_price', 319.66)
    deployed_usd = tao_deployed * tao_price
    
    return render_template('dashboard.html', 
                          positions=positions,
                          taostats=taostats,
                          tao_price=tao_price,
                          deployed_usd=deployed_usd)

@app.route('/api/positions')
def api_positions():
    """API endpoint for positions"""
    return jsonify(load_positions())

@app.route('/api/data')
def api_data():
    """API endpoint for dashboard data"""
    positions = load_positions()
    taostats = get_taostats_data()
    tao_price = taostats.get('tao_price', 319.66)
    
    return jsonify({
        'positions': positions,
        'taostats': taostats,
        'tao_price': tao_price,
        'timestamp': datetime.utcnow().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    app.run(host='0.0.0.0', port=port, debug=False)
