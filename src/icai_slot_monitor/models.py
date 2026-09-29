from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class Batch:
    watch_name: str
    course: str
    values: tuple[str, ...]
    available_seats: int | None = None

    def key(self) -> str:
        # Avoid using the inferred availability value in the identity.
        # Seat counts may change while the underlying batch remains the same.
        # Keep non-numeric/date/text fields plus the first few fields as a
        # conservative fallback for older portal table layouts.
        stable = []
        for value in self.values:
            v = value.strip()
            if re.fullmatch(r"\d+", v.replace(",", "")):
                continue
            stable.append(v)
        if not stable:
            stable = list(self.values[:2])
        return "|".join((self.watch_name, self.course, *stable))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
