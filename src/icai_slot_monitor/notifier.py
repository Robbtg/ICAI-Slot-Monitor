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

    # Split into chunks to respect Telegram's message length limit.
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


def _batch_details(batch: Batch) -> list[str]:
    values = [str(v).strip() for v in batch.values if str(v).strip()]
    details = [f"• <b>Course:</b> {escape(batch.course)}"]

    seats = (
        str(batch.available_seats)
        if batch.available_seats is not None
        else "Unknown (not exposed by portal)"
    )
    details.append(f"• <b>Available seats:</b> {escape(seats)}")

    if values:
        details.append("• <b>Batch details:</b>")
        details.extend(f"  - {escape(v)}" for v in values)

    return details


def format_run_report(
    batches_by_watch: dict[str, list[Batch]],
    watch_names: list[str],
    portal_url: str,
    *,
    started_at: str,
    cycle: int = 0,
    error: str | None = None,
    errors_by_watch: dict[str, str] | None = None,
) -> str:
    """Build the Telegram message sent on every monitor check."""
    cycle_str = f" #{cycle}" if cycle else ""
    lines = [
        "🤖 <b>ICAI SLOT MONITOR</b>",
        "",
        f"<b>Check{cycle_str}:</b> {escape(started_at)}",
        "<b>Next check:</b> ~5 minutes",
        "",
    ]

    # ---- Global failure (ICAI scrape itself threw) ----
    if error:
        lines.extend(
            [
                "⚠️ <b>ICAI CHECK FAILED</b>",
                "",
                f"<b>Time:</b> {escape(started_at)}",
                f"<b>Error:</b> {escape(error)}",
                "",
                "No availability result could be confirmed for this run.",
                "The monitoring loop will continue with the next check.",
                "",
                f'🔗 <a href="{escape(portal_url)}">Open ICAI Batch Details</a>',
            ]
        )
        return "\n".join(lines)

    errors_by_watch = errors_by_watch or {}

    # ---- Per-watch results ----
    for watch_name in watch_names:
        lines.append(f"📍 <b>CHENNAI — {escape(watch_name.replace('Chennai ', ''))}</b>")

        if watch_name in errors_by_watch:
            lines.append("⚠️ <b>CHECK ERROR</b>")
            lines.append(f"<b>Error:</b> {escape(errors_by_watch[watch_name])}")
            lines.append("")
            continue

        batches = batches_by_watch.get(watch_name, [])

        if not batches:
            lines.append("❌ No qualifying batch found / no slot currently detected.")
            lines.append("")
            continue

        available_count = 0
        for batch in batches:
            if batch.available_seats is None:
                status = "⚠️ Batch found — seat count not exposed by portal"
            elif batch.available_seats > 0:
                available_count += 1
                status = f"✅ <b>Batch detected — {batch.available_seats} seat(s) available</b>"
            else:
                status = "⛔ Batch found — 0 seats available"

            lines.append(status)
            lines.extend(_batch_details(batch))
            lines.append("")

        lines.append(f"<b>Qualifying batches:</b> {len(batches)}")
        lines.append(f"<b>Batches with seats:</b> {available_count}")
        lines.append("")

    lines.extend(
        [
            "Status: ✅ Check completed successfully",
            "",
            f'🔗 <a href="{escape(portal_url)}">Open ICAI Batch Details</a>',
        ]
    )
    return "\n".join(lines)


def format_alert(batch: Batch, reason: str, portal_url: str) -> str:
    """Backward-compatible event alert formatter (kept for reference)."""
    values = "\n".join(f"• {escape(v)}" for v in batch.values if str(v).strip())
    seats = (
        str(batch.available_seats)
        if batch.available_seats is not None
        else "Unknown (not exposed by portal)"
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
