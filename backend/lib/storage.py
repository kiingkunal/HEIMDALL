"""SQLite state + parquet time-series helpers. SQLite for state (harvest log, LLM cache,
playbooks, latest-value snapshots), parquet for AIS/price time series. No cloud DB by design —
SQLite + parquet survive dead venue wifi, and that is the feature.

Every stored record carries source + fetched_at so the Phase 0 gate ('every record carries
source and timestamp') is structurally enforced, not aspirational.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "state.db"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """Idempotent schema. Called on app startup."""
    own = conn is None
    conn = conn or get_db()
    try:
        conn.executescript(
            """
            -- Append-only harvest log: proves every fetch, with source + timestamp.
            CREATE TABLE IF NOT EXISTS harvest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                harvester   TEXT NOT NULL,
                source      TEXT NOT NULL,
                kind        TEXT NOT NULL,          -- live | cache | ...
                status      TEXT NOT NULL,          -- ok | error | empty
                fetched_at  TEXT NOT NULL,          -- ISO8601 UTC
                record_count INTEGER DEFAULT 0,
                detail      TEXT
            );

            -- Latest tagged values keyed by (namespace, key). Upserted each harvest.
            CREATE TABLE IF NOT EXISTS latest (
                namespace   TEXT NOT NULL,
                key         TEXT NOT NULL,
                payload     TEXT NOT NULL,          -- JSON Tagged/dict
                source      TEXT NOT NULL,
                kind        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL,
                PRIMARY KEY (namespace, key)
            );

            -- LLM narrative cache keyed by input hash. Protects Groq free-tier limits.
            CREATE TABLE IF NOT EXISTS llm_cache (
                input_hash  TEXT PRIMARY KEY,
                provider    TEXT NOT NULL,
                model       TEXT NOT NULL,
                prompt_name TEXT,
                output      TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            -- Playbooks (Phase 3 populates; table exists from Phase 0).
            CREATE TABLE IF NOT EXISTS playbooks (
                id          TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                valid_until TEXT,
                status      TEXT NOT NULL,          -- fresh | stale | recomputing
                payload     TEXT NOT NULL,
                stale_reason TEXT
            );
            """
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def log_harvest(harvester: str, source: str, kind: str, status: str,
                record_count: int = 0, detail: str | None = None,
                conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or get_db()
    try:
        conn.execute(
            "INSERT INTO harvest_log (harvester, source, kind, status, fetched_at, record_count, detail)"
            " VALUES (?,?,?,?,?,?,?)",
            (harvester, source, kind, status, _now_iso(), record_count, detail),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def put_latest(namespace: str, key: str, payload: dict[str, Any],
               source: str, kind: str, fetched_at: str | None = None,
               conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or get_db()
    try:
        conn.execute(
            "INSERT INTO latest (namespace, key, payload, source, kind, fetched_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(namespace, key) DO UPDATE SET"
            " payload=excluded.payload, source=excluded.source,"
            " kind=excluded.kind, fetched_at=excluded.fetched_at",
            (namespace, key, json.dumps(payload), source, kind, fetched_at or _now_iso()),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def get_latest(namespace: str, key: str,
               conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    own = conn is None
    conn = conn or get_db()
    try:
        row = conn.execute(
            "SELECT payload, source, kind, fetched_at FROM latest WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
        if not row:
            return None
        return {
            "payload": json.loads(row["payload"]),
            "source": row["source"],
            "kind": row["kind"],
            "fetched_at": row["fetched_at"],
        }
    finally:
        if own:
            conn.close()


def get_namespace(namespace: str,
                  conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or get_db()
    try:
        rows = conn.execute(
            "SELECT key, payload, source, kind, fetched_at FROM latest WHERE namespace=?",
            (namespace,),
        ).fetchall()
        return [
            {"key": r["key"], "payload": json.loads(r["payload"]),
             "source": r["source"], "kind": r["kind"], "fetched_at": r["fetched_at"]}
            for r in rows
        ]
    finally:
        if own:
            conn.close()


def cache_llm(input_hash: str, provider: str, model: str, prompt_name: str | None,
              output: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (input_hash, provider, model, prompt_name, output, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (input_hash, provider, model, prompt_name, output, _now_iso()),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def get_llm_cache(input_hash: str, conn: sqlite3.Connection | None = None) -> str | None:
    own = conn is None
    conn = conn or get_db()
    try:
        row = conn.execute(
            "SELECT output FROM llm_cache WHERE input_hash=?", (input_hash,)
        ).fetchone()
        return row["output"] if row else None
    finally:
        if own:
            conn.close()


def write_parquet_snapshot(df, name: str) -> Path:
    """Write a timestamped parquet snapshot under data/snapshots/. df is a pandas DataFrame."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SNAPSHOT_DIR / f"{name}_{ts}.parquet"
    df.to_parquet(path, index=False)
    return path


def latest_snapshot(name_prefix: str) -> Path | None:
    """Return the newest exact-prefix snapshot.

    Snapshot names are ``<prefix>_<UTC timestamp>.parquet``. Requiring the timestamp to begin
    with a digit prevents ``latest_snapshot("ais")`` from accidentally selecting ``ais_sim_*``.
    """
    if not SNAPSHOT_DIR.exists():
        return None
    matches = sorted(SNAPSHOT_DIR.glob(f"{name_prefix}_[0-9]*.parquet"))
    return matches[-1] if matches else None


def list_snapshots(name_prefix: str) -> list[Path]:
    """List exact-prefix snapshots oldest to newest without mixing live and SIM namespaces."""
    if not SNAPSHOT_DIR.exists():
        return []
    return sorted(SNAPSHOT_DIR.glob(f"{name_prefix}_[0-9]*.parquet"))
