"""Replay past days for lakes the owner remembers and check the app's labels."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from wildice.catalog import load_catalog
from wildice.config import load_config
from wildice.icemodel import run_ice_model
from wildice.imagery import CopernicusClient, fetch_imagery, s1_baseline
from wildice.models import Confidence, Label, SourceUnavailable
from wildice.score import score_lake, valid_s2_classes
from wildice.weather import cell_of, cell_points, fetch_daily, make_session, season_start

log = logging.getLogger(__name__)

EXPECTED = {
    "skated": {Label.LIKELY_BLACK_ICE},
    "snow": {Label.SNOW_COVERED},
    "water": {Label.OPEN_WATER, Label.FREEZING},
    "rough": {Label.FREEZING, Label.UNKNOWN, Label.SNOW_COVERED},
}


@dataclass
class Row:
    lake_id: str
    day: date
    observed: str
    predicted: Label
    confidence: Confidence
    reason: str
    match: bool
    error: str | None = None


def _error_row(lake_id, day, observed, msg: str) -> Row:
    return Row(lake_id, day, observed, Label.UNKNOWN, Confidence.LOW, "", False, error=msg)


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def run_backtest(obs_path: Path, root: Path, session, client) -> list[Row]:
    root = Path(root)
    cfg = load_config(root / "config.yaml")
    lake_list = load_catalog(root / "site" / "data" / "lakes.geojson")
    lakes = {lake.id: lake for lake in lake_list}
    points = cell_points(lake_list)  # same request point per cell as the daily job
    doc = yaml.safe_load(Path(obs_path).read_text(encoding="utf-8")) or {}
    rows: list[Row] = []
    for item in doc.get("observations") or []:
        lake_id, observed = str(item.get("lake_id")), str(item.get("observed"))
        try:
            day = _as_date(item.get("day"))
        except ValueError:
            rows.append(_error_row(lake_id, item.get("day"), observed,
                                   f"bad day {item.get('day')!r}"))
            continue
        lake = lakes.get(lake_id)
        if lake is None:
            rows.append(_error_row(lake_id, day, observed, "unknown lake_id"))
            continue
        if observed not in EXPECTED:
            rows.append(_error_row(lake_id, day, observed, f"unknown observed {observed!r}"))
            continue
        try:
            cell = cell_of(lake.lat, lake.lon)
            wx = fetch_daily([cell], season_start(day, cfg), day, session, archive=True,
                             points=points)[cell]
            wx = [d for d in wx if d.day <= day]
            ice = run_ice_model(wx, cfg)
            img = None
            if client is not None and lake.interior is not None:
                base = (s1_baseline(client, lake, ice.freeze_up)
                        if ice.freeze_up is not None else None)
                img = fetch_imagery(client, lake, day, cfg, base)
                ice = run_ice_model(wx, cfg, valid_s2_classes(img, cfg))
            sc = score_lake(lake, ice, img, day, cfg)
        except SourceUnavailable as exc:
            rows.append(_error_row(lake_id, day, observed, str(exc)))
            continue
        rows.append(Row(lake_id, day, observed, sc.label, sc.confidence, sc.reason,
                        sc.label in EXPECTED[observed]))
    return rows


def summarize(rows: list[Row]) -> str:
    ok = [r for r in rows if r.error is None]
    lines = [f"{'lake':<10} {'day':<10} {'observed':<8} {'predicted':<17} {'conf':<6} ok  reason"]
    for r in rows:
        if r.error is not None:
            lines.append(f"{r.lake_id:<10} {r.day!s:<10} {r.observed:<8} ERROR: {r.error}")
        else:
            lines.append(f"{r.lake_id:<10} {r.day!s:<10} {r.observed:<8} {r.predicted.value:<17} "
                         f"{r.confidence.value:<6} {'yes' if r.match else 'NO ':<3} {r.reason}")
    false_alerts = sum(r.predicted is Label.LIKELY_BLACK_ICE and r.observed != "skated"
                       for r in ok)
    misses = sum(r.observed == "skated" and r.predicted is not Label.LIKELY_BLACK_ICE
                 for r in ok)
    lines.append("")
    lines.append(f"matched {sum(r.match for r in ok)}/{len(ok)}")
    lines.append(f"false alerts: {false_alerts}")
    lines.append(f"misses: {misses}")
    if len(ok) != len(rows):
        lines.append(f"errors: {len(rows) - len(ok)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    obs = Path(args[0]) if args else Path("backtest.yaml")
    session = make_session()
    cid, secret = os.environ.get("CDSE_CLIENT_ID"), os.environ.get("CDSE_CLIENT_SECRET")
    client = CopernicusClient(cid, secret, session) if cid and secret else None
    print("imagery: " + ("Copernicus" if client else "none (CDSE env not set; weather only)"))
    print(summarize(run_backtest(obs, Path.cwd(), session, client)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
