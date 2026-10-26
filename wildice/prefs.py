"""Owner pin/hide preferences."""
from __future__ import annotations

import json
from pathlib import Path

from wildice.config import Config


def load_prefs(cfg: Config, prefs_dir: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Return (pinned, hidden): config base plus prefs/*.json applied in filename order."""
    pinned = set(cfg.pinned)
    hidden = set(cfg.hidden)
    prefs_dir = Path(prefs_dir)
    if not prefs_dir.is_dir():
        return frozenset(pinned), frozenset(hidden)
    for f in sorted(prefs_dir.glob("*.json"), key=lambda p: p.name):
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
            lake_id, action = str(item["lake_id"]), item["action"]
        except (ValueError, KeyError, TypeError):
            continue  # malformed pref file: ignore
        if action == "pin":
            pinned.add(lake_id)
        elif action == "unpin":
            pinned.discard(lake_id)
        elif action == "hide":
            hidden.add(lake_id)
        elif action == "unhide":
            hidden.discard(lake_id)
    return frozenset(pinned), frozenset(hidden)
