# Operations Guide

## First run

1. Create a Telegram bot with `@BotFather`.
2. Obtain the target chat ID.
3. Add `ICAI_TELEGRAM_BOT_TOKEN` and `ICAI_TELEGRAM_CHAT_ID` to GitHub Actions secrets.
4. Run the workflow manually once.
5. Confirm the Telegram message contains Chennai Advanced MCS watch.

## Expected Telegram messages

The bot monitors Chennai Advanced MCS Course:

- Immediate alert when batches with seats become available
- Periodic compact summary every 30 minutes (30 checks)
- Final status report on the last search of the run time (session completion)

## If the ICAI page changes

The Playwright adapter dynamically looks for labels, select controls, and the result table instead of relying on fixed screen coordinates. If the portal's structure changes materially, inspect the `debug/` files created after a failed run.

## State file

`state/state.json` keeps the last successful portal snapshot. It is not required for sending the per-run Telegram report, but it provides useful change history and avoids losing context across GitHub runners.

## Local testing

Use `--dry-run` first if you want to inspect the generated report without sending Telegram messages.
