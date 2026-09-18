"""
Tests for netmigrate/api.py, per docs/web-layer-spec.md section 7.

Written as plain assert functions so pytest collects them directly, with a
fallback runner at the bottom (see test_persistence.py) so they run without
pytest installed. Every test builds its own app against a temporary SQLite
file via ``create_app(db_path=...)`` -- never the real netmigrate.db.

Uses FastAPI's TestClient (sync, in-process ASGI -- no real socket, no real
network), so this suite needs no running server.
"""

import io
import json
import os
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from netmigrate.api import create_app  # noqa: E402
from netmigrate import ai_fallback  # noqa: E402


@contextmanager
def temp_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_path=path)
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        os.remove(path)


CISCO_TEXT = """!
hostname SW1
!
vlan 10
 name SALES
!
interface GigabitEthernet0/0/1
 description UPLINK TO CORE
 switchport mode trunk
 switchport trunk allowed vlan 10,20
 no shutdown
!
interface Vlan10
 ip address 192.168.10.1 255.255.255.0
!
ip route 10.0.0.0 255.0.0.0 192.168.10.254
end
"""

HUAWEI_TEXT = """#
sysname SW1
#
vlan batch 10 20
#
vlan 10
 name SALES
#
interface GE0/0/1
 description UPLINK TO CORE
 port link-type trunk
 port trunk allow-pass vlan 10 20
 undo shutdown
#
interface Vlanif10
 ip address 192.168.10.1 255.255.255.0
#
ip route-static 10.0.0.0 255.0.0.0 192.168.10.254
return
"""


# --------------------------------------------------------------------------
# 3.1 POST /api/convert -- contract shape
# --------------------------------------------------------------------------


def test_convert_returns_contract_shape_with_all_documented_keys():
    with temp_client() as client:
        r = client.post(
            "/api/convert",
            json={
                "text": CISCO_TEXT,
                "source_vendor": "cisco",
                "target_vendor": "huawei",
                "filename": "sw01.cfg",
            },
        )
        assert r.status_code == 200
        body = r.json()

        for key in (
            "source_vendor",
            "target_vendor",
            "source_text",
            "output_text",
            "lines",
            "metrics",
            "conversion_id",
            "detected_source",
        ):
            assert key in body, f"missing key {key!r}"

        assert body["source_vendor"] == "cisco_iosxe"
        assert body["target_vendor"] == "huawei_vrp"
        assert body["detected_source"] == "cisco"
        assert isinstance(body["conversion_id"], int)

        for metric_key in (
            "total_lines",
            "significant_lines",
            "rule_lines",
            "ai_lines",
            "unmapped_lines",
            "rule_coverage",
            "duration_ms",
        ):
            assert metric_key in body["metrics"]

        assert len(body["lines"]) > 0
        for line in body["lines"]:
            for line_key in ("text", "provenance", "source_line", "rule_id", "needs_review"):
                assert line_key in line
            assert line["provenance"] in {"RULE", "AI", "UNMAPPED", "GENERATED"}


# --------------------------------------------------------------------------
# Conversion is persisted and retrievable via /api/conversions/{id}
# --------------------------------------------------------------------------


def test_conversion_is_persisted_and_retrievable():
    with temp_client() as client:
        r = client.post(
            "/api/convert",
            json={"text": CISCO_TEXT, "source_vendor": "cisco", "target_vendor": "huawei"},
        )
        conversion_id = r.json()["conversion_id"]

        got = client.get(f"/api/conversions/{conversion_id}")
        assert got.status_code == 200
        record = got.json()
        assert record["id"] == conversion_id
        assert record["source_text"] == CISCO_TEXT
        assert record["output_text"] == r.json()["output_text"]
        assert len(record["lines"]) == len(r.json()["lines"])


def test_get_conversion_404_for_unknown_id():
    with temp_client() as client:
        r = client.get("/api/conversions/999")
        assert r.status_code == 404
        assert "error" in r.json()


