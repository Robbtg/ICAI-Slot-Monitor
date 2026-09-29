from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import Batch


def load_state(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def snapshot(batches: list[Batch]) -> dict[str, Any]:
    records = []
    for b in sorted(batches, key=lambda x: x.key()):
        records.append({
            "key": b.key(),
            "course": b.course,
            "values": list(b.values),
            "available_seats": b.available_seats,
        })
    return {"batches": records}


def signature(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
