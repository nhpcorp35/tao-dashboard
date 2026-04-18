#!/usr/bin/env python3
\"\"\"TAO Decision Engine
Run daily after daily_email.py: computes signals for your positions + top market subnets.
Output: tao_decisions.json (array sorted score desc)
\"\"\"
import pandas as pd
import json
from datetime import datetime
import bittensor as bt
import numpy as np

HISTORY_FILE = 'bt_history.csv'
POSITIONS_FILE = 'positions.json'  # from USER.md or snapshot
OUTPUT_FILE = 'tao_decisions.json'

EPOCHS_PER_DAY = 20

# Rules config (editable)
RULES = {
    'BUY_ADD': [
        'apr7d_rank <= 0.3',
        'flow7d_pct > 0',
        'spot_apr >= apr7d * 0.95',
        'your_size_pct < 0.05'
    ],
    'HOLD': [
        'apr7d_rank <= 0.5',
        'abs(flow7d_pct) <= 0.1',  # stable
        'spot_apr >= apr7d * 0.9'
    ],
    'TRIM_SELL': [
        'apr7d_rank > 0.7',
        'flow7d_pct < 0',
        'spot_apr < apr7d * 0.95'
    ],
    'WATCHLIST': [
        'apr7d_rank <= 0.4',
        'flow7d_pct > -0.05',  # improving
        'spot_apr > apr7d * 1.05'  # spot heating
    ]
}

TARGET_RULES = {  # action → target your_size_pct
    'BUY_ADD': 0.05,
    'HOLD': 0.03,
    'TRIM_SELL': 0.01,
    'WATCHLIST': 0.0
}

def load_data():
    # Bittensor live for top subnets
    sub = bt.subtensor(network='finney')
    top_netuids = range(min(128, sub.get_subnet_count()))
    live_data = []
    your_positions = {}
    for netuid in top_netuids:
        stake = float(sub.get_subnet_stake(netuid) / 1e9)
        if stake < 10: continue  # filter tiny
        mg = bt.metagraph(netuid=netuid, lite=True)
        em_epoch = float(mg.emissions.sum())
        neurons = len(mg.hotkeys)
        live_data.append({'netuid': netuid, 'stake': stake, 'em_epoch': em_epoch, 'neurons': neurons})

    # History for flows/APR7d (your posns + market)
    df = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame()
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df_net = df.groupby('netuid').agg({
            'subnet_stake': 'last',
            'subnet_em_epoch': 'last',
            'date': 'max'
        }).reset_index()
        # 7d flows/APR from history
        for _, row in df_net.iterrows():
            netuid = row['netuid']
            hist = df[df['netuid'] == netuid].sort_values('date').tail(8)
            if len(hist) >= 2:
                flow24_pct = (hist.iloc[-1]['subnet_stake'] - hist.iloc[-2]['subnet_stake']) / hist.iloc[-2]['subnet_stake']
                flow7_pct = (hist.iloc[-1]['subnet_stake'] - hist.iloc[0]['subnet_stake']) / hist.iloc[0]['subnet_stake'] if len(hist) >= 8 else 0
            else:
                flow24_pct = flow7_pct = 0
            # APR7d avg
            daily_em7 = hist['subnet_em_epoch'].tail(7).mean()
            apr7d = (daily_em7 * EPOCHS_PER_DAY / row['subnet_stake'] * 365 * 100) if row['subnet_stake'] > 0 else 0
            # rank placeholder (top by APR)
            live_data.append({'netuid': netuid, 'apr7d': apr7d, 'flow24_pct': flow24_pct, 'flow7d_pct': flow7_pct})

    # Dedup/merge live + hist
    metrics = {}
    for d in live_data:
        uid = d['netuid']
        metrics[uid] = d

    # Your positions (from history last)
    if not df.empty:
        your_df = df.groupby(['netuid', 'validator']).last().reset_index()
        for _, row in your_df.iterrows():
            uid = row['netuid']
            your_positions[uid] = {'validator': row['validator'], 'your_stake': row['my_stake'], 'your_size_pct': row['my_stake'] / metrics.get(uid, {}).get('stake', 1)}

    return metrics, your_positions

