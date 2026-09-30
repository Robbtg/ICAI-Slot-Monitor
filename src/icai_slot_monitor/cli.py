from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import load_config
from .icai import ICAIClient
from .models import Batch
from .notifier import (
    format_batch_alert,
    format_summary_report,
    format_error_report,
    send_telegram,
)
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
# Check result data class                                              #
# ------------------------------------------------------------------ #

class CheckResult:
    """Holds the outcome of a single ICAI check cycle."""

    def __init__(
        self,
        cycle: int,
        checked_at: str,
        batches_by_watch: dict[str, list[Batch]],
        errors_by_watch: dict[str, str],
        scrape_failed: bool = False,
        error: str | None = None,
    ):
        self.cycle = cycle
        self.checked_at = checked_at
        self.batches_by_watch = batches_by_watch
        self.errors_by_watch = errors_by_watch
        self.scrape_failed = scrape_failed
        self.error = error

    @property
    def has_available_batch(self) -> bool:
        """True if at least one watch found a batch with seats > 0."""
        for batches in self.batches_by_watch.values():
            for b in batches:
                if b.available_seats is None or b.available_seats > 0:
                    return True
        return False

    @property
    def has_watch_error(self) -> bool:
        return bool(self.errors_by_watch)


# ------------------------------------------------------------------ #
# Single check cycle                                                   #
# ------------------------------------------------------------------ #

def run_one_check(
    cfg,
    cycle: int,
) -> CheckResult:
    """
    Perform one full ICAI check for all watches.
    Never raises — all errors are caught and returned in CheckResult.
    """
    watch_names = [w.name for w in cfg.watches]
    checked_at = _fmt_ist(_now_ist())

    _print_separator()
    log.info("ICAI SLOT MONITOR")
    _print_separator()
    log.info("Cycle      : %d", cycle)
    log.info("Started    : %s", checked_at)
    log.info("Targets    : %d", len(cfg.watches))

    # ---- Attempt scrape ----
    try:
        batches, watch_errors = ICAIClient(cfg).check()
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        log.exception("[ERROR] ICAI check failed — cycle %d", cycle)
        return CheckResult(
            cycle=cycle,
            checked_at=checked_at,
            batches_by_watch={},
            errors_by_watch={},
            scrape_failed=True,
            error=error_text,
        )

    # ---- Log results per watch ----
    for i, watch in enumerate(cfg.watches, 1):
        if watch.name in watch_errors:
            log.error("[%d/%d] %s", i, len(cfg.watches), watch.name)
            log.error("  [ERROR]  : %s", watch_errors[watch.name])
        else:
            watch_batches = [b for b in batches if b.watch_name == watch.name]
            result_str = f"{len(watch_batches)} batch(es) found" if watch_batches else "NO BATCH"
            log.info("[%d/%d] %s → %s", i, len(cfg.watches), watch.name, result_str)
            for batch in watch_batches:
                seats = "unknown" if batch.available_seats is None else str(batch.available_seats)
                log.info("    Seats: %s | %s", seats, " | ".join(batch.values))

    return CheckResult(
        cycle=cycle,
        checked_at=checked_at,
        batches_by_watch=_group_by_watch(batches),
        errors_by_watch=watch_errors,
    )


# ------------------------------------------------------------------ #
# Notification decision engine                                         #
# ------------------------------------------------------------------ #

