from __future__ import annotations

import os
from html import escape

import requests

from .models import Batch


TELEGRAM_MAX_MESSAGE_LENGTH = 3900


def _credentials() -> tuple[str, str]:
    token = os.getenv("ICAI_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ICAI_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "Telegram credentials are missing. Set ICAI_TELEGRAM_BOT_TOKEN and ICAI_TELEGRAM_CHAT_ID."
        )
    return token, chat_id


def send_telegram(message: str) -> None:
    """Send a Telegram message. Raises on failure — caller must handle."""
    token, chat_id = _credentials()
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    chunks = [
        message[i : i + TELEGRAM_MAX_MESSAGE_LENGTH]
        for i in range(0, len(message), TELEGRAM_MAX_MESSAGE_LENGTH)
    ] or [""]

    for chunk in chunks:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()


def _batch_lines(batch: Batch) -> list[str]:
    """Format a single batch's details as a list of HTML lines."""
    lines = []
    seats = (
        str(batch.available_seats)
        if batch.available_seats is not None
        else "Unknown"
    )
    lines.append(f"• <b>Course:</b> {escape(batch.course)}")
    lines.append(f"• <b>Available seats:</b> {escape(seats)}")

    values = [str(v).strip() for v in batch.values if str(v).strip()]
    if values:
        lines.append("• <b>Batch details:</b>")
        lines.extend(f"  - {escape(v)}" for v in values)

    return lines


# ------------------------------------------------------------------ #
# Message formatters                                                   #
# ------------------------------------------------------------------ #

def format_batch_alert(
    batch: Batch,
    checked_at: str,
    cycle: int,
    portal_url: str,
) -> str:
    """
    Urgent alert sent immediately when a batch with available seats is found.
    Sent on EVERY cycle where a batch is found.
    """
    seats = (
        str(batch.available_seats)
        if batch.available_seats is not None
        else "Unknown (not exposed by portal)"
    )

    lines = [
        "🚨 <b>ICAI BATCH AVAILABLE!</b>",
        "",
        f"<b>Watch:</b> {escape(batch.watch_name)}",
        f"<b>Checked:</b> {escape(checked_at)} (cycle #{cycle})",
        "",
        f"✅ <b>Available seats: {escape(seats)}</b>",
    ]
    lines.extend(_batch_lines(batch))
    lines.extend([
        "",
        f'🔗 <a href="{escape(portal_url)}">👉 Register NOW on ICAI portal</a>',
    ])
    return "\n".join(lines)


def format_summary_report(
    results: list,  # list[CheckResult] — imported lazily to avoid circular
    watch_names: list[str],
    portal_url: str,
) -> str:
    """
    Periodic summary sent after every N silent (no-batch) checks.
    Compact — one line per watch per check.
    """
    n = len(results)
    first_at = results[0].checked_at if results else "?"
    last_at = results[-1].checked_at if results else "?"

    lines = [
        f"📋 <b>ICAI MONITOR — {n}-Check Summary</b>",
        "",
        f"<b>Period:</b> {escape(first_at)} → {escape(last_at)}",
        f"<b>Checks:</b> #{results[0].cycle} – #{results[-1].cycle}" if results else "",
        "",
    ]

    # Per-watch mini table
    for watch_name in watch_names:
        found_count = 0
        alert_count = 0
        for r in results:
            batches = r.batches_by_watch.get(watch_name, [])
            if batches:
                found_count += 1
                for b in batches:
                    if b.available_seats is None or b.available_seats > 0:
                        alert_count += 1

        short_name = watch_name.replace("Chennai ", "")
        if alert_count > 0:
            lines.append(
                f"📍 <b>CHENNAI — {escape(short_name)}</b>: "
                f"🚨 SEATS AVAILABLE in {alert_count}/{n} checks!"
            )
        elif found_count > 0:
            lines.append(
                f"📍 <b>CHENNAI — {escape(short_name)}</b>: "
                f"⛔ Batch found but 0 seats in {found_count}/{n} checks"
            )
        else:
            lines.append(
                f"📍 <b>CHENNAI — {escape(short_name)}</b>: "
                f"❌ No batch in all {n} checks"
            )

    lines.extend([
        "",
        f"<i>Next summary after {n} more checks (~{n * 5} min)</i>",
        "",
        f'🔗 <a href="{escape(portal_url)}">ICAI Batch Details</a>',
    ])
    return "\n".join(lines)


def format_error_report(
    error: str,
    checked_at: str,
    cycle: int,
    portal_url: str,
) -> str:
    """Alert sent immediately when the ICAI scrape itself fails."""
    lines = [
        "⚠️ <b>ICAI CHECK FAILED</b>",
        "",
        f"<b>Time:</b> {escape(checked_at)} (cycle #{cycle})",
        f"<b>Error:</b> {escape(error)}",
        "",
        "No availability result for this check.",
        "The monitoring loop will continue.",
        "",
        f'🔗 <a href="{escape(portal_url)}">ICAI Batch Details</a>',
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Legacy — kept for backwards compatibility only                       #
# ------------------------------------------------------------------ #

def format_run_report(
    batches_by_watch: dict,
    watch_names: list[str],
    portal_url: str,
    *,
    started_at: str,
    cycle: int = 0,
    error: str | None = None,
    errors_by_watch: dict | None = None,
) -> str:
    """Legacy full-report formatter. Not used in v1.3+ flow."""
    if error:
        return format_error_report(
            error=error,
            checked_at=started_at,
            cycle=cycle,
            portal_url=portal_url,
        )
    # Build a minimal summary for backwards compat
    lines = [
        "🤖 <b>ICAI SLOT MONITOR</b>",
        "",
        f"<b>Check #{cycle}:</b> {escape(started_at)}",
        "",
    ]
    errors_by_watch = errors_by_watch or {}
    for watch_name in watch_names:
        short = watch_name.replace("Chennai ", "")
        if watch_name in errors_by_watch:
            lines.append(f"📍 <b>CHENNAI — {escape(short)}:</b> ⚠️ check error")
        else:
            batches = batches_by_watch.get(watch_name, [])
            if batches:
                lines.append(f"📍 <b>CHENNAI — {escape(short)}:</b> ✅ {len(batches)} batch(es) found")
            else:
                lines.append(f"📍 <b>CHENNAI — {escape(short)}:</b> ❌ No batch")
    lines.extend(["", f'🔗 <a href="{escape(portal_url)}">ICAI Batch Details</a>'])
    return "\n".join(lines)


def format_alert(batch: Batch, reason: str, portal_url: str) -> str:
    """Legacy event alert formatter (kept for reference)."""
    values = "\n".join(f"• {escape(v)}" for v in batch.values if str(v).strip())
    seats = (
        str(batch.available_seats)
        if batch.available_seats is not None
        else "Unknown"
    )
    return (
        "🚨 <b>ICAI BATCH OPENING</b>\n\n"
        f"<b>Watch:</b> {escape(batch.watch_name)}\n"
        f"<b>Course:</b> {escape(batch.course)}\n"
        f"<b>Reason:</b> {escape(reason)}\n"
        f"<b>Available seats:</b> {escape(seats)}\n\n"
        f"<b>Batch details:</b>\n{values}\n\n"
        f'🔗 <a href="{escape(portal_url)}">Open ICAI Batch Details</a>'
    )