def compute_score(metrics, apr7d, flow7d_pct, spot_apr, decline, rank_pct, your_size_pct):
    apr_norm = min(apr7d / 5000, 1)  # cap high APR
    flow_norm = (flow7d_pct + 0.5) / 1.0  # -50% to +50% → 0-1
    rank_norm = 1 - rank_pct
    decline_pen = max(0, 1 - decline * 2)  # penalize drop
    size_adj = 1 - your_size_pct * 10  # prefer underweight
    return int((apr_norm * flow_norm * rank_norm * decline_pen * size_adj) * 100)

def get_action(metrics_entry, rules):
    apr7d = metrics_entry.get('apr7d', 0)
    spot_apr = (metrics_entry['em_epoch'] * EPOCHS_PER_DAY / metrics_entry['stake'] * 365 * 100) if metrics_entry['stake'] > 0 else 0
    flow7d_pct = metrics_entry.get('flow7d_pct', 0)
    apr7d_rank = 0.3  # placeholder: compute percentile from all
    decline = (spot_apr - apr7d) / apr7d if apr7d > 0 else 0
    your_size_pct = metrics_entry.get('your_size_pct', 0)

    for action, conds in rules.items():
        if all(eval(c.replace('apr7d_rank', str(apr7d_rank)).replace('flow7d_pct', str(flow7d_pct))...) for c in conds):
            return action
    return 'HOLD'  # default

def main():
    metrics, your_pos = load_data()

    # Rank all
    apr7d_list = [m['apr7d'] for m in metrics.values() if 'apr7d' in m]
    apr7d_list.sort(reverse=True)
    decisions = []
    for uid, m in metrics.items():
        if m['stake'] < 10: continue
        name = f'SN{uid}'  # fetch name if API
        spot_apr = (m['em_epoch'] * EPOCHS_PER_DAY / m['stake'] * 365 * 100) if m['stake'] > 0 else 0
        apr7d = m.get('apr7d', spot_apr)
        flow7d_pct = m.get('flow7d_pct', 0)
        flow24_pct = m.get('flow24_pct', 0)
        apr7d_rank_pct = apr7d_list.index(apr7d) / len(apr7d_list) if apr7d in apr7d_list else 0.5
        decline = (spot_apr - apr7d) / max(apr7d, 1)
        your_size_pct = your_pos.get(uid, {}).get('your_size_pct', 0)
        action = get_action({'apr7d': apr7d, 'spot_apr': spot_apr, 'flow7d_pct': flow7d_pct, 'apr7d_rank': apr7d_rank_pct, 'your_size_pct': your_size_pct}, RULES)
        score = compute_score(m, apr7d, flow7d_pct, spot_apr, decline, apr7d_rank_pct, your_size_pct)
        reason = {
            'BUY_ADD': 'High APR + pos flows + underweight',
            'HOLD': 'Stable top50 APR + flows',
            'TRIM_SELL': 'APR decline + neg flows',
            'WATCHLIST': 'APR heating, flow watch'
        }.get(action, 'Default hold')

        decisions.append({
            'netuid': uid,
            'name': name,
            'action': action,
            'score': score,
            'short_reason': reason,
            'key_metrics': {
                'apr7d': round(apr7d, 0),
                'spot_apr': round(spot_apr, 0),
                'flow7d_pct': round(flow7d_pct*100, 1),
                'flow24_pct': round(flow24_pct*100, 1),
                'apr7d_rank_pct': round(apr7d_rank_pct*100, 0),
                'your_size_pct': round(your_size_pct*100, 1),
                'stake_TAO': round(m['stake'], 0),
                'em_epoch_TAO': round(m['em_epoch'], 2)
            }
        })

    decisions.sort(key=lambda x: x['score'], reverse=True)

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(decisions, f, indent=2)
    print(f'Wrote {len(decisions)} decisions to {OUTPUT_FILE}')
    print(json.dumps(decisions[:5], indent=2))  # preview top5

if __name__ == '__main__':
    main()