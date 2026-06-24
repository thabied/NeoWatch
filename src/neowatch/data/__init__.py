"""Data package.

Async clients for every external data source (NASA NeoWs, JPL Horizons, APOD,
JPL SBDB, arXiv, NASA DONKI). Every client parses responses into Pydantic models,
retries on failure, and shares one HTTP/rate-limit layer — so the rest of the app
sees clean typed objects, never raw JSON.
"""
