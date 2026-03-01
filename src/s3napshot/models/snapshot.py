from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SnapshotEntry:
    key: str
    size: int
    last_modified: datetime