# --------------------------------------------------------------------------
# Auto-detection both ways
# --------------------------------------------------------------------------


def test_auto_detection_picks_cisco():
    with temp_client() as client:
        r = client.post(
            "/api/convert",
            json={"text": CISCO_TEXT, "source_vendor": "auto", "target_vendor": "huawei"},
        )
        assert r.status_code == 200
        assert r.json()["detected_source"] == "cisco"
        assert r.json()["source_vendor"] == "cisco_iosxe"


def test_auto_detection_picks_huawei():
    with temp_client() as client:
        r = client.post(
            "/api/convert",
            json={"text": HUAWEI_TEXT, "source_vendor": "auto", "target_vendor": "cisco"},
        )
        assert r.status_code == 200
        assert r.json()["detected_source"] == "huawei"
        assert r.json()["source_vendor"] == "huawei_vrp"


# --------------------------------------------------------------------------
# 3.2 batch: one bad file must not abort the batch
# --------------------------------------------------------------------------


def test_batch_with_one_bad_file_still_returns_results_for_good_ones():
    with temp_client() as client:
        options = {
            "good.cfg": {"source_vendor": "cisco", "target_vendor": "huawei"},
            "bad.cfg": {"source_vendor": "cisco", "target_vendor": "not-a-vendor"},
        }
        files = [
            ("files", ("good.cfg", CISCO_TEXT, "text/plain")),
            ("files", ("bad.cfg", CISCO_TEXT, "text/plain")),
        ]
        r = client.post(
            "/api/convert/batch",
            data={"options": json.dumps(options)},
            files=files,
        )
        assert r.status_code == 200
        body = r.json()
        assert "batch_id" in body
        results = {entry["filename"]: entry for entry in body["results"]}
        assert len(results) == 2

        assert results["good.cfg"]["ok"] is True
        assert isinstance(results["good.cfg"]["conversion_id"], int)
        assert "metrics" in results["good.cfg"]

        assert results["bad.cfg"]["ok"] is False
        assert "error" in results["bad.cfg"]
        assert "conversion_id" not in results["bad.cfg"]


# --------------------------------------------------------------------------
# 3.3 ZIP contains one entry per successful file
# --------------------------------------------------------------------------


def test_batch_zip_contains_one_entry_per_successful_file():
    with temp_client() as client:
        options = {
            "sw01.cfg": {"source_vendor": "cisco", "target_vendor": "huawei"},
            "sw02.cfg": {"source_vendor": "cisco", "target_vendor": "huawei"},
            "bad.cfg": {"source_vendor": "cisco", "target_vendor": "bogus"},
        }
        files = [
            ("files", ("sw01.cfg", CISCO_TEXT, "text/plain")),
            ("files", ("sw02.cfg", CISCO_TEXT, "text/plain")),
            ("files", ("bad.cfg", CISCO_TEXT, "text/plain")),
        ]
        r = client.post(
            "/api/convert/batch", data={"options": json.dumps(options)}, files=files
        )
        batch_id = r.json()["batch_id"]

        zr = client.get(f"/api/batch/{batch_id}/zip")
        assert zr.status_code == 200
        assert zr.headers["content-type"] == "application/zip"

        zf = zipfile.ZipFile(io.BytesIO(zr.content))
        names = sorted(zf.namelist())
        assert names == ["sw01_huawei.cfg", "sw02_huawei.cfg"]

        good_entry = next(e for e in r.json()["results"] if e["filename"] == "sw01.cfg")
        stored = client.get(f"/api/conversions/{good_entry['conversion_id']}").json()
        assert zf.read("sw01_huawei.cfg").decode("utf-8") == stored["output_text"]


def test_batch_zip_404_for_unknown_batch_id():
    with temp_client() as client:
        r = client.get("/api/batch/does-not-exist/zip")
        assert r.status_code == 404
        assert "error" in r.json()


# --------------------------------------------------------------------------
# Device CRUD through the API
# --------------------------------------------------------------------------


