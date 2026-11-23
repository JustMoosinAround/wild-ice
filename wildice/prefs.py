"""Owner pin/hide preferences."""
from __future__ import annotations

import json
from collections.abc import Iterable
import logging
from pathlib import Path

from wildice.config import Config

log = logging.getLogger(__name__)


def load_prefs(cfg: Config, prefs_dir: Path, extra: Iterable[dict] = (),
               owner_saved: Iterable[str] = ()) -> tuple[frozenset[str], frozenset[str]]:
    """Return (watched, hidden). Watched = config.pinned plus the owner's saved lakes
    ("My lakes"): checked daily and first in alerts. Pins are retired (owner, Nov 2026:
    pinned lakes became the owner's saved lakes), so old pin/unpin prefs are ignored.
    Hidden: config base, then prefs/*.json in filename order, then `extra` (the
    worker's prefs, oldest first)."""
    pinned = set(cfg.pinned) | {str(i) for i in owner_saved}
    hidden = set(cfg.hidden)
    prefs_dir = Path(prefs_dir)
    files = sorted(prefs_dir.glob("*.json"), key=lambda p: p.name) if prefs_dir.is_dir() else []
    items = []
    for f in files:
        try:
            items.append((f.name, json.loads(f.read_text(encoding="utf-8"))))
        except ValueError as e:
            log.warning("skipping malformed pref file %s: %r", f.name, e)
    items += [("ice log", item) for item in extra]
    for name, item in items:
        try:
            lake_id, action = str(item["lake_id"]), item["action"]
        except (KeyError, TypeError) as e:
            log.warning("skipping malformed pref %s: %r", name, e)
            continue
        if action in ("pin", "unpin"):
            continue
        elif action == "hide":
            hidden.add(lake_id)
        elif action == "unhide":
            hidden.discard(lake_id)
        else:
            log.warning("skipping pref %s: unknown action %r", name, action)
    return frozenset(pinned), frozenset(hidden)
