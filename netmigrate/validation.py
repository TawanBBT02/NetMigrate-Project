"""
Validation harness: round-trip fidelity and golden-file comparison.

Round-trip fidelity is measured on the **IR**, not on the text.

Why: converting Cisco -> Huawei -> Cisco legitimately changes the text.
Comment markers differ, separators regenerate, and blocks may emit in a
different order. None of that is data loss. Comparing text would report
failures that are not failures, and H2 would understate the result.

Comparing the IR asks the question that actually matters: did any
configuration *intent* get lost or altered on the way round? ``source_line``
is excluded from comparison because line numbers necessarily change.
"""

from __future__ import annotations

import dataclasses
import statistics
import time
from dataclasses import fields, is_dataclass
from typing import Any

from netmigrate.engine import can_convert, convert, get_parser
from netmigrate.ir import DeviceConfig, Vendor

# Fields that are expected to differ after a round trip and carry no intent.
IGNORED_FIELDS = {"source_line", "total_lines", "significant_lines",
                  "source_vendor", "suggestion", "rationale", "provenance"}


# --------------------------------------------------------------------------
# IR comparison
# --------------------------------------------------------------------------


def ir_diff(left: Any, right: Any, path: str = "") -> list[str]:
    """Structurally compare two IR objects. Returns a list of differences.

    Empty list means semantically identical.
    """
    diffs: list[str] = []

    if is_dataclass(left) and is_dataclass(right):
        if type(left) is not type(right):
            return [f"{path}: type {type(left).__name__} != {type(right).__name__}"]
        for f in fields(left):
            if f.name in IGNORED_FIELDS:
                continue
            diffs.extend(
                ir_diff(
                    getattr(left, f.name),
                    getattr(right, f.name),
                    f"{path}.{f.name}" if path else f.name,
                )
            )
        return diffs

    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                diffs.append(f"{path}[{key}]: missing on left")
            elif key not in right:
                diffs.append(f"{path}[{key}]: missing on right")
            else:
                diffs.extend(ir_diff(left[key], right[key], f"{path}[{key}]"))
        return diffs

    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            diffs.append(f"{path}: length {len(left)} != {len(right)}")
        for i, (a, b) in enumerate(zip(left, right)):
            diffs.extend(ir_diff(a, b, f"{path}[{i}]"))
        return diffs

    if isinstance(left, set) and isinstance(right, set):
        if left != right:
            diffs.append(f"{path}: {sorted(left)} != {sorted(right)}")
        return diffs

    if left != right:
        diffs.append(f"{path}: {left!r} != {right!r}")
    return diffs


def ir_equal(left: Any, right: Any) -> bool:
    return not ir_diff(left, right)


# --------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------


@dataclasses.dataclass
class RoundTripReport:
    source_vendor: Vendor
    target_vendor: Vendor
    ok: bool
    differences: list[str] = dataclasses.field(default_factory=list)
    skipped: bool = False
    reason: str = ""

    # Metrics from the outbound leg, for the evaluation table.
    significant_lines: int = 0
    rule_lines: int = 0
    ai_lines: int = 0
    unmapped_lines: int = 0
    duration_ms: float = 0.0

    @property
    def rule_coverage(self) -> float:
        if self.significant_lines == 0:
            return 0.0
        return self.rule_lines / self.significant_lines


def round_trip(text: str, source: Vendor, target: Vendor) -> RoundTripReport:
    """Convert source -> target -> source and compare the IR both ways.

    Returns a report rather than raising, so the harness can run the whole
    corpus and tabulate.
    """
    if not can_convert(source, target):
        return RoundTripReport(
            source, target, ok=False, skipped=True,
            reason=f"no {source.value} parser or {target.value} renderer yet",
        )
    if not can_convert(target, source):
        return RoundTripReport(
            source, target, ok=False, skipped=True,
            reason=f"no {target.value} parser or {source.value} renderer yet",
        )

    outbound = convert(text, source, target)
    inbound = convert(outbound.output_text, target, source)

    parse_source = get_parser(source)
    original_ir = parse_source(text)
    returned_ir = parse_source(inbound.output_text)

    diffs = ir_diff(_comparable(original_ir), _comparable(returned_ir))

    return RoundTripReport(
        source_vendor=source,
        target_vendor=target,
        ok=not diffs,
        differences=diffs,
        significant_lines=outbound.significant_lines,
        rule_lines=outbound.rule_lines,
        ai_lines=outbound.ai_lines,
        unmapped_lines=outbound.unmapped_lines,
        duration_ms=outbound.duration_ms,
    )


