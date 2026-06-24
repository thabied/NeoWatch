"""JPL Horizons client.

Ephemeris (position/velocity) data for a solar-system body. No API key. Horizons
returns a free-form text block, which we keep raw inside ``EphemerisData``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from .http import retry_external
from .models import EphemerisData

_BASE = "https://ssd.jpl.nasa.gov/api/horizons.api"


def parse_ephemeris(target: str, date: str, data: dict[str, Any]) -> EphemerisData:
    """Wrap Horizons' ``result`` text block in a typed model."""
    return EphemerisData(target=target, date=date, raw_result=str(data.get("result", "")))


@retry_external
async def get_ephemeris(
    client: httpx.AsyncClient,
    target: str,
    date: str,
) -> EphemerisData:
    """Fetch a one-day observer ephemeris for ``target`` on ``date`` (YYYY-MM-DD).

    Horizons requires a stop time strictly after the start, so we span one day.
    """
    stop = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    resp = await client.get(
        _BASE,
        params={
            "format": "json",
            "COMMAND": f"'{target}'",
            "OBJ_DATA": "NO",
            "MAKE_EPHEM": "YES",
            "EPHEM_TYPE": "OBSERVER",
            "CENTER": "'500@399'",  # geocentric (Earth)
            "START_TIME": f"'{date}'",
            "STOP_TIME": f"'{stop}'",
            "STEP_SIZE": "'1 d'",
            "QUANTITIES": "'1,9,20'",  # RA/DEC, visual mag, range & range-rate
        },
    )
    resp.raise_for_status()
    return parse_ephemeris(target, date, resp.json())
