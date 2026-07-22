"""Verify the configured AISStream credential without printing it or persisting payloads."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import websockets
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
URL = "wss://stream.aisstream.io/v0/stream"


async def verify(timeout_s: float = 20.0) -> dict[str, object]:
    """Subscribe to Hormuz and return only non-sensitive connection evidence."""
    load_dotenv(ROOT / ".env")
    key = os.getenv("AISSTREAM_API_KEY", "")
    if not key:
        raise RuntimeError("AISSTREAM_API_KEY is not configured")
    subscribe = {
        "APIKey": key,
        "BoundingBoxes": [[[25.5, 55.0], [27.2, 57.5]]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }
    async with websockets.connect(URL, ping_interval=20) as websocket:
        await websocket.send(json.dumps(subscribe))
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=timeout_s))
    metadata = message.get("MetaData", {})
    return {
        "connected": True,
        "message_type": message.get("MessageType"),
        "mmsi_present": bool(metadata.get("MMSI")),
        "credential_echoed": False,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify()), sort_keys=True))
