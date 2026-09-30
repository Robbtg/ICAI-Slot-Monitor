from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import load_config
from .icai import ICAIClient
from .models import Batch
from .notifier import format_run_report, send_telegram
from .state import load_state, save_state, signature, snapshot


# ------------------------------------------------------------------ #
# Logging                                                              #
# ------------------------------------------------------------------ #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("icai-slot-monitor")

# Indian Standard Time offset
IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    return datetime.now(IST)


def _fmt_ist(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y %H:%M:%S IST")


def _group_by_watch(batches: list[Batch]) -> dict[str, list[Batch]]:
    grouped: dict[str, list[Batch]] = {}
    for batch in batches:
        grouped.setdefault(batch.watch_name, []).append(batch)
    return grouped


def _print_separator() -> None:
    log.info("=" * 50)


# ------------------------------------------------------------------ #
# Single check cycle                                                   #
# ------------------------------------------------------------------ #

def run_one_check(
    cfg,
    state_path: str,
    previous_state: dict,
    cycle: int,
    dry_run: bool,
) -> dict:
    """
    Perform one full ICAI check for all watches, send Telegram, return updated state.

    The function never raises — all errors are caught and reported.
    Returns the current previous_state (unchanged) on error.
    """
    watch_names = [w.name for w in cfg.watches]
    started_at_dt = _now_ist()
    started_at = _fmt_ist(started_at_dt)

    _print_separator()
    log.info("ICAI SLOT MONITOR")
    _print_separator()
    log.info("Cycle      : %d", cycle)
    log.info("Started    : %s", started_at)
    log.info("Targets    : %d", len(cfg.watches))

    # ---- Attempt scrape ----
    try:
        batches, watch_errors = ICAIClient(cfg).check()
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        log.exception("[ERROR] ICAI check failed — cycle %d", cycle)

        # Try to send a Telegram error report
        try:
            report = format_run_report(
                batches_by_watch={},
                watch_names=watch_names,
                portal_url=cfg.portal.url,
                started_at=started_at,
                cycle=cycle,
                error=error_text,
            )
            if not dry_run and cfg.monitor.telegram_enabled:
                send_telegram(report)
                log.info("Telegram failure report sent.")
            else:
                log.info("Dry-run / Telegram disabled — failure report:\n%s", report)
        except Exception as tg_exc:
            log.error("Telegram error report failed: %s", tg_exc)

        # Return existing state; the loop continues
        return previous_state

    # ---- Log results per watch ----
    for i, watch in enumerate(cfg.watches, 1):
        if watch.name in watch_errors:
            log.error("[%d/%d] %s", i, len(cfg.watches), watch.name)
            log.error("  Region   : %s", watch.region)
            log.error("  POU      : %s", watch.pou)
            log.error("  Course   : %s", watch.course_exact or str(watch.course_contains))
            log.error("  [ERROR]  : %s", watch_errors[watch.name])
        else:
            watch_batches = [b for b in batches if b.watch_name == watch.name]
            result_str = f"{len(watch_batches)} batch(es) found" if watch_batches else "NO BATCH"
            log.info("[%d/%d] %s", i, len(cfg.watches), watch.name)
            log.info("  Region   : %s", watch.region)
            log.info("  POU      : %s", watch.pou)
            log.info("  Course   : %s", watch.course_exact or str(watch.course_contains))
            log.info("  Result   : %s", result_str)
            for batch in watch_batches:
                seats = "unknown" if batch.available_seats is None else str(batch.available_seats)
                log.info("    Seats: %s | %s", seats, " | ".join(batch.values))

    # ---- Format and send Telegram ----
    grouped = _group_by_watch(batches)
    report = format_run_report(
        batches_by_watch=grouped,
        watch_names=watch_names,
        portal_url=cfg.portal.url,
        started_at=started_at,
        cycle=cycle,
        errors_by_watch=watch_errors,
    )

    telegram_status = "SKIPPED (dry-run or disabled)"
    if not dry_run and cfg.monitor.telegram_enabled:
        try:
            send_telegram(report)
            telegram_status = "SENT"
        except Exception as tg_exc:
            telegram_status = f"FAILED — {tg_exc}"
            log.error("Telegram send failed: %s", tg_exc)
    else:
        log.info("Dry-run / Telegram disabled — report:\n%s", report)

    log.info("Telegram   : %s", telegram_status)

    # ---- Update in-memory state ----
    current_snap = snapshot(batches)
    current_sig = signature(current_snap)
    previous_sig = previous_state.get("_signature")

    if current_sig != previous_sig:
        current_snap["_signature"] = current_sig
        log.info("State      : CHANGED (will persist at session end)")
        return current_snap
    else:
        log.info("State      : unchanged")
        return previous_state


# ------------------------------------------------------------------ #
# Main entry point                                                     #
# ------------------------------------------------------------------ #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="ICAI public batch availability monitor"
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "--state",
        default="state/state.json",
        help="Path to state.json (default: state/state.json)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check and exit (test mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Never send Telegram messages",
    )
    parser.add_argument(
        "--loop-minutes",
        type=int,
        default=None,
        help="Total monitoring session duration in minutes (overrides config)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=None,
        help="Check interval in seconds (overrides config)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    # CLI overrides take precedence over config file
    loop_minutes = args.loop_minutes if args.loop_minutes is not None else cfg.monitor.loop_minutes
    interval_seconds = args.interval_seconds if args.interval_seconds is not None else cfg.monitor.interval_seconds

    previous_state = load_state(args.state)

    log.info("=" * 50)
    log.info("ICAI SLOT MONITOR — SESSION START")
    log.info("=" * 50)
    log.info("Config     : %s", args.config)
    log.info("State      : %s", args.state)
    log.info("Watches    : %d", len(cfg.watches))
    log.info("Mode       : %s", "once" if args.once else f"loop ({loop_minutes} min, {interval_seconds}s interval)")
    log.info("Telegram   : %s", "disabled (dry-run)" if args.dry_run else ("enabled" if cfg.monitor.telegram_enabled else "disabled (config)"))

    session_start = time.monotonic()
    session_limit_seconds = loop_minutes * 60

    cycle = 0

    while True:
        cycle += 1
        cycle_start = time.monotonic()

        previous_state = run_one_check(
            cfg=cfg,
            state_path=args.state,
            previous_state=previous_state,
            cycle=cycle,
            dry_run=args.dry_run,
        )

        # --once exits after first check
        if args.once:
            log.info("--once mode: exiting after cycle %d.", cycle)
            break

        elapsed_session = time.monotonic() - session_start
        remaining_session = session_limit_seconds - elapsed_session

        if remaining_session <= 0:
            log.info("Session duration reached (%d min). Exiting cleanly.", loop_minutes)
            break

        # Calculate how long the check itself took
        cycle_elapsed = time.monotonic() - cycle_start
        sleep_time = max(0.0, interval_seconds - cycle_elapsed)

        # Don't sleep longer than remaining session time
        sleep_time = min(sleep_time, remaining_session)

        next_check_dt = _now_ist() + timedelta(seconds=sleep_time)
        log.info(
            "Next check in: %.0f seconds (~%s IST)",
            sleep_time,
            _fmt_ist(next_check_dt),
        )
        _print_separator()

        time.sleep(sleep_time)

        # Re-check session limit after sleeping
        elapsed_session = time.monotonic() - session_start
        if elapsed_session >= session_limit_seconds:
            log.info("Session duration reached (%d min). Exiting cleanly.", loop_minutes)
            break

    # ---- Persist state once at session end ----
    try:
        save_state(args.state, previous_state)
        log.info("Session state saved to %s", args.state)
    except Exception as exc:
        log.error("Failed to save state: %s", exc)

    log.info("=" * 50)
    log.info("ICAI SLOT MONITOR — SESSION END (cycle %d completed)", cycle)
    log.info("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
