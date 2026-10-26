"""ntfy push for lakes that newly became likely black ice."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from wildice.models import Label, Lake, Score, SourceUnavailable
from wildice.publish import display_name

NTFY_URL = "https://ntfy.sh"
SOURCE = "ntfy"
TIMEOUT_S = 30


def newly_black_ice(scores: dict[str, Score], prev_labels: dict[str, str],
                    lakes: dict[str, Lake], pinned: frozenset[str],
                    hidden: frozenset[str]) -> list[str]:
    """Ids now likely black ice whose previous label was anything else or absent."""
    ids = [i for i, s in scores.items()
           if s.label == Label.LIKELY_BLACK_ICE
           and prev_labels.get(i) != Label.LIKELY_BLACK_ICE.value
           and i not in hidden and i in lakes]
    ids.sort(key=lambda i: (i not in pinned, -lakes[i].area_acres, i))
    return ids


def _map_url(base_url: str, lake_id: str) -> str:
    return f"{base_url.rstrip('/')}/#lake={lake_id}"


def format_alert(ids: list[str], lakes: dict[str, Lake], scores: dict[str, Score],
                 pinned: frozenset[str], base_url: str) -> tuple[str, str, str]:
    """Return (title, markdown body, click URL). Title stays ASCII (HTTP header)."""
    n = len(ids)
    title = "1 lake looks skateable" if n == 1 else f"{n} lakes look skateable"
    lines = []
    for i in ids:
        star = "★ " if i in pinned else ""
        lines.append(f"- {star}**{display_name(lakes[i])}** — {scores[i].reason} "
                     f"([map]({_map_url(base_url, i)}))")
    return title, "\n".join(lines), _map_url(base_url, ids[0])


def send_ntfy(topic: str, title: str, body: str, click: str | None,
              session: requests.Session) -> None:
    headers = {"Title": title, "Markdown": "yes"}
    if click:
        headers["Click"] = click
    try:
        resp = session.post(f"{NTFY_URL}/{topic}", data=body.encode("utf-8"),
                            headers=headers, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SourceUnavailable(SOURCE, str(exc)) from exc


def load_labels(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_labels(path: Path, scores: dict[str, Score]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = {i: s.label.value for i, s in sorted(scores.items())}
    path.write_text(json.dumps(labels, indent=1), encoding="utf-8", newline="\n")
