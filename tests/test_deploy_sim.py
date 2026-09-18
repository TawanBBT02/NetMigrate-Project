"""
Tests for netmigrate/deploy_sim.py.

Plain assert functions with a fallback runner (see test_persistence.py) so
this collects under pytest and also runs standalone. No pytest-asyncio --
CLAUDE.md forbids new dependencies, so async tests drive the generator with
asyncio.run() directly. Every test passes speed=0.01 so the suite does not
sit through several seconds of simulated delay per run.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate import deploy_sim  # noqa: E402

FAST = 0.01


def _device(**overrides):
    device = {
        "id": 1,
        "hostname": "SW1",
        "ip_address": "10.0.0.1",
        "vendor": "huawei_vrp",
        "ssh_port": 22,
    }
    device.update(overrides)
    return device


def _conversion(lines=None, **overrides):
    if lines is None:
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
    conversion = {
        "source_vendor": "cisco_iosxe",
        "target_vendor": "huawei_vrp",
        "lines": lines,
    }
    conversion.update(overrides)
    return conversion


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# Basic shape
# --------------------------------------------------------------------------


def test_events_are_dicts_with_ts_level_message():
    events = _run(deploy_sim.collect(_device(), _conversion(), speed=FAST))
    assert len(events) > 0
    for event in events:
        assert set(("ts", "level", "message")) <= set(event.keys())
        assert event["level"] in {"INFO", "SUCCESS", "WARNING", "ERROR", "COMMAND"}
        # ISO 8601 UTC, per spec 3.5 / section 5.
        assert event["ts"].endswith("Z")


def test_generator_consumes_without_a_web_server():
    # deploy_sim must be usable directly -- no FastAPI/TestClient involved.
    async def drain():
        collected = []
        async for event in deploy_sim.simulate_deployment(_device(), _conversion(), speed=FAST):
            collected.append(event)
        return collected

    events = _run(drain())
    assert len(events) > 0


# --------------------------------------------------------------------------
# COMMAND / WARNING emission
# --------------------------------------------------------------------------


def test_emits_one_command_per_non_blank_config_line():
    conversion = _conversion()
    events = _run(deploy_sim.collect(_device(), conversion, speed=FAST))
    command_events = [e for e in events if e["level"] == "COMMAND"]

    non_blank_texts = [ln["text"] for ln in conversion["lines"] if ln["text"].strip()]
    assert [e["message"] for e in command_events] == non_blank_texts


def test_blank_lines_produce_no_command_event():
    lines = [
        {"text": "", "provenance": "GENERATED", "source_line": None, "rule_id": None, "needs_review": False},
        {"text": "   ", "provenance": "GENERATED", "source_line": None, "rule_id": None, "needs_review": False},
        {"text": "sysname SW1", "provenance": "RULE", "source_line": 1, "rule_id": "hostname", "needs_review": False},
    ]
    events = _run(deploy_sim.collect(_device(), _conversion(lines=lines), speed=FAST))
    command_events = [e for e in events if e["level"] == "COMMAND"]
    assert len(command_events) == 1
    assert command_events[0]["message"] == "sysname SW1"


def test_needs_review_line_gets_a_warning_right_after_its_command():
    events = _run(deploy_sim.collect(_device(), _conversion(), speed=FAST))
    levels = [e["level"] for e in events]

    # The third sample line (AI, needs_review=True) must produce COMMAND
    # immediately followed by WARNING.
    command_indices = [i for i, e in enumerate(events) if e["level"] == "COMMAND"]
    ai_command_idx = command_indices[2]
    assert levels[ai_command_idx] == "COMMAND"
    assert levels[ai_command_idx + 1] == "WARNING"
    warning_event = events[ai_command_idx + 1]
    assert "[NETMIGRATE-AI-REVIEW] suggestion" in warning_event["message"]
    assert warning_event["source_line"] == 9


def test_lines_without_needs_review_produce_no_warning():
    lines = [
        {"text": "sysname SW1", "provenance": "RULE", "source_line": 1, "rule_id": "hostname", "needs_review": False},
    ]
    events = _run(deploy_sim.collect(_device(), _conversion(lines=lines), speed=FAST))
    assert not any(e["level"] == "WARNING" for e in events)


def test_no_config_lines_still_completes():
    events = _run(deploy_sim.collect(_device(), _conversion(lines=[]), speed=FAST))
    assert not any(e["level"] == "COMMAND" for e in events)
    assert events[-1]["level"] == "SUCCESS"
    assert events[-1].get("done") is True


# --------------------------------------------------------------------------
# Stage ordering and completion
# --------------------------------------------------------------------------


def test_stage_order_is_connect_auth_config_commands_commit_close():
    events = _run(deploy_sim.collect(_device(), _conversion(), speed=FAST))
    messages = [(e["level"], e["message"]) for e in events]

    assert messages[0] == ("INFO", "Connecting to 10.0.0.1:22")
    assert messages[1] == ("INFO", "Authenticating to SW1")
    assert messages[2][0] == "SUCCESS"
    assert messages[3] == ("INFO", "Entering configuration mode")
    assert messages[4][0] == "SUCCESS"

    # Commit and close happen after the last COMMAND/WARNING event.
    last_command_like_idx = max(
        i for i, e in enumerate(events) if e["level"] in {"COMMAND", "WARNING"}
    )
    remaining_messages = [e["message"] for e in events[last_command_like_idx + 1:]]
    assert "Committing configuration" in remaining_messages
    assert "Configuration committed" in remaining_messages
    assert any("Closing connection" in m for m in remaining_messages)


def test_final_event_is_success_with_done_true():
    events = _run(deploy_sim.collect(_device(), _conversion(), speed=FAST))
    final = events[-1]
    assert final["level"] == "SUCCESS"
    assert final["done"] is True

    # done must not appear (or must be falsy) on every other event.
    for event in events[:-1]:
        assert not event.get("done")


def test_device_fields_are_used_in_connect_and_close_messages():
    device = _device(hostname="RT-CORE", ip_address="192.168.1.1", ssh_port=2222)
    events = _run(deploy_sim.collect(device, _conversion(), speed=FAST))
    assert events[0]["message"] == "Connecting to 192.168.1.1:2222"
    assert any("RT-CORE" in e["message"] for e in events if e["level"] == "INFO")


def test_missing_optional_device_fields_use_sane_defaults():
    device = {"hostname": "SW1"}  # no ip_address / ssh_port
    events = _run(deploy_sim.collect(device, _conversion(), speed=FAST))
    assert events[0]["message"] == "Connecting to 0.0.0.0:22"


# --------------------------------------------------------------------------
# SSE framing helper
# --------------------------------------------------------------------------


def test_format_sse_produces_data_line_with_valid_json():
    import json

    event = {"ts": "2026-09-20T18:00:01Z", "level": "INFO", "message": "hi"}
    framed = deploy_sim.format_sse(event)
    assert framed.startswith("data: ")
    assert framed.endswith("\n\n")
    payload = json.loads(framed[len("data: "):].strip())
    assert payload == event


# --------------------------------------------------------------------------
# Timing sanity (no sockets/network -- asyncio.sleep only, but must still
# actually take time proportional to `speed`, not be a no-op)
# --------------------------------------------------------------------------


def test_speed_scales_elapsed_time():
    import time

    async def timed(speed):
        start = time.perf_counter()
        await deploy_sim.collect(_device(), _conversion(), speed=speed)
        return time.perf_counter() - start

    fast_elapsed = _run(timed(0.005))
    slower_elapsed = _run(timed(0.05))
    assert slower_elapsed > fast_elapsed


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
