"""Per-lake Sentinel-2 / Sentinel-1 summary statistics from Copernicus Data Space.

Assumed Statistical API response shape (no live credentials were available when
this was written, so fixtures are hand-built to the documented format):

    {"data": [{"interval": {"from": "<iso>Z", "to": "<iso>Z"},
               "outputs": {"<outputId>": {"bands": {"B0": {"stats": {
                   "min", "max", "mean", "stDev", "sampleCount", "noDataCount"}}}}}}],
     "status": "OK"}

Band keys inside an output are B0, B1, ... in the order the evalscript returns
them. Output ids and band order are defined by the scripts in wildice/evalscripts:
  s2_stats.js : "valid" B0; "reflectance" B0=B03, B1=B04, B2=B11 (each x valid flag)
  s1_stats.js : "vv" B0 (linear power)
Days with no data come back as no interval (or a NaN mean); both are handled.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import requests

from wildice.config import Config
from wildice.models import ImageryStats, Lake, S1Obs, S2Obs, SourceUnavailable

TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
             "protocol/openid-connect/token")
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
SOURCE = "copernicus"
CRS_4326 = "http://www.opengis.net/def/crs/EPSG/0/4326"
TIMEOUT_S = 120
MAX_RETRIES = 3  # matches weather.make_session Retry(total=3)
TOKEN_MARGIN_S = 60
RESOLUTION_DEG = 0.0002  # ~22 m N-S; statistics resolution in CRS units
THUMB_PX = 256
BASELINE_DAYS = 30
# VV-only coverage over Southcentral Alaska is unverified: "DV" (dual VV+VH) scenes
# may not be the only mode acquired there. Confirm at the first live run.
S1_POLARIZATION = "DV"
EVALSCRIPTS = Path(__file__).parent / "evalscripts"


def _status(exc: Exception) -> int | None:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) if resp is not None else None


def _script(name: str) -> str:
    return (EVALSCRIPTS / name).read_text(encoding="utf-8")


def _attempts(resp) -> int:
    """HTTP requests behind one response: 1 + urllib3 retries performed."""
    retries = getattr(getattr(resp, "raw", None), "retries", None)
    history = getattr(retries, "history", None)
    return 1 + len(history) if history else 1


class Budget:
    """Monthly request counter persisted as JSON; resets when the month changes."""

    def __init__(self, path: Path, monthly_limit: int,
                 today: Callable[[], date] = date.today) -> None:
        self.path = Path(path)
        self.limit = monthly_limit
        self._today = today
        self.month = self._month_key()
        self.used = 0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("month") == self.month:
                self.used = int(raw.get("used", 0))
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    def _month_key(self) -> str:
        return self._today().strftime("%Y-%m")

    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def record(self, n: int = 1) -> None:
        self.used += n

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"month": self.month, "used": self.used}),
                             encoding="utf-8", newline="\n")


def _mean(output: dict, band: str = "B0") -> float | None:
    """Mean of one output band, or None when absent / NaN / non-numeric."""
    try:
        value = float(output["bands"][band]["stats"]["mean"])
    except (KeyError, TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


class CopernicusClient:
    def __init__(self, client_id: str, client_secret: str, session: requests.Session,
                 budget: Budget | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session
        self.budget = budget
        self._clock = clock
        self._token: str | None = None
        self._token_expiry = 0.0

    def _auth_header(self) -> dict:
        if self._token is None or self._clock() >= self._token_expiry:
            try:
                resp = self.session.post(TOKEN_URL, data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }, timeout=TIMEOUT_S)
                resp.raise_for_status()
                body = resp.json()
                token = body["access_token"]
                ttl = float(body.get("expires_in", 300))
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                raise SourceUnavailable(SOURCE, f"token: {exc}", status=_status(exc)) from exc
            self._token = token
            self._token_expiry = self._clock() + max(0.0, ttl - TOKEN_MARGIN_S)
        return {"Authorization": f"Bearer {self._token}"}

    def _post(self, url: str, body: dict) -> requests.Response:
        headers = self._auth_header()
        try:
            resp = self.session.post(url, json=body, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as exc:
            # RetryError means urllib3 exhausted its retries: 1 + MAX_RETRIES requests
            self._record(MAX_RETRIES + 1 if isinstance(exc, requests.exceptions.RetryError)
                         else 1)
            raise SourceUnavailable(SOURCE, str(exc)) from exc
        self._record(_attempts(resp))
        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceUnavailable(SOURCE, str(exc), status=resp.status_code) from exc
        return resp

    def _record(self, n: int) -> None:
        if self.budget is not None:
            self.budget.record(max(1, n))

    @staticmethod
    def _bounds(geometry: dict) -> dict:
        return {"geometry": geometry, "properties": {"crs": CRS_4326}}

    def _statistics(self, collection: str, data_filter: dict, evalscript: str,
                    geometry: dict, start: date, end: date) -> list[dict]:
        body = {
            "input": {
                "bounds": self._bounds(geometry),
                "data": [{"type": collection, "dataFilter": data_filter}],
            },
            "aggregation": {
                "timeRange": {"from": f"{start.isoformat()}T00:00:00Z",
                              "to": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z"},
                "aggregationInterval": {"of": "P1D"},
                "evalscript": evalscript,
                "resolution": {"x": RESOLUTION_DEG, "y": RESOLUTION_DEG},
            },
        }
        resp = self._post(STATS_URL, body)
        try:
            data = resp.json()["data"]
            if not isinstance(data, list):
                raise TypeError("data is not a list")
            return data
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceUnavailable(SOURCE, f"unexpected statistics response: {exc}") from exc

    @staticmethod
    def _day(interval: dict) -> date:
        return date.fromisoformat(interval["interval"]["from"][:10])

    def s2_stats(self, geometry: dict, start: date, end: date) -> list[S2Obs]:
        rows = self._statistics("sentinel-2-l2a", {"mosaickingOrder": "mostRecent"},
                                _script("s2_stats.js"), geometry, start, end)
        out: list[S2Obs] = []
        try:
            for row in rows:
                outputs = row["outputs"]
                valid = _mean(outputs["valid"])
                if valid is None:  # no data at all that day
                    continue
                if valid <= 0.0:  # data present but no valid pixels
                    out.append(S2Obs(self._day(row), 0.0, 0.0, 0.0, 0.0))
                    continue
                refl = outputs["reflectance"]
                means = [_mean(refl, b) for b in ("B0", "B1", "B2")]
                if any(m is None for m in means):  # NaN band on a valid day
                    continue
                bands = [round(m / valid, 6) for m in means]
                out.append(S2Obs(self._day(row), round(valid, 6), *bands))
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(SOURCE, f"unexpected S2 response: {exc}") from exc
        return out

    def s1_stats(self, geometry: dict, start: date, end: date) -> list[S1Obs]:
        rows = self._statistics(
            "sentinel-1-grd",
            {"acquisitionMode": "IW", "polarization": S1_POLARIZATION, "resolution": "HIGH"},
            _script("s1_stats.js"), geometry, start, end)
        out: list[S1Obs] = []
        try:
            for row in rows:
                linear = _mean(row["outputs"]["vv"])
                if linear is None or linear <= 0.0:
                    continue
                out.append(S1Obs(self._day(row), 10.0 * math.log10(linear)))
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(SOURCE, f"unexpected S1 response: {exc}") from exc
        return out

    def truecolor_png(self, geometry: dict, day: date) -> bytes:
        body = {
            "input": {
                "bounds": self._bounds(geometry),
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{day.isoformat()}T00:00:00Z",
                            "to": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z"},
                        "mosaickingOrder": "leastCC",
                    },
                }],
            },
            "output": {"width": THUMB_PX, "height": THUMB_PX,
                       "responses": [{"identifier": "default",
                                      "format": {"type": "image/png"}}]},
            "evalscript": _script("truecolor.js"),
        }
        return self._post(PROCESS_URL, body).content


def fetch_imagery(client: CopernicusClient, lake: Lake, run_date: date, cfg: Config,
                  baseline_db: float | None) -> ImageryStats:
    if lake.interior is None:
        raise ValueError(f"lake {lake.id} has no interior geometry")
    start = run_date - timedelta(days=cfg.imagery.lookback_days)
    return ImageryStats(
        s2=tuple(client.s2_stats(lake.interior, start, run_date)),
        s1=tuple(client.s1_stats(lake.interior, start, run_date)),
        s1_baseline_db=baseline_db,
    )


def s1_baseline(client: CopernicusClient, lake: Lake, freeze_up: date) -> float | None:
    """Median VV dB over the 30 days before freeze_up (freeze_up day excluded)."""
    if lake.interior is None:
        raise ValueError(f"lake {lake.id} has no interior geometry")
    obs = client.s1_stats(lake.interior, freeze_up - timedelta(days=BASELINE_DAYS),
                          freeze_up - timedelta(days=1))
    if not obs:
        return None
    return statistics.median(o.vv_db for o in obs)
