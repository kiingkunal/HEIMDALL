"""datadocked.com API key pool with credit accounting. Keys and per-key budgets are loaded from
environment configuration. Endpoint costs: get-vessels-by-area=10, get-vessel-location=1,
get-vessel-historical=5.
Credits are scarce, so this pool:

  - tracks spend per key in SQLite (survives restarts — we never lose the count),
  - rotates to the next key when one is exhausted or rate-limited,
  - refuses a call when the whole pool can't afford it (frugal guard), so we never silently
    blow the budget during testing or a demo.

Design intent: datadocked is a *snapshot* source, not a continuous recorder. Bounded corridor and
port-area sweeps provide real demo density; optional SIM augmentation remains separately labelled.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import storage

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_CREDITS_PER_KEY = int(os.getenv("DATADOCKED_CREDITS_PER_KEY", "20"))


def _keys() -> list[str]:
    raw = os.getenv("DATADOCKED_API_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ais_key_credits (
            key_id      TEXT PRIMARY KEY,   -- masked key (last 6 chars) — never store full key in DB
            spent       INTEGER NOT NULL DEFAULT 0,
            budget      INTEGER NOT NULL,
            disabled    INTEGER NOT NULL DEFAULT 0,   -- 1 if 401/403/exhausted
            last_used   TEXT
        );
        """
    )
    conn.commit()


def _mask(key: str) -> str:
    return f"...{key[-6:]}" if len(key) >= 6 else key


def _init_rows(conn: sqlite3.Connection) -> None:
    _ensure_table(conn)
    for k in _keys():
        conn.execute(
            "INSERT OR IGNORE INTO ais_key_credits (key_id, spent, budget) VALUES (?,0,?)",
            (_mask(k), DEFAULT_CREDITS_PER_KEY),
        )
    conn.commit()


def remaining_by_key(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    own = conn is None
    conn = conn or storage.get_db()
    try:
        _init_rows(conn)
        rows = conn.execute(
            "SELECT key_id, spent, budget, disabled FROM ais_key_credits"
        ).fetchall()
        return {r["key_id"]: (0 if r["disabled"] else max(0, r["budget"] - r["spent"]))
                for r in rows}
    finally:
        if own:
            conn.close()


def total_remaining() -> int:
    return sum(remaining_by_key().values())


def pick_key(cost: int) -> tuple[str, str] | None:
    """Return (full_key, masked_id) for a key that can afford `cost`, or None if the pool can't.
    Chooses the key with the most remaining credits (spread the load, keep keys alive)."""
    conn = storage.get_db()
    try:
        _init_rows(conn)
        rows = conn.execute(
            "SELECT key_id, spent, budget, disabled FROM ais_key_credits ORDER BY (budget-spent) DESC"
        ).fetchall()
        affordable = [r for r in rows if not r["disabled"] and (r["budget"] - r["spent"]) >= cost]
        if not affordable:
            return None
        target_id = affordable[0]["key_id"]
        # map masked id back to a full key
        for k in _keys():
            if _mask(k) == target_id:
                return k, target_id
        return None
    finally:
        conn.close()


def charge(masked_id: str, cost: int) -> None:
    conn = storage.get_db()
    try:
        _ensure_table(conn)
        conn.execute(
            "UPDATE ais_key_credits SET spent = spent + ?, last_used = datetime('now') WHERE key_id = ?",
            (cost, masked_id),
        )
        conn.commit()
    finally:
        conn.close()


def disable(masked_id: str, reason: str = "") -> None:
    conn = storage.get_db()
    try:
        _ensure_table(conn)
        conn.execute("UPDATE ais_key_credits SET disabled = 1 WHERE key_id = ?", (masked_id,))
        conn.commit()
    finally:
        conn.close()
    storage.log_harvest("ais", "datadocked keypool", "live", "error",
                        detail=f"key {masked_id} disabled: {reason}"[:200])


def status() -> dict[str, Any]:
    return {
        "keys": len(_keys()),
        "remaining_by_key": remaining_by_key(),
        "total_remaining": total_remaining(),
        "budget_per_key": DEFAULT_CREDITS_PER_KEY,
    }
