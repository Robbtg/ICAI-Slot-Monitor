from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import AppConfig, Watch
from .models import Batch


@dataclass
class SelectInfo:
    selector: str
    options: list[str]


def _normal(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def _find_select_by_nearby_label(page: Page, label: str) -> str | None:
    """
    Prefer semantic/label based discovery. Falls back to common ICAI control names.
    """
    target = _normal(label)

    # Label -> select association.
    labels = page.locator("label")
    for i in range(labels.count()):
        lab = labels.nth(i)
        txt = _normal(lab.inner_text())
        if target in txt:
            for_id = lab.get_attribute("for")
            if for_id:
                return f"#{for_id}"

    # Select whose preceding text contains the requested label.
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        ident = sel.get_attribute("id")
        if not ident:
            continue
        # XPath is used only to inspect local surrounding text.
        try:
            parent_text = _normal(sel.locator("xpath=..").inner_text())
            if target in parent_text:
                return f"#{ident}"
        except Exception:
            pass

    return None


def _all_selects(page: Page) -> list[SelectInfo]:
    result: list[SelectInfo] = []
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        ident = sel.get_attribute("id")
        if not ident:
            continue
        options = [
            x.strip()
            for x in sel.locator("option").all_inner_texts()
            if x.strip()
        ]
        result.append(SelectInfo(f"#{ident}", options))
    return result


def _choose_select(selects: list[SelectInfo], candidates: Iterable[str]) -> str:
    candidates = [_normal(x) for x in candidates]
    for item in selects:
        joined = " ".join(_normal(x) for x in item.options[:5])
        if any(c in joined for c in candidates):
            return item.selector
    raise RuntimeError(f"Could not identify select control. Available controls: {selects}")


def _select_by_text(page: Page, selector: str, text: str) -> None:
    options = page.locator(f"{selector} option").all_inner_texts()
    desired = _normal(text)

    exact = next((x for x in options if _normal(x) == desired), None)
    partial = next((x for x in options if desired in _normal(x)), None)
    choice = exact or partial

    if not choice:
        raise RuntimeError(
            f"Option {text!r} not found in {selector}. Available: {options[:80]}"
        )

    page.locator(selector).select_option(label=choice)


def _course_selector(page: Page, fragments: tuple[str, ...]) -> tuple[str, str]:
    selects = _all_selects(page)
    wanted = [_normal(x) for x in fragments]

    best: tuple[int, SelectInfo, str] | None = None
    for sel in selects:
        for option in sel.options:
            n = _normal(option)
            score = sum(1 for f in wanted if f in n)
            if score:
                candidate = (score, sel, option)
                if best is None or candidate[0] > best[0]:
                    best = candidate

    if not best:
        raise RuntimeError(
            f"Course matching {fragments!r} failed. Select controls: {selects}"
        )

    return best[1].selector, best[2]


def _wait_for_postback(page: Page, old_signature: str) -> None:
    # ASP.NET pages often replace select contents after a postback.
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        pass


def _extract_table(page: Page, watch: Watch, course_text: str, min_seats: int) -> list[Batch]:
    tables = page.locator("table")
    batches: list[Batch] = []

    for ti in range(tables.count()):
        table = tables.nth(ti)
        rows = table.locator("tr")
        if rows.count() < 2:
            continue

        headers = [re.sub(r"\s+", " ", x).strip() for x in rows.nth(0).locator("th,td").all_inner_texts()]
        if not headers:
            continue

        # Convert every row into a compact tuple. The actual portal has changed
        # table presentation over time, so extraction is intentionally generic.
        for ri in range(1, rows.count()):
            cells = [
                re.sub(r"\s+", " ", x).strip()
                for x in rows.nth(ri).locator("td,th").all_inner_texts()
            ]
            if not cells:
                continue

            row_text = " | ".join(cells)
            lower = _normal(row_text)

            # Skip obvious navigation/header/footer rows.
            if len(cells) < 2 or lower in {"no record found", "no records found"}:
                continue

            available = _infer_available_seats(headers, cells)
            if available is not None and available < min_seats:
                # Keep full rows out of the alert state when there is no qualifying vacancy.
                continue

            batches.append(
                Batch(
                    watch_name=watch.name,
                    course=course_text,
                    values=tuple(cells),
                    available_seats=available,
                )
            )

    return batches


def _to_int(value: str) -> int | None:
    m = re.search(r"\d+", value.replace(",", ""))
    return int(m.group()) if m else None


def _infer_available_seats(headers: list[str], cells: list[str]) -> int | None:
    normalized_headers = [_normal(x) for x in headers]

    # First look for explicit "available/vacancy/seats left" columns.
    for i, h in enumerate(normalized_headers):
        if i >= len(cells):
            continue
        if any(k in h for k in ("available", "vacancy", "seats left", "remaining")):
            return _to_int(cells[i])

    batch_size = None
    seats_filled = None

    for i, h in enumerate(normalized_headers):
        if i >= len(cells):
            continue
        n = _to_int(cells[i])
        if n is None:
            continue
        if "batch size" in h or h == "size":
            batch_size = n
        if "seat" in h and "fill" in h:
            seats_filled = n

    if batch_size is not None and seats_filled is not None:
        return max(batch_size - seats_filled, 0)

    return None


class ICAIClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def check(self) -> list[Batch]:
        all_batches: list[Batch] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.config.portal.headless)
            try:
                for watch in self.config.watches:
                    all_batches.extend(self._check_watch(browser, watch))
            finally:
                browser.close()

        return all_batches

    def _check_watch(self, browser: Browser, watch: Watch) -> list[Batch]:
        page = browser.new_page()
        page.set_default_timeout(self.config.portal.timeout_ms)

        try:
            page.goto(self.config.portal.url, wait_until="domcontentloaded")

            selects = _all_selects(page)
            region_selector = _find_select_by_nearby_label(page, "Region")
            if not region_selector:
                region_selector = _choose_select(selects, ["region", "southern", "northern"])

            _select_by_text(page, region_selector, watch.region)
            _wait_for_postback(page, "")

            # Re-discover after the region postback.
            selects = _all_selects(page)
            pou_selector = _find_select_by_nearby_label(page, "Pou")
            if not pou_selector:
                pou_selector = _choose_select(selects, [watch.pou, "pou"])

            _select_by_text(page, pou_selector, watch.pou)
            _wait_for_postback(page, "")

            course_selector, course_text = _course_selector(page, watch.course_contains)
            page.locator(course_selector).select_option(label=course_text)
            _wait_for_postback(page, "")

            # Prefer a visible control whose accessible text/value contains
            # "Get List". This works with both <button> and ASP.NET <input>.
            clicked = False

            candidates = page.locator("button, input[type=submit], input[type=button]")
            for i in range(candidates.count()):
                control = candidates.nth(i)
                try:
                    label = " ".join(
                        x for x in [
                            control.inner_text(timeout=500),
                            control.get_attribute("value"),
                            control.get_attribute("aria-label"),
                            control.get_attribute("title"),
                            control.get_attribute("id"),
                        ] if x
                    )
                    if "get list" in _normal(label):
                        control.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                raise RuntimeError("Could not locate the ICAI 'Get List' control.")

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            return _extract_table(
                page,
                watch,
                course_text,
                self.config.monitor.minimum_available_seats,
            )

        except Exception:
            debug_dir = Path("debug")
            debug_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", watch.name)
            try:
                page.screenshot(path=str(debug_dir / f"{safe}.png"), full_page=True)
                (debug_dir / f"{safe}.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            raise
        finally:
            page.close()
