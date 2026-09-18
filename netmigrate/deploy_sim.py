"""
Simulated deployment log generator for module 4 (docs/web-layer-spec.md 3.5).

CLAUDE.md section 5 rules real device connectivity out of scope for this
project entirely -- no SSH, no Netmiko/Paramiko, no sockets. This module
produces the same shape of event a real push would log, timed with
``asyncio.sleep`` only, so ``api.py`` can stream it over SSE and this file
stays unit-testable on its own, with no web server and no database involved.

The generator takes plain dicts, not the persistence-layer or IR types
directly: a device record shaped like ``persistence.get_device()`` and a
conversion record shaped like ``persistence.get_conversion()`` (equivalently
``ConversionResult.to_dict()`` plus the device it targets). That keeps this
module decoupled from both -- api.py is the only place that wires them
together -- and lets tests hand-build minimal dicts instead of touching
SQLite.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

# Wall-clock delay per stage at speed=1.0. Chosen so a config of a few dozen
# lines (the size any config in this project's scope reaches) finishes well
# under the spec's 10 s ceiling: fixed stages sum to ~2.6 s, leaving room for
# per-line delay before the total would risk running long.
_STAGE_DELAY = 0.35
_SHORT_DELAY = 0.2
_COMMAND_DELAY = 0.08
_WARNING_DELAY = 0.04

LogEvent = dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(level: str, message: str, **extra: Any) -> LogEvent:
    event: LogEvent = {"ts": _now_iso(), "level": level, "message": message}
    event.update(extra)
    return event


async def simulate_deployment(
    device: dict[str, Any],
    conversion: dict[str, Any],
    *,
    speed: float = 1.0,
) -> AsyncIterator[LogEvent]:
    """Yield a simulated deployment log, one event at a time.

    ``device`` needs ``hostname``; ``ip_address`` and ``ssh_port`` are used
    if present. ``conversion`` needs ``lines``, each shaped like an entry in
    ``ConversionResult.to_dict()["lines"]`` (``text`` and ``needs_review`` are
    read; ``rule_id``/``source_line`` are echoed onto WARNING events when
    present). Blank output lines (separators, generated blank lines) are
    skipped -- there is nothing to "send".

    ``speed`` scales every delay; tests pass a small value (e.g. ``0.01``) so
    the whole generator drains in milliseconds instead of several seconds.
    """
    hostname = device.get("hostname") or "device"
    ip = device.get("ip_address") or "0.0.0.0"
    port = device.get("ssh_port") or 22
    lines = conversion.get("lines", [])

    async def wait(seconds: float) -> None:
        await asyncio.sleep(seconds * speed)

    await wait(_STAGE_DELAY)
    yield _event("INFO", f"Connecting to {ip}:{port}")

    await wait(_STAGE_DELAY)
    yield _event("INFO", f"Authenticating to {hostname}")
    await wait(_SHORT_DELAY)
    yield _event("SUCCESS", "Authentication successful")

    await wait(_SHORT_DELAY)
    yield _event("INFO", "Entering configuration mode")
    await wait(_SHORT_DELAY)
    yield _event("SUCCESS", "Configuration mode entered")

    for line in lines:
        text = line.get("text", "")
        if not text.strip():
            continue
        await wait(_COMMAND_DELAY)
        yield _event("COMMAND", text)
        if line.get("needs_review"):
            await wait(_WARNING_DELAY)
            yield _event(
                "WARNING",
                f"Flagged for manual review: {text.strip()}",
                rule_id=line.get("rule_id"),
                source_line=line.get("source_line"),
            )

    await wait(_STAGE_DELAY)
    yield _event("INFO", "Committing configuration")
    await wait(_STAGE_DELAY)
    yield _event("SUCCESS", "Configuration committed")

    await wait(_SHORT_DELAY)
    yield _event("INFO", f"Closing connection to {hostname}")
    await wait(_SHORT_DELAY)
    yield _event("SUCCESS", "Deployment complete", done=True)


async def collect(
    device: dict[str, Any],
    conversion: dict[str, Any],
    *,
    speed: float = 1.0,
) -> list[LogEvent]:
    """Drain :func:`simulate_deployment` into a list. Convenience for tests
    and for any caller (e.g. a log download) that wants the full run rather
    than a live stream."""
    return [event async for event in simulate_deployment(device, conversion, speed=speed)]


def format_sse(event: LogEvent) -> str:
    """Render one event as an SSE ``data:`` line, matching spec 3.5.

    Separate from the generator on purpose: the generator yields plain
    dicts so tests can assert on structured fields directly, without parsing
    SSE framing back out of a string.
    """
    import json

    return f"data: {json.dumps(event)}\n\n"
