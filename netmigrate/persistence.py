"""
SQLite persistence layer for NetMigrate's web layer.

Standard-library ``sqlite3`` only -- no SQLAlchemy, no web imports. This
module never touches the IR dataclasses; it only ever sees the plain dict
shape produced by ``ConversionResult.to_dict()`` (CLAUDE.md section 4, the
API contract). Keeping the storage boundary here means this module has no
reason to change when the engine's internals do, and no reason for the web
layer to reach past it into the engine.

Schema exactly as specified in docs/web-layer-spec.md section 2 (thesis
section 3.9). ``conversion_lines`` deliberately has no text column:
``engine.convert`` builds ``output_text`` as ``"\\n".join(ln.text for ln in
lines)``, so a line's text is always recoverable as position
``output_line_no - 1`` in ``output_text.split("\\n")``. Storing it twice
would be redundant and could drift out of sync.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

DbPath = Union[str, Path]

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT    NOT NULL,
    source_vendor      TEXT    NOT NULL,
    target_vendor      TEXT    NOT NULL,
    filename           TEXT,
    total_lines        INTEGER NOT NULL,
    significant_lines  INTEGER NOT NULL,
    rule_lines         INTEGER NOT NULL,
    ai_lines           INTEGER NOT NULL,
    unmapped_lines     INTEGER NOT NULL,
    duration_ms        REAL    NOT NULL,
    source_text        TEXT    NOT NULL,
    output_text        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS conversion_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversion_id   INTEGER NOT NULL REFERENCES conversions(id) ON DELETE CASCADE,
    source_line_no  INTEGER,
    output_line_no  INTEGER NOT NULL,
    provenance      TEXT    NOT NULL,
    rule_id         TEXT,
    needs_review    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname    TEXT    NOT NULL,
    ip_address  TEXT,
    vendor      TEXT,
    os_version  TEXT,
    ssh_port    INTEGER DEFAULT 22,
    location    TEXT,
    status      TEXT    DEFAULT 'unknown',
    notes       TEXT,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lines_conversion ON conversion_lines(conversion_id);
CREATE INDEX IF NOT EXISTS idx_conversions_created ON conversions(created_at DESC);
"""


def _utc_now_iso() -> str:
    """ISO 8601 UTC, matching the format used across the web-layer spec."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: DbPath) -> sqlite3.Connection:
    """Open a connection with the schema already in place.

    ``PRAGMA foreign_keys`` is OFF by default in sqlite3 and is a
    per-connection setting, not something stored in the file -- it must be
    set on every connection, or ``ON DELETE CASCADE`` on conversion_lines
    silently does nothing and orphans lines behind deleted conversions.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def get_connection(db_path: DbPath) -> Iterator[sqlite3.Connection]:
    """Convenience context manager: open, yield, close."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Conversions (spec 3.1, 3.6)
# --------------------------------------------------------------------------


def save_conversion(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    filename: Optional[str] = None,
) -> int:
    """Persist a ``ConversionResult.to_dict()`` payload and its lines.

    Returns the new conversion id. Runs as one transaction: a conversion row
    with no lines, or lines with no parent, would corrupt the audit history,
    so both inserts commit together or not at all.
    """
    metrics = payload["metrics"]
    with conn:
        cur = conn.execute(
            """
            INSERT INTO conversions (
                created_at, source_vendor, target_vendor, filename,
                total_lines, significant_lines, rule_lines, ai_lines,
                unmapped_lines, duration_ms, source_text, output_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                payload["source_vendor"],
                payload["target_vendor"],
                filename,
                metrics["total_lines"],
                metrics["significant_lines"],
                metrics["rule_lines"],
                metrics["ai_lines"],
                metrics["unmapped_lines"],
                metrics["duration_ms"],
                payload["source_text"],
                payload["output_text"],
            ),
        )
        conversion_id = cur.lastrowid

        conn.executemany(
            """
            INSERT INTO conversion_lines (
                conversion_id, source_line_no, output_line_no,
                provenance, rule_id, needs_review
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    conversion_id,
                    line["source_line"],
                    idx,
                    line["provenance"],
                    line["rule_id"],
                    int(bool(line["needs_review"])),
                )
                for idx, line in enumerate(payload["lines"], start=1)
            ],
        )
    return conversion_id


def _summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    significant = row["significant_lines"]
    rule = row["rule_lines"]
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source_vendor": row["source_vendor"],
        "target_vendor": row["target_vendor"],
        "filename": row["filename"],
        "metrics": {
            "total_lines": row["total_lines"],
            "significant_lines": significant,
            "rule_lines": rule,
            "ai_lines": row["ai_lines"],
            "unmapped_lines": row["unmapped_lines"],
            "rule_coverage": round(rule / significant, 4) if significant else 0.0,
            "duration_ms": row["duration_ms"],
        },
    }


def list_conversions(
    conn: sqlite3.Connection, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """Summary fields only -- no source_text/output_text (spec 3.6)."""
    rows = conn.execute(
        """
        SELECT id, created_at, source_vendor, target_vendor, filename,
               total_lines, significant_lines, rule_lines, ai_lines,
               unmapped_lines, duration_ms
        FROM conversions
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [_summary_from_row(row) for row in rows]


def get_conversion(
    conn: sqlite3.Connection, conversion_id: int
) -> Optional[dict[str, Any]]:
    """Full record including lines, for diff reconstruction (spec 3.6)."""
    row = conn.execute(
        "SELECT * FROM conversions WHERE id = ?", (conversion_id,)
    ).fetchone()
    if row is None:
        return None

    output_text_lines = row["output_text"].split("\n")
    line_rows = conn.execute(
        """
        SELECT source_line_no, output_line_no, provenance, rule_id, needs_review
        FROM conversion_lines
        WHERE conversion_id = ?
        ORDER BY output_line_no
        """,
        (conversion_id,),
    ).fetchall()

    lines = []
    for lr in line_rows:
        idx = lr["output_line_no"] - 1
        text = output_text_lines[idx] if 0 <= idx < len(output_text_lines) else ""
        lines.append(
            {
                "text": text,
                "provenance": lr["provenance"],
                "source_line": lr["source_line_no"],
                "rule_id": lr["rule_id"],
                "needs_review": bool(lr["needs_review"]),
            }
        )

    record = _summary_from_row(row)
    record["source_text"] = row["source_text"]
    record["output_text"] = row["output_text"]
    record["lines"] = lines
    return record


def delete_conversion(conn: sqlite3.Connection, conversion_id: int) -> bool:
    """Delete a conversion. ``ON DELETE CASCADE`` removes its lines with it."""
    with conn:
        cur = conn.execute(
            "DELETE FROM conversions WHERE id = ?", (conversion_id,)
        )
    return cur.rowcount > 0


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Aggregate dashboard numbers (spec 3.7), via SQL aggregates only."""
    totals = conn.execute(
        """
        SELECT
            COUNT(*)                            AS total_conversions,
            COALESCE(SUM(significant_lines), 0) AS total_significant_lines,
            COALESCE(SUM(rule_lines), 0)        AS rule_lines,
            COALESCE(SUM(ai_lines), 0)          AS ai_lines,
            COALESCE(SUM(unmapped_lines), 0)    AS unmapped_lines
        FROM conversions
        """
    ).fetchone()

    flagged = conn.execute(
        "SELECT COUNT(*) AS n FROM conversion_lines WHERE needs_review = 1"
    ).fetchone()["n"]

    by_direction = conn.execute(
        """
        SELECT source_vendor || '->' || target_vendor AS direction, COUNT(*) AS count
        FROM conversions
        GROUP BY direction
        ORDER BY count DESC
        """
    ).fetchall()

    recent = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS date, COUNT(*) AS count
        FROM conversions
        WHERE created_at >= strftime('%Y-%m-%dT00:00:00Z', 'now', '-13 days')
        GROUP BY date
        ORDER BY date
        """
    ).fetchall()

    significant = totals["total_significant_lines"]
    rule_lines = totals["rule_lines"]

    return {
        "total_conversions": totals["total_conversions"],
        "total_significant_lines": significant,
        "rule_lines": rule_lines,
        "ai_lines": totals["ai_lines"],
        "unmapped_lines": totals["unmapped_lines"],
        "rule_coverage": round(rule_lines / significant, 4) if significant else 0.0,
        "flagged_for_review": flagged,
        "by_direction": [
            {"direction": r["direction"], "count": r["count"]} for r in by_direction
        ],
        "recent": [{"date": r["date"], "count": r["count"]} for r in recent],
    }


