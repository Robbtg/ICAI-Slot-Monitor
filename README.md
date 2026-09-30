# ICAI Slot Monitor

A free, self-hosted monitoring system that automatically checks the official **ICAI Launch Batch Details** page every ~5 minutes and sends you a Telegram notification after **every** check — whether or not a slot is available.

**Platform:** GitHub Actions + Python + Playwright + Telegram  
**Cost:** ₹0 — no paid hosting required  
**Official ICAI page:** https://www.icaionlineregistration.org/launchbatchdetail.aspx

---

## What This Monitor Does

Every ~5 minutes (continuously, 24/7), the monitor:

1. Opens the ICAI Launch Batch Details page using a real Chromium browser (Playwright)
2. Selects **Region: Southern** → **POU: CHENNAI** → the target course
3. Clicks **Get List** and reads the results table
4. Sends a Telegram message with the result — **even if no batch is found**

---

## Monitored Courses

| Name | Region | POU | Course |
|------|--------|-----|--------|
| Chennai Advanced MCS | Southern | CHENNAI | Advanced (ICITSS) MCS Course |
| Chennai Advanced ITT | Southern | CHENNAI | AICITSS - Advanced Information Technology |

> **Not monitored:** "Advanced (ICITSS) MCS Course - Weekend", "ICITSS - Information Technology", "ICITSS - Orientation Course"

---

## Telegram Message Format

### When no batch is available

```
🤖 ICAI SLOT MONITOR

Check #17: 30-09-2026 08:05:12 IST
Next check: ~5 minutes

📍 CHENNAI — Advanced MCS
❌ No qualifying batch found / no slot currently detected.

📍 CHENNAI — Advanced ITT
❌ No qualifying batch found / no slot currently detected.

Status: ✅ Check completed successfully

🔗 Open ICAI Batch Details
```

### When a batch is detected

```
🤖 ICAI SLOT MONITOR

Check #18: 30-09-2026 08:10:15 IST
Next check: ~5 minutes

📍 CHENNAI — Advanced MCS
✅ Batch detected — 12 seat(s) available
• Course: Advanced (ICITSS) MCS Course
• Available seats: 12
• Batch details:
  - [date / venue / other details from portal]

Status: ✅ Check completed successfully
```

### On ICAI website failure

```
⚠️ ICAI CHECK FAILED

Time: 30-09-2026 08:10:15 IST
Error: PlaywrightTimeoutError: ...

The monitoring loop will continue with the next check.
```

---

## Why a Long-Running Loop Instead of `*/5 * * * *` Cron

GitHub's scheduled workflows have a **minimum interval of 5 minutes** but can be significantly delayed during high-load periods. A `*/5` cron might fire every 10–30 minutes in practice.

This system uses a different approach:

```
GitHub Actions starts (every ~6 hours via cron)
        ↓
Python runs a long-running loop for ~350 minutes
        ↓
Every cycle: check → Telegram → wait 5 minutes → repeat
        ↓
Exit cleanly at ~350 minutes
        ↓
Next GitHub Actions session begins (next 6-hour cron)
```

The sleep logic is precise:

```python
start = time.monotonic()
check()
elapsed = time.monotonic() - start
time.sleep(max(0, 300 - elapsed))   # keep 5-minute intervals
```

This ensures the checks are always ~5 minutes apart, regardless of how long the scrape takes.

### Daily Schedule

| Session | Starts (IST) | Ends (IST) |
|---------|-------------|-----------|
| 1 | ~00:02 | ~05:52 |
| 2 | ~06:02 | ~11:52 |
| 3 | ~12:02 | ~17:52 |
| 4 | ~18:02 | ~23:52 |

A small handover gap exists between sessions. This is expected and safe.

---

## GitHub Setup Instructions

### Step 1 — Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456:ABC-DEF...`)
4. Add the bot to your chat/group, then find your **chat ID** using `@userinfobot` or the Telegram API

### Step 2 — Fork / Upload the Repository

Upload this project to a **public** GitHub repository (e.g. `yourusername/icai-slot-monitor`).

### Step 3 — Add GitHub Secrets

In your GitHub repository:

1. Go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret** and add:

