"""Claude tool-use schemas.

JSON-schema definitions (name, description, input_schema) that tell Claude which
tools exist and what arguments they take. These are what we pass to the Anthropic
API so the model can request a tool call.

Key concept: a tool schema is a contract the model reads; the matching Python
function in ``fetch_tools`` is what actually executes. Descriptions are written
*for the model* — they double as the prompt that decides when each tool fires.
"""

from __future__ import annotations

from typing import Any

# Each entry follows Anthropic's tool schema: name, description, input_schema.
# `additionalProperties: false` keeps the model from inventing arguments.
FETCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_neo_feed",
        "description": (
            "List near-Earth objects with close approaches in a date range. "
            "Use this first to find which asteroids are approaching. Dates are "
            "YYYY-MM-DD and the range must be 7 days or fewer (NASA limit)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date, YYYY-MM-DD."},
                "end_date": {"type": "string", "description": "End date, YYYY-MM-DD."},
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_neo_detail",
        "description": (
            "Fetch the full record (orbital elements included) for one NEO by its "
            "reference id. Use after get_neo_feed when a specific object needs detail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "neo_id": {"type": "string", "description": "The NEO reference id."},
            },
            "required": ["neo_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_space_weather",
        "description": (
            "Summarise space weather (solar flares, CMEs, geomagnetic storms) over "
            "a date range. Use when observing conditions or hazards are relevant. "
            "Dates are YYYY-MM-DD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date, YYYY-MM-DD."},
                "end_date": {"type": "string", "description": "End date, YYYY-MM-DD."},
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_ephemeris",
        "description": (
            "Get a JPL Horizons observer ephemeris (sky position, range) for a "
            "target body on a date. Use for precise observing geometry of a named "
            "object. Date is YYYY-MM-DD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target body name or designation."},
                "date": {"type": "string", "description": "Observation date, YYYY-MM-DD."},
            },
            "required": ["target", "date"],
            "additionalProperties": False,
        },
    },
]