# --------------------------------------------------------------------------
# Devices (spec 3.4) -- records only, no connectivity testing (CLAUDE.md 5)
# --------------------------------------------------------------------------

_DEVICE_FIELDS = (
    "hostname",
    "ip_address",
    "vendor",
    "os_version",
    "ssh_port",
    "location",
    "status",
    "notes",
)


def _device_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {field: row[field] for field in ("id", *_DEVICE_FIELDS, "created_at")}


def create_device(conn: sqlite3.Connection, device: dict[str, Any]) -> int:
    if not device.get("hostname"):
        raise ValueError("hostname is required")
    with conn:
        cur = conn.execute(
            """
            INSERT INTO devices (
                hostname, ip_address, vendor, os_version, ssh_port,
                location, status, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device["hostname"],
                device.get("ip_address"),
                device.get("vendor"),
                device.get("os_version"),
                device.get("ssh_port", 22),
                device.get("location"),
                device.get("status", "unknown"),
                device.get("notes"),
                _utc_now_iso(),
            ),
        )
    return cur.lastrowid


def get_device(conn: sqlite3.Connection, device_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return _device_from_row(row) if row else None


def list_devices(
    conn: sqlite3.Connection,
    q: Optional[str] = None,
    vendor: Optional[str] = None,
    location: Optional[str] = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if q:
        clauses.append("(hostname LIKE ? OR ip_address LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if vendor:
        clauses.append("vendor = ?")
        params.append(vendor)
    if location:
        clauses.append("location = ?")
        params.append(location)

    sql = "SELECT * FROM devices"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY hostname"

    rows = conn.execute(sql, params).fetchall()
    return [_device_from_row(row) for row in rows]


def update_device(
    conn: sqlite3.Connection, device_id: int, fields: dict[str, Any]
) -> bool:
    """Update only the columns present in ``fields``. Returns False if the
    device does not exist."""
    updates = {k: v for k, v in fields.items() if k in _DEVICE_FIELDS}
    if not updates:
        return get_device(conn, device_id) is not None
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with conn:
        cur = conn.execute(
            f"UPDATE devices SET {set_clause} WHERE id = ?",
            (*updates.values(), device_id),
        )
    return cur.rowcount > 0


def delete_device(conn: sqlite3.Connection, device_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    return cur.rowcount > 0
