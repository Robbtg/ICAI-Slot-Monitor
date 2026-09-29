# ICAI Chennai Slot Monitor

A lightweight Python + Playwright monitor for the public ICAI **Launch Batch Details** page.

## What this version checks

Every scheduled run checks exactly two Chennai watches:

1. **Chennai MCS**
2. **Chennai Advanced ITT**

Both use:

- Region: `Southern`
- POU: `CHENNAI`
- Course matching by visible text fragments

Official page:
https://www.icaionlineregistration.org/launchbatchdetail.aspx

## Telegram behavior

This version intentionally sends **one Telegram status report on every successful run**, even when no slot is available.

Example when nothing is available:

```text
🤖 ICAI SLOT MONITOR

Checked: 29-09-2026 23:05:12 IST
Frequency: ~5 minutes

📌 Chennai MCS
❌ No qualifying batch found / no slot currently detected.

📌 Chennai Advanced ITT
❌ No qualifying batch found / no slot currently detected.
```

If a batch is found, the report includes the course, available seats (when the portal exposes them), and the returned batch details.

If the ICAI page fails, the bot sends a **CHECK FAILED** Telegram message so you know the monitor itself did not complete normally.

## Important scheduling note

GitHub Actions scheduled jobs are **best effort**. The workflow is configured at 2, 7, 12, 17, etc. minutes past each hour to approximate a 5-minute cadence while reducing exact top-of-hour contention. GitHub may delay a scheduled run under platform load.

## Telegram setup

Create a bot with `@BotFather`, then add these GitHub repository secrets:

- `ICAI_TELEGRAM_BOT_TOKEN`
- `ICAI_TELEGRAM_CHAT_ID`

Do not place the token in `config.yaml`.

## GitHub deployment

1. Create a GitHub repository.
2. Upload this project.
3. Add the two Telegram secrets.
4. Open **Actions → ICAI Slot Monitor → Run workflow** for an immediate test.
5. The scheduled workflow then runs approximately every five minutes.

## Local test

### Linux/macOS

```bash
./run_local.sh
```

### Windows

```bat
run_local.bat
```

A local run requires Playwright Chromium and the same Telegram environment variables.

For a dry run without sending Telegram messages:

```bash
PYTHONPATH=src python -m icai_slot_monitor.cli --config config/config.yaml --state state/state.json --once --dry-run
```

## Project safety / scope

The monitor only reads the public ICAI Launch Batch Details page and sends notifications. It does not automate ICAI login, CAPTCHA solving, payment, or final registration submission.
