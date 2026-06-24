"""JPL Small Body Database (SBDB) client.

Physical characteristics and orbit class for a named/numbered small body. No API
key. SBDB's JSON is deeply nested; ``parse_sbdb`` flattens it onto ``SBDBRecord``.
"""

from __future__ import annotations

from typing import Any

import httpx

from .http import retry_external
from .models import SBDBPhysPar, SBDBRecord

_BASE = "https://ssd-api.jpl.nasa.gov/sbdb.api"


def _to_bool(value: Any) -> bool | None:
    """SBDB flags arrive as booleans, ``"Y"/"N"`` strings, or null — normalize."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "1"}
    return None


def parse_sbdb(data: dict[str, Any]) -> SBDBRecord:
    """Flatten SBDB's nested ``object``/``phys_par`` JSON into ``SBDBRecord``."""
    obj: dict[str, Any] = data.get("object", {})
    orbit_class = obj.get("orbit_class")
    phys_par: list[dict[str, Any]] = data.get("phys_par", [])
    return SBDBRecord(
        fullname=str(obj.get("fullname", "")),
        neo=_to_bool(obj.get("neo")),
        pha=_to_bool(obj.get("pha")),
        designation=obj.get("des"),
        orbit_class=orbit_class.get("name") if isinstance(orbit_class, dict) else None,
        phys_par=[SBDBPhysPar.model_validate(p) for p in phys_par],
    )


@retry_external
async def get_sbdb(client: httpx.AsyncClient, sstr: str) -> SBDBRecord:
    """Look up a small body by search string (name or designation)."""
    # Request physical parameters; we don't pass a close-approach flag because
    # SBDB rejects unknown params (400) and SBDBRecord doesn't store approaches.
    resp = await client.get(_BASE, params={"sstr": sstr, "phys-par": "true"})
    resp.raise_for_status()
    return parse_sbdb(resp.json())
