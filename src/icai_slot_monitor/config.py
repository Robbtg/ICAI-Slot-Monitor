from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PortalConfig:
    url: str
    timeout_ms: int = 30000
    headless: bool = True
    retries: int = 2


@dataclass(frozen=True)
class MonitorConfig:
    minimum_available_seats: int = 1
    alert_on_new_batch: bool = True
    alert_on_seat_increase: bool = True
    alert_on_return_to_available: bool = True


@dataclass(frozen=True)
class Watch:
    name: str
    region: str
    pou: str
    course_contains: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    portal: PortalConfig
    monitor: MonitorConfig
    watches: tuple[Watch, ...]


def load_config(path: str | Path) -> AppConfig:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    p = raw.get("portal", {})
    m = raw.get("monitor", {})

    watches = []
    for item in raw.get("watches", []):
        watches.append(
            Watch(
                name=str(item["name"]),
                region=str(item["region"]),
                pou=str(item["pou"]),
                course_contains=tuple(str(x) for x in item.get("course_contains", [])),
            )
        )

    if not watches:
        raise ValueError("config.yaml contains no watches")

    return AppConfig(
        portal=PortalConfig(
            url=str(p.get("url", "https://www.icaionlineregistration.org/launchbatchdetail.aspx")),
            timeout_ms=int(p.get("timeout_ms", 30000)),
            headless=bool(p.get("headless", True)),
            retries=int(p.get("retries", 2)),
        ),
        monitor=MonitorConfig(
            minimum_available_seats=int(m.get("minimum_available_seats", 1)),
            alert_on_new_batch=bool(m.get("alert_on_new_batch", True)),
            alert_on_seat_increase=bool(m.get("alert_on_seat_increase", True)),
            alert_on_return_to_available=bool(m.get("alert_on_return_to_available", True)),
        ),
        watches=tuple(watches),
    )
