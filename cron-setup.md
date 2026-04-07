# TAO Daily Email Cron Setup

## Add to your system crontab:

```
# Run TAO daily email at 9 AM EST
0 9 * * * /usr/bin/python3 /home/node/.openclaw/workspace/tao-dashboard/daily_email.py >> /home/node/.openclaw/workspace/tao-dashboard/cron.log 2>&1
```

## To install:
```bash
crontab -e
# Paste the line above, save & exit
crontab -l  # Verify it's there
```

## To test without cron:
```bash
python3 /home/node/.openclaw/workspace/tao-dashboard/daily_email.py
```

## Current status:
- ⚠️ Email delivery: **not yet configured** (see notes below)
- Dashboard: **ready to run** (`python3 app.py`)

## Email Setup (TODO)

For actual email delivery, we need SMTP credentials. Options:

1. **Gmail** (easiest):
   - Enable "App Password" in Gmail account settings
   - Store in env var: `TAO_EMAIL_PASSWORD`
   - Update `daily_email.py` to use smtp.gmail.com

2. **SendGrid / Mailgun** (cloud):
   - Get API key
   - Use their SMTP relay
   - More reliable for cron

3. **Local sendmail**:
   - If available on your system

For now, `daily_email.py` logs output to console. Once you choose an option, I'll wire it up.