| Secret Name | Value |
|-------------|-------|
| `ICAI_TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `ICAI_TELEGRAM_CHAT_ID` | Your Telegram chat/group ID |

> ⚠️ **Never** put these values in `config.yaml`, source code, README, or logs.

### Step 4 — Enable GitHub Actions

1. Go to **Actions** tab in your repository
2. If prompted, click **"I understand my workflows, enable them"**

### Step 5 — Test Manually

1. Go to **Actions → ICAI Slot Monitor → Run workflow**
2. Click **Run workflow** (leave defaults)
3. Watch the logs — you should see a Telegram message within ~2 minutes

---

## Manual Testing (Local)

### Prerequisites

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

### Set environment variables

**Linux/macOS:**
```bash
export ICAI_TELEGRAM_BOT_TOKEN="your-token"
export ICAI_TELEGRAM_CHAT_ID="your-chat-id"
```

**Windows (PowerShell):**
```powershell
$env:ICAI_TELEGRAM_BOT_TOKEN = "your-token"
$env:ICAI_TELEGRAM_CHAT_ID   = "your-chat-id"
```

### Run a single check (recommended for first test)

```bash
PYTHONPATH=src python -m icai_slot_monitor.cli --once
```

### Run a short loop (10 minutes, 5-minute interval)

```bash
PYTHONPATH=src python -m icai_slot_monitor.cli --loop-minutes 10 --interval-seconds 300
```

### Dry-run (no Telegram messages sent)

```bash
PYTHONPATH=src python -m icai_slot_monitor.cli --once --dry-run
```

### Full options

```
usage: python -m icai_slot_monitor.cli [options]

  --config PATH         Path to config.yaml (default: config/config.yaml)
  --state PATH          Path to state.json  (default: state/state.json)
  --once                Run one check and exit
  --dry-run             Never send Telegram messages
  --loop-minutes N      Session duration in minutes (overrides config)
  --interval-seconds N  Check interval in seconds (overrides config)
```

---

## Configuration

Edit [`config/config.yaml`](config/config.yaml) to adjust settings:

```yaml
monitor:
  loop_minutes: 350        # Session duration (keep < 360)
  interval_seconds: 300    # Check interval (5 minutes)
  telegram_enabled: true
  notification_mode: "every_check"  # Send on every check, not just on change
  minimum_available_seats: 1
```

### Changing the Monitored POU or Courses

Edit the `watches` section in `config/config.yaml`:

```yaml
watches:
  - name: "Chennai Advanced MCS"
    region: "Southern"
    pou: "CHENNAI"
    course_exact: "Advanced (ICITSS) MCS Course"
    course_contains:
      - "Advanced"
      - "MCS"
```

Use `course_exact` for an exact text match (recommended — prevents accidentally selecting the Weekend variant).

---

## How Automatic Monitoring Works

```
GitHub cron fires (4x per day)
         ↓
checkout + install deps (~2 min)
         ↓
python cli.py --loop-minutes 350 --interval-seconds 300
         ↓
Cycle 1: check ICAI → Telegram → sleep 5 min
Cycle 2: check ICAI → Telegram → sleep 5 min
         ...
Cycle ~70: check ICAI → Telegram
         ↓
350 minutes elapsed → exit cleanly
         ↓
Next cron fires → repeat
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No Telegram messages | Missing secrets | Check `ICAI_TELEGRAM_BOT_TOKEN` and `ICAI_TELEGRAM_CHAT_ID` in repo settings |
| "Telegram credentials missing" error | Secrets not set | Add both secrets as shown in setup |
| "Could not locate the ICAI 'Get List' control" | ICAI page changed | Check the debug screenshot in the `debug/` folder (created automatically) |
| "Course matching failed" | Course name changed on ICAI | Update `course_exact` in config.yaml |
| Workflow never starts | Actions disabled | Go to Actions tab → enable workflows |
| Two sessions running simultaneously | Concurrency group handles this | `cancel-in-progress: false` ensures the running session is never killed |
| Workflow exceeds 360 minutes | Should not happen with `loop_minutes: 350` | Reduce `loop_minutes` in config |

---

## Project Structure

```
icai-slot-monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml          # GitHub Actions workflow (6-hour schedule)
├── config/
│   └── config.yaml              # All settings and watch targets
├── src/
│   └── icai_slot_monitor/
│       ├── __init__.py
│       ├── cli.py               # Main entrypoint + long-running loop
│       ├── config.py            # Config loader
│       ├── icai.py              # Playwright scraper (ASP.NET postback handling)
│       ├── models.py            # Batch data model
│       ├── notifier.py          # Telegram message formatting + sending
│       └── state.py             # State persistence (saved once per session)
├── state/
│   └── state.json               # Last known state (not committed every check)
├── requirements.txt
└── README.md
```

---

## Security Notes

- Telegram credentials are stored **only** as GitHub repository secrets
- Credentials are **never** logged, printed, or written to files
- The monitor only reads the public ICAI page — no login, CAPTCHA solving, payment, or registration automation

---

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `ICAI_TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `ICAI_TELEGRAM_CHAT_ID` | Your Telegram chat or group ID |

---

## Changing the Check Interval

To check every 3 minutes instead of 5:

1. Edit `config/config.yaml`: set `interval_seconds: 180`
2. Commit and push

Or pass it at runtime:
```bash
python -m icai_slot_monitor.cli --interval-seconds 180 --loop-minutes 350
```

---

*This monitor only reads publicly available information from the ICAI website. It does not automate any registration, login, payment, or CAPTCHA solving.*
