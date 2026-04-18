# TAO Dashboard — Project Map

## 🎯 Purpose

Turn TAO subnet data into **clear allocation decisions** (Buy / Hold / Trim / Exit).

---

## 🧩 Core Architecture

### 1. Data Pipeline

**File:** `update_bt_history.py`
**Role:**

* Fetches Bittensor subnet data
* Writes historical dataset

**Output:**

* `bt_history.csv`

---

### 2. Decision Engine

**File:** `tao_decision_engine.py`
**Role:**

* Reads `bt_history.csv`
* Generates signals (Buy / Hold / Trim / Exit)
* Applies stance logic

**Output:**

* `tao_decisions.json`

---

### 3. Email Report

**File:** `daily_email.py`
**Role:**

* Reads:

  * `bt_history.csv`
  * `tao_decisions.json`
* Builds and sends portfolio + subnet report

---

### 4. Dashboard UI

**File:** `app.py`
**Role:**

* Displays decisions visually
* Shows stance + reasoning

---

## 📊 Data Files

* `bt_history.csv` → historical subnet + flow data
* `tao_decisions.json` → latest engine output

---

## ▶️ Run Order

1. Update data:

```bash
python update_bt_history.py
```

2. Generate decisions:

```bash
python tao_decision_engine.py
```

3. Send report:

```bash
python daily_email.py
```

4. Run dashboard:

```bash
python app.py
```

---

## ⚠️ Current Status

* ✅ Dashboard working
* ✅ Decision engine stable (Root excluded)
* ⚠️ **Data pipeline issue:**

  * Emissions = 0
  * Flows = 0
  * APR = 0

---

## 🔧 Current Priority

**Fix data pipeline**

Trace:

* `update_bt_history.py` → data fetch
* `bt_history.csv` → stored values
* `daily_email.py` → report output

Goal:
→ Restore real emissions / flows / APR

---

## 🧭 Next Phase (after fix)

Upgrade to:

👉 **TAO Allocation Engine**

* Add rotation triggers
* Add position sizing
* Convert signals → capital actions

---

## 🧠 Mental Model

Not a dashboard.

👉 A system that answers:

**“What should I do with my TAO right now?”**

Expected bt_history.csv columns:

- timestamp
- netuid
- stake
- emissions
- flow_24h
- flow_7d
- aprls


