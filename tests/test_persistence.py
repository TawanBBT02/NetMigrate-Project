"""
Tests for netmigrate/persistence.py.

Written as plain assert functions so pytest collects them directly, with a
fallback runner at the bottom so they run without pytest installed (see
test_core.py). Every test opens its own temporary database file -- never the
real netmigrate.db -- and removes it afterwards.
"""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate import persistence as db  # noqa: E402


@contextmanager
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = db.connect(path)
    try:
        yield conn
    finally:
        conn.close()
        os.remove(path)


def _sample_payload(
    source="cisco_iosxe",
    target="huawei_vrp",
    significant=4,
    rule=3,
    ai=1,
    unmapped=0,
    flagged=1,
):
    """A payload shaped exactly like ConversionResult.to_dict() (CLAUDE.md
    section 4), small enough to hand-check every field a test reads back."""
    lines = [
        {
            "text": "sysname SW1",
            "provenance": "RULE",
            "source_line": 1,
            "rule_id": "hostname",
            "needs_review": False,
        },
        {
            "text": " port link-type access",
            "provenance": "RULE",
            "source_line": 5,
            "rule_id": "port.link-type",
            "needs_review": False,
        },
        {
            "text": "# [NETMIGRATE-AI-REVIEW] suggestion",
            "provenance": "AI",
            "source_line": 9,
            "rule_id": None,
            "needs_review": True,
        },
        {
            "text": "#",
            "provenance": "GENERATED",
            "source_line": None,
            "rule_id": None,
            "needs_review": False,
        },
    ]
    return {
        "source_vendor": source,
        "target_vendor": target,
        "source_text": "hostname SW1\n...\n",
        "output_text": "\n".join(ln["text"] for ln in lines),
        "lines": lines,
        "metrics": {
            "total_lines": 6,
            "significant_lines": significant,
            "rule_lines": rule,
            "ai_lines": ai,
            "unmapped_lines": unmapped,
            "rule_coverage": round(rule / significant, 4),
            "duration_ms": 0.25,
        },
    }


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_schema_creates_cleanly_on_empty_db():
    with temp_db() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"conversions", "conversion_lines", "devices"} <= tables

        # Calling init_schema again (e.g. a second connect()) must not error
        # or clobber existing rows -- CREATE TABLE IF NOT EXISTS.
        db.init_schema(conn)
        assert conn.execute("SELECT COUNT(*) AS n FROM conversions").fetchone()["n"] == 0


# --------------------------------------------------------------------------
# Save / read a conversion
# --------------------------------------------------------------------------


def test_save_and_read_back_conversion_with_lines():
    with temp_db() as conn:
        payload = _sample_payload()
        conversion_id = db.save_conversion(conn, payload, filename="sw01.cfg")
        assert isinstance(conversion_id, int)

        record = db.get_conversion(conn, conversion_id)
        assert record is not None
        assert record["filename"] == "sw01.cfg"
        assert record["source_vendor"] == "cisco_iosxe"
        assert record["target_vendor"] == "huawei_vrp"
        assert record["source_text"] == payload["source_text"]
        assert record["output_text"] == payload["output_text"]
        assert record["metrics"]["rule_lines"] == 3
        assert record["metrics"]["ai_lines"] == 1
        assert record["metrics"]["rule_coverage"] == round(3 / 4, 4)

        # Lines come back in output order with text reconstructed from
        # output_text, not duplicated in conversion_lines.
        assert len(record["lines"]) == 4
        assert [ln["text"] for ln in record["lines"]] == [
            ln["text"] for ln in payload["lines"]
        ]
        assert [ln["provenance"] for ln in record["lines"]] == [
            "RULE",
            "RULE",
            "AI",
            "GENERATED",
        ]
        assert record["lines"][2]["needs_review"] is True
        assert record["lines"][2]["rule_id"] is None
        assert record["lines"][1]["rule_id"] == "port.link-type"
        assert record["lines"][3]["source_line"] is None


def test_get_conversion_returns_none_for_unknown_id():
    with temp_db() as conn:
        assert db.get_conversion(conn, 999) is None


def test_list_conversions_is_summary_only_and_newest_first():
    with temp_db() as conn:
        first = db.save_conversion(conn, _sample_payload())
        second = db.save_conversion(conn, _sample_payload())

        summaries = db.list_conversions(conn)
        assert [s["id"] for s in summaries] == [second, first]
        assert "source_text" not in summaries[0]
        assert "output_text" not in summaries[0]
        assert "lines" not in summaries[0]

        # limit/offset paginate.
        assert [s["id"] for s in db.list_conversions(conn, limit=1)] == [second]
        assert [s["id"] for s in db.list_conversions(conn, limit=1, offset=1)] == [first]


# --------------------------------------------------------------------------
# Metrics aggregation
# --------------------------------------------------------------------------


