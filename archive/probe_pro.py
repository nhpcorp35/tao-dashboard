#!/usr/bin/env python3
import requests
import json
import sys
from datetime import datetime, timedelta

key = 'tao-d4074cce-4fc4-4b65-9ca0-421464b75d66:d5a5343b'
headers = {'Authorization': key}
base = 'https://api.taostats.io/api'

endpoints = [
    'subnets',
    'subnets?limit=20&sort=stake_desc',
    'subnets?limit=20&sort=emissions_desc',
    'subnets/4',
    'subnets/4/emissions',
    'subnets/4/yield',
    'subnets/4/stats',
    'subnets/4/delegates',
    'yield',
    'subnets/yield',
    'delegation/portfolio',
    'delegation/active',
    'chain/stake/netuid=4',
    'subnets/4/stake_history?period=7d',
    'pro/portfolio',
    'delegation/v1?nominator=5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb&limit=5',
]

print('Probing Taostats Pro API with new key:')
print(f'Key prefix: tao-d4074cce...')

for e in endpoints:
    url = f'{base}/{e}'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f'\n--- {e} ---')
        print(f'Status: {r.status_code}')
        print(f'Content-Type: {r.headers.get("content-type", "N/A")}')
        if r.ok and r.headers.get('content-type', '').startswith('application/json'):
            data = r.json()
            print(json.dumps(data, indent=2)[:2000] + ('...' if len(str(data)) > 2000 else ''))
        elif r.ok:
            print(r.text[:800])
        else:
            print(r.text[:400])
    except Exception as ex:
        print(f'Error: {ex}')