def _comparable(cfg: DeviceConfig) -> DeviceConfig:
    """Normalise an IR for comparison.

    Unmapped blocks are excluded: a construct with no rule is expected to
    survive as a comment, and comments do not parse back into the IR. Loss
    there is already counted by the unmapped metric, so counting it again as
    a round-trip failure would double-penalise the same limitation.

    Ordering is normalised, since block emission order is a renderer choice.
    """
    clone = dataclasses.replace(
        cfg,
        vlans=sorted(cfg.vlans, key=lambda v: v.vlan_id),
        interfaces=sorted(cfg.interfaces, key=lambda i: (i.if_type, i.if_number)),
        static_routes=sorted(
            cfg.static_routes, key=lambda r: (r.prefix, r.mask, r.next_hop)
        ),
        unmapped=[],
    )
    if clone.ospf is not None:
        clone.ospf = dataclasses.replace(
            clone.ospf,
            areas={
                area: sorted(nets, key=lambda n: (n.address, n.wildcard))
                for area, nets in clone.ospf.areas.items()
            },
        )
    return clone


# --------------------------------------------------------------------------
# Golden files
# --------------------------------------------------------------------------


@dataclasses.dataclass
class GoldenReport:
    name: str
    ok: bool
    diff: str = ""
    skipped: bool = False
    reason: str = ""


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------


@dataclasses.dataclass
class TimingReport:
    """Conversion timing over several repeats.

    A single measurement of a sub-millisecond operation is mostly scheduler
    noise. Report the median as the headline figure -- it is robust against
    the occasional outlier from garbage collection or the OS -- and keep min
    and max so the spread is visible in the thesis rather than hidden.
    """

    repeats: int
    median_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float

    @property
    def seconds_median(self) -> float:
        return self.median_ms / 1000.0

    def reduction_vs(self, manual_seconds: float) -> float:
        """Proportional time reduction against a manual baseline. Tests H4."""
        if manual_seconds <= 0:
            return 0.0
        return 1.0 - (self.seconds_median / manual_seconds)


def benchmark_convert(
    text: str,
    source: Vendor,
    target: Vendor,
    repeats: int = 50,
) -> TimingReport | None:
    """Time a conversion over ``repeats`` runs. None if the pair is missing.

    The AI fallback is never invoked here: it makes a network call, which
    would dominate the measurement and make the figure unreproducible.
    """
    if not can_convert(source, target):
        return None

    samples: list[float] = []
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        convert(text, source, target)
        samples.append((time.perf_counter() - started) * 1000.0)

    samples.sort()
    return TimingReport(
        repeats=len(samples),
        median_ms=statistics.median(samples),
        mean_ms=statistics.fmean(samples),
        min_ms=samples[0],
        max_ms=samples[-1],
    )


# --------------------------------------------------------------------------
# Text normalisation for golden comparison
# --------------------------------------------------------------------------


def normalise_text(text: str) -> str:
    """Trim trailing whitespace and collapse blank runs, for comparison.

    Leading whitespace is preserved: indentation carries block structure in a
    configuration file, so it must not be stripped. Only whole blank lines at
    the start and end are removed.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]

    start, end = 0, len(lines)
    while start < end and not lines[start]:
        start += 1
    while end > start and not lines[end - 1]:
        end -= 1

    out: list[str] = []
    for ln in lines[start:end]:
        if not ln and out and not out[-1]:
            continue
        out.append(ln)
    return "\n".join(out)


def check_golden(
    name: str,
    source_text: str,
    expected_text: str,
    source: Vendor,
    target: Vendor,
) -> GoldenReport:
    """Convert and compare against a stored expected output, byte for byte."""
    if not can_convert(source, target):
        return GoldenReport(
            name, ok=False, skipped=True,
            reason=f"cannot convert {source.value} -> {target.value} yet",
        )

    result = convert(source_text, source, target)
    got = normalise_text(result.output_text)
    want = normalise_text(expected_text)

    if got == want:
        return GoldenReport(name, ok=True)

    import difflib

    diff = "\n".join(
        difflib.unified_diff(
            want.splitlines(),
            got.splitlines(),
            fromfile=f"expected/{name}",
            tofile=f"actual/{name}",
            lineterm="",
        )
    )
    return GoldenReport(name, ok=False, diff=diff)