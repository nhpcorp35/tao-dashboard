# TAO Portfolio Dashboard

Self-hosted live tracker for alpha staking positions.

## Quick Start

```bash
cd /home/node/.openclaw/workspace/tao-dashboard
pip install -r requirements.txt
python3 app.py
```

Then open: **http://127.0.0.1:5555**

## Files

- **app.py** — Flask server, fetches Taostats data, serves dashboard
- **templates/dashboard.html** — Live UI (dark theme, responsive)
- **daily_email.py** — Cron job script (9 AM EST snapshot)
- **positions.json** — Your staking positions (auto-created on first deploy)
- **cron-setup.md** — Instructions for email scheduling

## Features

✓ Real-time TAO price  
✓ Holdings summary (total, deployed, liquid)  
✓ Active deployment tracker  
✓ Top emitting subnets (live from Taostats)  
✓ Daily email snapshot  

## Roadmap

- [ ] Email delivery (Gmail / SendGrid)
- [ ] Alpha price tracking per subnet
- [ ] Daily/weekly ROI calculator
- [ ] Deployment history chart
- [ ] Mobile responsive polish

## Notes

- Dashboard updates on page refresh (Taostats API call)
- Email cron is prepared but needs SMTP credentials
- Positions stored in `positions.json` — edit manually or via API (coming)
- No real transactions yet — test deployment is paper trading

---

**Run this anytime:**
```bash
python3 app.py
```

**Check daily email locally:**
```bash
python3 daily_email.py
```
