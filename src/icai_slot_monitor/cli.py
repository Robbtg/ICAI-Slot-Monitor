from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from .config import load_config
from .icai import ICAIClient
from .models import Batch
from .notifier import format_run_report, send_telegram
from .state import load_state, save_state, signature, snapshot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("icai-slot-monitor")


def _group_by_watch(batches: list[Batch]) -> dict[str, list[Batch]]:
    grouped: dict[str, list[Batch]] = {}
    for batch in batches:
        grouped.setdefault(batch.watch_name, []).append(batch)
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(description="ICAI public batch availability monitor")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--state", default="state/state.json")
    parser.add_argument("--once", action="store_true", help="Run one check and exit")
    parser.add_argument("--dry-run", action="store_true", help="Never send Telegram messages")
    args = parser.parse_args()

    cfg = load_config(args.config)
    previous = load_state(args.state)
    checked_at = datetime.now().astimezone().strftime("%d-%m-%Y %H:%M:%S %Z")

    log.info("Checking %d watch(es)", len(cfg.watches))
    log.info("Telegram mode: %s", "disabled (dry-run)" if args.dry_run else "every run")

    try:
        batches, watch_errors = ICAIClient(cfg).check()
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        log.exception("ICAI check failed")

        report = format_run_report(
            batches_by_watch={},
            watch_names=[watch.name for watch in cfg.watches],
            portal_url=cfg.portal.url,
            started_at=checked_at,
            error=error_text,
        )

        if not args.dry_run:
            send_telegram(report)
            log.info("Telegram failure report sent.")
        else:
            log.info("Dry-run failure report:\n%s", report)
        return 1

    current = snapshot(batches)
    current_sig = signature(current)
    previous_sig = previous.get("_signature")

    log.info("Found %d qualifying batch row(s)", len(batches))
    for watch_name, error in watch_errors.items():
        log.error("[%s] %s", watch_name, error)
    for batch in batches:
        seats = "unknown" if batch.available_seats is None else str(batch.available_seats)
        log.info(
            "[%s] %s | seats=%s | %s",
            batch.watch_name,
            batch.course,
            seats,
            " | ".join(batch.values),
        )

    grouped = _group_by_watch(batches)
    report = format_run_report(
        batches_by_watch=grouped,
        watch_names=[watch.name for watch in cfg.watches],
        portal_url=cfg.portal.url,
        started_at=checked_at,
        errors_by_watch=watch_errors,
    )

    if not args.dry_run:
        send_telegram(report)
        log.info("Telegram status report sent for this run.")
    else:
        log.info("Dry-run report:\n%s", report)

    # Save state after the run. State is still
    # useful for history/debugging, but alerts are now sent every run.
    if current_sig != previous_sig:
        current["_signature"] = current_sig
        save_state(args.state, current)
        log.info("State changed and was saved.")
    else:
        log.info("No state change.")

    # A handled per-watch portal error is reported to Telegram, so keep the
    # scheduled monitor green unless the overall run/notification itself failed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
