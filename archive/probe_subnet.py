#!/usr/bin/env python3
import requests
import json
from datetime import datetime, timedelta
import sys

key = 'tao-3ab43b1a-25ef-4d3f-a677-03523704008a:7ec8aee8'
headers = {'Authorization': key}
base = 'https://api.taostats.io/api'

netuid = int(sys.argv[1]) if len(sys.argv) > 1 else 1

endpoints = [
    f'subnets/{netuid}',
    f'subnets/{netuid}/delegates',
    f'subnets/{netuid}/emissions',
    f'subnets/{netuid}/yield',
    f'subnets/{netuid}/stats',
]

print(f'Probing subnet {netuid}:')
for e in endpoints:
    url = f'{base}/{e}'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f'\n--- {e} ---')
        print(f'Status: {r.status_code}')
        if r.ok:
            data = r.json()
            print(json.dumps(data, indent=2)[:1500] + '...' if len(str(data)) > 1500 else json.dumps(data, indent=2))
        else:
            print(r.text[:300])
    except Exception as ex:
        print(f'Error: {ex}')