def test_stats_aggregate_across_several_conversions():
    with temp_db() as conn:
        db.save_conversion(
            conn,
            _sample_payload(source="cisco_iosxe", target="huawei_vrp", significant=4, rule=3, ai=1),
        )
        db.save_conversion(
            conn,
            _sample_payload(source="cisco_iosxe", target="huawei_vrp", significant=10, rule=8, ai=1, unmapped=1),
        )
        db.save_conversion(
            conn,
            _sample_payload(source="huawei_vrp", target="cisco_iosxe", significant=6, rule=6, ai=0, unmapped=0),
        )

        stats = db.get_stats(conn)
        assert stats["total_conversions"] == 3
        assert stats["total_significant_lines"] == 4 + 10 + 6
        assert stats["rule_lines"] == 3 + 8 + 6
        assert stats["ai_lines"] == 1 + 1 + 0
        assert stats["unmapped_lines"] == 0 + 1 + 0
        assert stats["rule_coverage"] == round((3 + 8 + 6) / (4 + 10 + 6), 4)

        # Every sample payload flags exactly one AI line for review.
        assert stats["flagged_for_review"] == 3

        by_direction = {d["direction"]: d["count"] for d in stats["by_direction"]}
        assert by_direction == {"cisco_iosxe->huawei_vrp": 2, "huawei_vrp->cisco_iosxe": 1}

        # All saved "now", so they fall inside the 14-day recent window.
        assert sum(r["count"] for r in stats["recent"]) == 3


def test_stats_on_empty_database_does_not_divide_by_zero():
    with temp_db() as conn:
        stats = db.get_stats(conn)
        assert stats["total_conversions"] == 0
        assert stats["rule_coverage"] == 0.0
        assert stats["by_direction"] == []
        assert stats["recent"] == []


# --------------------------------------------------------------------------
# Cascade delete
# --------------------------------------------------------------------------


def test_delete_conversion_cascades_to_lines():
    with temp_db() as conn:
        conversion_id = db.save_conversion(conn, _sample_payload())
        line_count = conn.execute(
            "SELECT COUNT(*) AS n FROM conversion_lines WHERE conversion_id = ?",
            (conversion_id,),
        ).fetchone()["n"]
        assert line_count == 4

        assert db.delete_conversion(conn, conversion_id) is True
        assert db.get_conversion(conn, conversion_id) is None

        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM conversion_lines WHERE conversion_id = ?",
            (conversion_id,),
        ).fetchone()["n"]
        assert remaining == 0


def test_delete_conversion_returns_false_for_unknown_id():
    with temp_db() as conn:
        assert db.delete_conversion(conn, 999) is False


# --------------------------------------------------------------------------
# Device CRUD
# --------------------------------------------------------------------------


def test_device_crud_round_trips():
    with temp_db() as conn:
        device_id = db.create_device(
            conn,
            {
                "hostname": "SW1",
                "ip_address": "10.0.0.1",
                "vendor": "cisco_iosxe",
                "location": "Bangkok-DC1",
            },
        )
        assert isinstance(device_id, int)

        fetched = db.get_device(conn, device_id)
        assert fetched["hostname"] == "SW1"
        assert fetched["ip_address"] == "10.0.0.1"
        assert fetched["ssh_port"] == 22  # column default
        assert fetched["status"] == "unknown"  # column default
        assert fetched["created_at"]

        assert db.update_device(conn, device_id, {"location": "Bangkok-DC2", "status": "active"}) is True
        updated = db.get_device(conn, device_id)
        assert updated["location"] == "Bangkok-DC2"
        assert updated["status"] == "active"
        # Unrelated columns must survive a partial update untouched.
        assert updated["hostname"] == "SW1"

        assert db.delete_device(conn, device_id) is True
        assert db.get_device(conn, device_id) is None
        assert db.delete_device(conn, device_id) is False


def test_device_requires_hostname():
    with temp_db() as conn:
        try:
            db.create_device(conn, {"ip_address": "10.0.0.1"})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for missing hostname")


def test_list_devices_filters_by_query_vendor_and_location():
    with temp_db() as conn:
        db.create_device(conn, {"hostname": "SW1", "ip_address": "10.0.0.1", "vendor": "cisco_iosxe", "location": "DC1"})
        db.create_device(conn, {"hostname": "SW2", "ip_address": "10.0.0.2", "vendor": "huawei_vrp", "location": "DC1"})
        db.create_device(conn, {"hostname": "RT1", "ip_address": "10.0.1.1", "vendor": "cisco_iosxe", "location": "DC2"})

        all_devices = db.list_devices(conn)
        assert [d["hostname"] for d in all_devices] == ["RT1", "SW1", "SW2"]  # ORDER BY hostname

        assert [d["hostname"] for d in db.list_devices(conn, q="SW")] == ["SW1", "SW2"]
        assert [d["hostname"] for d in db.list_devices(conn, vendor="huawei_vrp")] == ["SW2"]
        assert [d["hostname"] for d in db.list_devices(conn, location="DC2")] == ["RT1"]
        assert [d["hostname"] for d in db.list_devices(conn, q="10.0.0.2")] == ["SW2"]


def test_get_connection_context_manager_closes_connection():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with db.get_connection(path) as conn:
            db.create_device(conn, {"hostname": "SW1"})
        # The connection is closed on exit; using it now must raise.
        try:
            conn.execute("SELECT 1")
        except Exception:
            pass
        else:
            raise AssertionError("expected connection to be closed")

        # A fresh connection to the same file still sees the schema and row.
        with db.get_connection(path) as conn2:
            assert len(db.list_devices(conn2)) == 1
    finally:
        os.remove(path)


# --------------------------------------------------------------------------
# Fallback runner
# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        (n, o)
        for n, o in sorted(globals().items())
        if n.startswith("test_") and callable(o)
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