def test_device_crud_through_api():
    with temp_client() as client:
        create = client.post(
            "/api/devices",
            json={"hostname": "SW1", "ip_address": "10.0.0.1", "vendor": "cisco_iosxe"},
        )
        assert create.status_code == 201
        device = create.json()
        device_id = device["id"]
        assert device["hostname"] == "SW1"
        assert device["ip_address"] == "10.0.0.1"

        listed = client.get("/api/devices")
        assert listed.status_code == 200
        assert any(d["id"] == device_id for d in listed.json())

        filtered = client.get("/api/devices", params={"vendor": "cisco_iosxe"})
        assert any(d["id"] == device_id for d in filtered.json())

        updated = client.put(f"/api/devices/{device_id}", json={"location": "Bangkok-DC1"})
        assert updated.status_code == 200
        assert updated.json()["location"] == "Bangkok-DC1"
        assert updated.json()["hostname"] == "SW1"  # untouched fields survive

        deleted = client.delete(f"/api/devices/{device_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        gone = client.put(f"/api/devices/{device_id}", json={"location": "X"})
        assert gone.status_code == 404

        gone_delete = client.delete(f"/api/devices/{device_id}")
        assert gone_delete.status_code == 404


def test_device_create_requires_hostname():
    with temp_client() as client:
        r = client.post("/api/devices", json={"ip_address": "10.0.0.1"})
        assert r.status_code == 400
        assert "error" in r.json()


# --------------------------------------------------------------------------
# /api/health -- no API key ever leaks
# --------------------------------------------------------------------------


def test_health_responds_and_never_leaks_the_api_key():
    secret = "sk-super-secret-test-value-12345"
    previous = os.environ.get(ai_fallback.API_KEY_ENV)
    os.environ[ai_fallback.API_KEY_ENV] = secret
    try:
        with temp_client() as client:
            r = client.get("/api/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert "database" in body
            assert "ai_fallback" in body
            assert "rules" in body and body["rules"] > 0
            assert "vendors" in body

            raw = r.text
            assert secret not in raw
            assert secret not in json.dumps(body)
    finally:
        if previous is None:
            os.environ.pop(ai_fallback.API_KEY_ENV, None)
        else:
            os.environ[ai_fallback.API_KEY_ENV] = previous


def test_health_reports_no_api_key_configured_when_absent():
    previous = os.environ.pop(ai_fallback.API_KEY_ENV, None)
    try:
        with temp_client() as client:
            body = client.get("/api/health").json()
            assert body["ai_fallback"]["enabled"] is False
            assert body["ai_fallback"]["reason"] == "no API key configured"
    finally:
        if previous is not None:
            os.environ[ai_fallback.API_KEY_ENV] = previous


# --------------------------------------------------------------------------
# XSS: config text is data, never executed
# --------------------------------------------------------------------------


def test_script_tag_in_config_text_is_escaped_not_executed():
    with temp_client() as client:
        payload_text = CISCO_TEXT.replace(
            "description UPLINK TO CORE",
            "description UPLINK TO CORE <script>alert(1)</script>",
        )
        r = client.post(
            "/api/convert",
            json={"text": payload_text, "source_vendor": "cisco", "target_vendor": "huawei"},
        )
        assert r.status_code == 200
        # JSON, never HTML -- a browser cannot execute a <script> tag that
        # only ever arrives inside a JSON string value.
        assert r.headers["content-type"].startswith("application/json")

        body = r.json()
        # The engine passes description text through verbatim; it comes
        # back unexecuted, as an ordinary (if unusual) string value inside a
        # JSON document -- there is no HTML context here for a browser to
        # execute it in.
        assert "<script>alert(1)</script>" in body["source_text"]


# --------------------------------------------------------------------------
# Oversized upload rejected with 400
# --------------------------------------------------------------------------


def test_oversized_batch_file_rejected_with_400():
    with temp_client() as client:
        huge_text = "! padding line\n" * 200_000  # well over 1 MB
        assert len(huge_text.encode("utf-8")) > 1 * 1024 * 1024

        options = {"huge.cfg": {"source_vendor": "cisco", "target_vendor": "huawei"}}
        files = [("files", ("huge.cfg", huge_text, "text/plain"))]
        r = client.post(
            "/api/convert/batch", data={"options": json.dumps(options)}, files=files
        )
        assert r.status_code == 400
        assert "error" in r.json()


def test_batch_rejects_more_than_twenty_files_with_400():
    with temp_client() as client:
        options = {}
        files = []
        for i in range(21):
            name = f"sw{i}.cfg"
            options[name] = {"source_vendor": "cisco", "target_vendor": "huawei"}
            files.append(("files", (name, CISCO_TEXT, "text/plain")))
        r = client.post(
            "/api/convert/batch", data={"options": json.dumps(options)}, files=files
        )
        assert r.status_code == 400
        assert "error" in r.json()


def test_batch_rejects_unsupported_extension_with_400():
    with temp_client() as client:
        options = {"sw01.exe": {"source_vendor": "cisco", "target_vendor": "huawei"}}
        files = [("files", ("sw01.exe", CISCO_TEXT, "text/plain"))]
        r = client.post(
            "/api/convert/batch", data={"options": json.dumps(options)}, files=files
        )
        assert r.status_code == 400


def test_oversized_json_body_rejected_with_400():
    with temp_client() as client:
        huge_text = "! padding line\n" * 200_000
        r = client.post(
            "/api/convert",
            json={"text": huge_text, "source_vendor": "cisco", "target_vendor": "huawei"},
        )
        assert r.status_code == 400
        assert "error" in r.json()


# --------------------------------------------------------------------------
# SSE stream yields events and terminates with done: true
# --------------------------------------------------------------------------


def test_sse_stream_yields_events_and_terminates_with_done_true():
    with temp_client() as client:
        conv = client.post(
            "/api/convert",
            json={"text": CISCO_TEXT, "source_vendor": "cisco", "target_vendor": "huawei"},
        ).json()
        device = client.post("/api/devices", json={"hostname": "SW1", "ip_address": "10.0.0.1"}).json()

        r = client.get(
            "/api/deploy/stream",
            params={"conversion_id": conv["conversion_id"], "device_id": device["id"]},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")

        events = []
        for chunk in r.text.split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            assert chunk.startswith("data: ")
            events.append(json.loads(chunk[len("data: "):]))

        assert len(events) > 0
        for event in events:
            assert event["level"] in {"INFO", "SUCCESS", "WARNING", "ERROR", "COMMAND"}

        assert events[-1]["level"] == "SUCCESS"
        assert events[-1].get("done") is True
        assert any(e["level"] == "COMMAND" for e in events)


def test_sse_stream_404_for_unknown_conversion_or_device():
    with temp_client() as client:
        device = client.post("/api/devices", json={"hostname": "SW1"}).json()
        r = client.get(
            "/api/deploy/stream",
            params={"conversion_id": 999, "device_id": device["id"]},
        )
        assert r.status_code == 404
        assert "error" in r.json()


# --------------------------------------------------------------------------
# Page routes (spec section 4) -- Jinja2Templates / StaticFiles wiring
# --------------------------------------------------------------------------


def test_every_page_route_renders_html():
    with temp_client() as client:
        for route in (
            "/",
            "/batch",
            "/devices",
            "/deploy",
            "/dashboard",
            "/history",
            "/settings",
        ):
            r = client.get(route)
            assert r.status_code == 200, route
            assert r.headers["content-type"].startswith("text/html")
            assert "<html" in r.text.lower()


def test_static_files_are_served():
    with temp_client() as client:
        r = client.get("/static/app.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]

        r = client.get("/static/diff.js")
        assert r.status_code == 200


def test_unknown_page_route_is_404_not_swallowed_by_api():
    with temp_client() as client:
        r = client.get("/no-such-page")
        assert r.status_code == 404


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