def maybe_notify(
    result: CheckResult,
    silent_results: list[CheckResult],
    summary_every_n: int,
    cfg,
    dry_run: bool,
    watch_names: list[str],
) -> list[CheckResult]:
    """
    Decide what (if anything) to send to Telegram.

    Rules:
      1. Scrape error → send error alert immediately, reset silent counter.
      2. Batch with seats available → send urgent alert immediately.
         (silent_results counter keeps running — no reset on alerts).
      3. No batch / 0 seats → accumulate silently.
         When silent_results reaches summary_every_n, send summary + reset.

    Returns the updated silent_results list.
    """

    def _send(message: str, label: str) -> None:
        if dry_run or not cfg.monitor.telegram_enabled:
            log.info("Dry-run / Telegram disabled — %s:\n%s", label, message)
        else:
            try:
                send_telegram(message)
                log.info("Telegram SENT (%s)", label)
            except Exception as tg_exc:
                log.error("Telegram send failed (%s): %s", label, tg_exc)

    # Rule 1: Scrape error → immediate alert
    if result.scrape_failed:
        msg = format_error_report(
            error=result.error or "Unknown error",
            checked_at=result.checked_at,
            cycle=result.cycle,
            portal_url=cfg.portal.url,
        )
        _send(msg, "scrape-error")
        # Reset silent accumulator on error so the next summary is fresh
        return []

    # Rule 2: Batch with seats → send immediate alert
    if result.has_available_batch:
        for watch_name in watch_names:
            batches = result.batches_by_watch.get(watch_name, [])
            for batch in batches:
                if batch.available_seats is None or batch.available_seats > 0:
                    msg = format_batch_alert(
                        batch=batch,
                        checked_at=result.checked_at,
                        cycle=result.cycle,
                        portal_url=cfg.portal.url,
                    )
                    _send(msg, f"BATCH ALERT — {watch_name}")

        # Add this result to silent list but DON'T reset — still count toward summary
        silent_results.append(result)
    else:
        # Rule 3: Nothing found — accumulate
        silent_results.append(result)
        log.info(
            "No batch found — silent check %d/%d",
            len(silent_results),
            summary_every_n,
        )

    # Send summary every N accumulated results
    if len(silent_results) >= summary_every_n:
        msg = format_summary_report(
            results=silent_results,
            watch_names=watch_names,
            portal_url=cfg.portal.url,
        )
        _send(msg, f"summary ({len(silent_results)} checks)")
        return []  # Reset accumulator

    return silent_results


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
    summary_every_n = cfg.monitor.summary_every_n_checks

    watch_names = [w.name for w in cfg.watches]
    previous_state = load_state(args.state)

    log.info("=" * 50)
    log.info("ICAI SLOT MONITOR — SESSION START")
    log.info("=" * 50)
    log.info("Config     : %s", args.config)
    log.info("State      : %s", args.state)
    log.info("Watches    : %d", len(cfg.watches))
    log.info(
        "Mode       : %s",
        "once" if args.once else f"loop ({loop_minutes} min, {interval_seconds}s interval)",
    )
    log.info(
        "Notify     : batch alerts immediately | summary every %d checks",
        summary_every_n,
    )
    log.info(
        "Telegram   : %s",
        "disabled (dry-run)" if args.dry_run else ("enabled" if cfg.monitor.telegram_enabled else "disabled (config)"),
    )

    session_start = time.monotonic()
    session_limit_seconds = loop_minutes * 60

    cycle = 0
    # Accumulator for silent (no-batch) checks
    silent_results: list[CheckResult] = []

    while True:
        cycle += 1
        cycle_start = time.monotonic()

        result = run_one_check(cfg=cfg, cycle=cycle)

        # Update in-memory state
        if not result.scrape_failed:
            all_batches = [b for bl in result.batches_by_watch.values() for b in bl]
            current_snap = snapshot(all_batches)
            current_sig = signature(current_snap)
            if current_sig != previous_state.get("_signature"):
                current_snap["_signature"] = current_sig
                previous_state = current_snap
                log.info("State      : CHANGED")
            else:
                log.info("State      : unchanged")

        # Notification decision
        silent_results = maybe_notify(
            result=result,
            silent_results=silent_results,
            summary_every_n=summary_every_n,
            cfg=cfg,
            dry_run=args.dry_run,
            watch_names=watch_names,
        )

        # --once exits after first check
        if args.once:
            # Flush any pending silent results as a summary before exiting
            if silent_results and not result.scrape_failed:
                from .notifier import format_summary_report
                msg = format_summary_report(
                    results=silent_results,
                    watch_names=watch_names,
                    portal_url=cfg.portal.url,
                )
                if not args.dry_run and cfg.monitor.telegram_enabled:
                    try:
                        send_telegram(msg)
                        log.info("Telegram SENT (final summary on --once exit)")
                    except Exception as tg_exc:
                        log.error("Telegram final summary failed: %s", tg_exc)
                else:
                    log.info("Dry-run: final summary:\n%s", msg)
            log.info("--once mode: exiting after cycle %d.", cycle)
            break

        elapsed_session = time.monotonic() - session_start
        remaining_session = session_limit_seconds - elapsed_session

        if remaining_session <= 0:
            log.info("Session duration reached (%d min). Exiting cleanly.", loop_minutes)
            break

        # Calculate sleep time
        cycle_elapsed = time.monotonic() - cycle_start
        sleep_time = max(0.0, interval_seconds - cycle_elapsed)
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
