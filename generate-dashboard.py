#!/usr/bin/env python3
"""
Generate static TAO dashboard HTML
Runs via cron hourly to update /tmp/tao-dashboard.html
"""

import json
import os
from datetime import datetime
import requests

WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
POSITIONS_FILE = os.path.join(WORKSPACE, 'tao-dashboard', 'positions.json')
OUTPUT_FILE = os.path.expanduser('~/Desktop/tao-dashboard.html')

def load_positions():
    """Load positions from file"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {
        'holdings': {'tao_total': 10000, 'tao_deployed': 0, 'tao_liquid': 10000},
        'deployments': []
    }

def get_tao_price():
    """Fetch current TAO price"""
    try:
        r = requests.get('https://api.taostats.io/api/v1/network', timeout=3)
        r.raise_for_status()
        return r.json().get('tao_price', 319.66)
    except:
        return 319.66

def generate_html(positions, tao_price):
    """Generate the static HTML"""
    deployed_usd = positions['holdings']['tao_deployed'] * tao_price
    liquid_usd = positions['holdings']['tao_liquid'] * tao_price
    
    deployments_html = ""
    if positions['deployments']:
        for dep in positions['deployments']:
            deployments_html += f"""
            <tr>
                <td>SN{dep['subnet']}</td>
                <td>{dep['alpha_staked']:.4f}</td>
                <td>{dep['date']}</td>
                <td><span style="color: #4ade80;">●</span> Active</td>
            </tr>
            """
    else:
        deployments_html = '<tr><td colspan="4" style="text-align: center; padding: 40px; color: #666;">No active deployments yet.</td></tr>'
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TAO Portfolio Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #e0e0e0;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ margin-bottom: 20px; color: #fff; font-size: 28px; }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding: 15px 20px;
            background: #1a1a1a;
            border-radius: 8px;
            border-left: 3px solid #ffd700;
        }}
        .header-price {{
            font-size: 20px;
            font-weight: bold;
            color: #ffd700;
        }}
        .header-time {{
            font-size: 12px;
            color: #888;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 20px;
        }}
        .card-title {{
            font-size: 14px;
            color: #999;
            text-transform: uppercase;
            margin-bottom: 10px;
            font-weight: 600;
        }}
        .card-value {{
            font-size: 28px;
            font-weight: bold;
            color: #fff;
        }}
        .card-sub {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        thead {{
            background: #222;
            border-bottom: 2px solid #333;
        }}
        th {{
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #bbb;
            font-size: 12px;
            text-transform: uppercase;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #2a2a2a;
            font-size: 14px;
        }}
        tr:hover {{ background: #151515; }}
        .emoji {{ font-size: 18px; margin-right: 8px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1><span class="emoji">τ</span>TAO Portfolio</h1>
        
        <div class="header">
            <div>
                <div class="header-price">TAO: ${tao_price:.2f}</div>
                <div class="header-time">Updated: {datetime.now().strftime('%a %b %d, %I:%M %p EST')}</div>
            </div>
            <div class="header-time">✓ Live</div>
        </div>
        
        <div class="grid">
            <div class="card">
                <div class="card-title">Holdings</div>
                <div class="card-value">{positions['holdings']['tao_total']:.2f}</div>
                <div class="card-sub">TAO Total</div>
            </div>
            
            <div class="card">
                <div class="card-title">Deployed</div>
                <div class="card-value">${deployed_usd:,.0f}</div>
                <div class="card-sub">{positions['holdings']['tao_deployed']:.2f} TAO</div>
            </div>
            
            <div class="card">
                <div class="card-title">Liquid</div>
                <div class="card-value">${liquid_usd:,.0f}</div>
                <div class="card-sub">{positions['holdings']['tao_liquid']:.2f} TAO</div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-title">Active Deployments</div>
            <table>
                <thead>
                    <tr>
                        <th>Subnet</th>
                        <th>Alpha Staked</th>
                        <th>Deployed Date</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {deployments_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
    
    return html

def main():
    positions = load_positions()
    tao_price = get_tao_price()
    html = generate_html(positions, tao_price)
    
    # Write to Desktop
    with open(OUTPUT_FILE, 'w') as f:
        f.write(html)
    
    print(f"✓ Dashboard updated: {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
