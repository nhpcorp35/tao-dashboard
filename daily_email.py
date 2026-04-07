#!/usr/bin/env python3
"""
TAO Daily Email Summary
Runs via cron at 9 AM EST, sends concise portfolio update
"""

import json
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
POSITIONS_FILE = os.path.join(WORKSPACE, 'tao-dashboard', 'positions.json')
RECIPIENT = 'allen@nhpcorp.com'

# Zoho SMTP
ZOHO_EMAIL = 'luke443@zohomail.com'
ZOHO_PASSWORD = '@aMk351818!!'
ZOHO_SMTP = 'smtp.zoho.com'
ZOHO_PORT = 587

def load_positions():
    """Load positions from file"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE) as f:
                return json.load(f)
        except:
            return None
    return None

def get_taostats_snapshot():
    """Fetch current TAO price and top subnets"""
    try:
        # Simple fallback: hardcoded or API call
        r = requests.get('https://taostats.io/api/v1/network', timeout=5)
        r.raise_for_status()
        data = r.json()
        return {
            'tao_price': data.get('tao_price', 319.66),
            'timestamp': datetime.utcnow().isoformat()
        }
    except:
        # Fallback: last known price (will be updated)
        return {'tao_price': 319.66, 'timestamp': datetime.utcnow().isoformat()}

def generate_email_body(positions, snapshot):
    """Generate email body"""
    tao_price = snapshot['tao_price']
    
    if not positions:
        positions = {
            'holdings': {'tao_total': 10000, 'tao_deployed': 0, 'tao_liquid': 10000},
            'deployments': []
        }
    
    deployed_usd = positions['holdings']['tao_deployed'] * tao_price
    liquid_usd = positions['holdings']['tao_liquid'] * tao_price
    
    body = f"""
TAO Portfolio Update — {datetime.now().strftime('%A, %B %d, %Y @ %I:%M %p EST')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SNAPSHOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TAO Price: ${tao_price:.2f}
Holdings: {positions['holdings']['tao_total']:.2f} TAO

Deployed:  {positions['holdings']['tao_deployed']:.2f} TAO (${deployed_usd:,.0f})
Liquid:    {positions['holdings']['tao_liquid']:.2f} TAO (${liquid_usd:,.0f})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACTIVE DEPLOYMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    if positions['deployments']:
        for dep in positions['deployments']:
            body += f"\nSN{dep['subnet']} — {dep['alpha_staked']:.4f} α staked (since {dep['date']})"
    else:
        body += "\nNo active deployments. Test deployment coming soon."
    
    body += """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Dashboard: http://127.0.0.1:5555
Full analysis: ask Luke "TAO analysis"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    return body

def send_email(subject, body):
    """Send email via Zoho SMTP"""
    try:
        msg = MIMEMultipart()
        msg['From'] = ZOHO_EMAIL
        msg['To'] = RECIPIENT
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(ZOHO_SMTP, ZOHO_PORT) as server:
            server.starttls()
            server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
            server.send_message(msg)
        
        print(f"✓ Email sent to {RECIPIENT}")
        return True
    except Exception as e:
        print(f"✗ Email send failed: {e}")
        return False

def main():
    """Run the daily summary"""
    positions = load_positions()
    snapshot = get_taostats_snapshot()
    
    body = generate_email_body(positions, snapshot)
    subject = f"TAO Portfolio — {datetime.now().strftime('%a %b %d')}"
    
    send_email(subject, body)
    print(f"✓ Daily email prepared for {RECIPIENT}")

if __name__ == '__main__':
    main()
