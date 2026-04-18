#!/usr/bin/env python3
import requests
import json
from datetime import datetime, timedelta

key = 'tao-3ab43b1a-25ef-4d3f-a677-03523704008a:7ec8aee8'
headers = {'Authorization': key}
base = 'https://api.taostats.io/api'

endpoints = [
    'subnets',
    'subnets/v1',
    'network/subnets',
    'yield',
    'subnets/yield',
    'emissions',
    'chain/emissions',
    'delegates',
    'validators',
    'subnets/stats',
    'subnets?limit=20',
    'delegation/active',
    'delegation/v1?limit=5&nominator=5Cexeg7deNSTzsqMKuBmvc9JHGHymuL4SdjAA9Jw4eeHUphb',
]

print('Probing Taostats API endpoints:')
for e in endpoints:
    url = f'{base}/{e}'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f'\n--- {e} ---')
        print(f'Status: {r.status_code}')
        if r.ok:
            data = r.json()
            print(json.dumps(data, indent=2)[:1000] + '...' if len(str(data)) > 1000 else json.dumps(data, indent=2))
        else:
            print(r.text[:300])
    except Exception as ex:
        print(f'Error: {ex}')
