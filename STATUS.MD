# STATUS — TAO Dashboard

## Last Working State

* Commit: c7a48c9
* Dashboard: working
* Decision engine: working
* Root excluded: yes

## Current Problem

* Emissions = 0
* Flows = 0
* APR = 0
* Email report duplicated / stale

## Likely Cause

* Data pipeline broken (update_bt_history.py OR schema mismatch)

## Next Action

* Trace:

  1. updater output
  2. bt_history.csv values
  3. daily_email.py field mapping

## Owner Focus

👉 Fix data before touching logic
