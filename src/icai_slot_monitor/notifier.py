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
    token, chat_id = _credentials()
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Telegram has a message-length limit. The monitor normally sends a
    # compact report, but splitting keeps a long portal response safe.
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
        else "Not exposed by portal"
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
    error: str | None = None,
) -> str:
    """Build the Telegram message sent on every monitor run."""
    lines = [
        "🤖 <b>ICAI SLOT MONITOR</b>",
        "",
        f"<b>Checked:</b> {escape(started_at)}",
        "<b>Frequency:</b> ~5 minutes",
        "",
    ]

    if error:
        lines.extend(
            [
                "❌ <b>CHECK FAILED</b>",
                f"<b>Error:</b> {escape(error)}",
                "",
                "No availability result could be confirmed for this run.",
                "",
                f'🔗 <a href="{escape(portal_url)}">Open ICAI Batch Details</a>',
            ]
        )
        return "\n".join(lines)

    for watch_name in watch_names:
        lines.append(f"📌 <b>{escape(watch_name)}</b>")
        batches = batches_by_watch.get(watch_name, [])

        if not batches:
            lines.append("❌ No qualifying batch found / no slot currently detected.")
            lines.append("")
            continue

        # A qualifying watch may return multiple rows/batches.
        available_count = 0
        for batch in batches:
            if batch.available_seats is None:
                status = "⚠️ Batch found; seat count not exposed"
            elif batch.available_seats > 0:
                available_count += 1
                status = f"✅ <b>{batch.available_seats} seat(s) available</b>"
            else:
                status = "⛔ Batch found; 0 seats available"

            lines.append(status)
            lines.extend(_batch_details(batch))
            lines.append("")

        lines.append(f"<b>Qualifying batches:</b> {len(batches)}")
        lines.append(f"<b>Batches with seats:</b> {available_count}")
        lines.append("")

    lines.extend(
        [
            f'🔗 <a href="{escape(portal_url)}">Open ICAI Batch Details</a>',
            "",
            "This report is sent on every scheduled check.",
        ]
    )
    return "\n".join(lines)


def format_alert(batch: Batch, reason: str, portal_url: str) -> str:
    """Backward-compatible event alert formatter."""
    values = "\n".join(f"• {escape(v)}" for v in batch.values if str(v).strip())
    seats = (
        str(batch.available_seats)
        if batch.available_seats is not None
        else "Not exposed by portal"
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
