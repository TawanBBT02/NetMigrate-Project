"""
Conversion engine: the single entry point the web layer calls.

Parsers and renderers register themselves here, so adding a vendor means
registering two functions rather than touching this module. That is the
n + n property from proposal 2.4.4(ง).

The registry starts with the Cisco parser only. Renderers register as they
are written; ``convert`` raises a clear error until the pair exists, and the
evaluation harness reports that as "not yet implemented" instead of crashing.
"""

from __future__ import annotations

import time
from typing import Callable

from netmigrate.ir import (
    ConversionResult,
    DeviceConfig,
    OutputLine,
    Provenance,
    Vendor,
)

# vendor -> text -> DeviceConfig
Parser = Callable[[str], DeviceConfig]
# vendor -> DeviceConfig -> list[OutputLine]
Renderer = Callable[[DeviceConfig], list[OutputLine]]

_PARSERS: dict[Vendor, Parser] = {}
_RENDERERS: dict[Vendor, Renderer] = {}


class VendorNotSupported(RuntimeError):
    """Raised when a parser or renderer has not been registered."""


def register_parser(vendor: Vendor, fn: Parser) -> None:
    _PARSERS[vendor] = fn


def register_renderer(vendor: Vendor, fn: Renderer) -> None:
    _RENDERERS[vendor] = fn


def has_parser(vendor: Vendor) -> bool:
    return vendor in _PARSERS


def has_renderer(vendor: Vendor) -> bool:
    return vendor in _RENDERERS


def can_convert(source: Vendor, target: Vendor) -> bool:
    return has_parser(source) and has_renderer(target)


def get_parser(vendor: Vendor) -> Parser:
    if vendor not in _PARSERS:
        raise VendorNotSupported(f"no parser registered for {vendor.value}")
    return _PARSERS[vendor]


def get_renderer(vendor: Vendor) -> Renderer:
    if vendor not in _RENDERERS:
        raise VendorNotSupported(f"no renderer registered for {vendor.value}")
    return _RENDERERS[vendor]


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


def convert(
    text: str,
    source: Vendor,
    target: Vendor,
    ai_fallback: Callable[[DeviceConfig], None] | None = None,
) -> ConversionResult:
    """Convert configuration text from one vendor to another.

    ``ai_fallback`` is called once, after parsing, with the DeviceConfig. It
    may fill ``suggestion`` on UnmappedBlock entries. It is never called for
    constructs the rule engine handled -- that condition is what keeps the
    coverage metric meaningful (proposal 2.3.1.1).
    """
    started = time.perf_counter()

    parse = get_parser(source)
    render = get_renderer(target)

    cfg = parse(text)

    if ai_fallback is not None and cfg.unmapped:
        ai_fallback(cfg)

    lines = render(cfg)

    # No int() cast: a conversion takes well under a millisecond, so
    # truncating to whole ms reports 0 for every file.
    duration_ms = (time.perf_counter() - started) * 1000.0

    result = ConversionResult(
        source_vendor=source,
        target_vendor=target,
        source_text=text,
        output_text="\n".join(ln.text for ln in lines),
        lines=lines,
        total_lines=cfg.total_lines,
        significant_lines=cfg.significant_lines,
        duration_ms=duration_ms,
    )

    # Coverage is measured on the SOURCE side, not the output side.
    #
    # Output-side counting would distort the ratio: the OSPF transformation
    # turns three Cisco lines into four Huawei lines, and `vlan 10,20` turns
    # one line into two blocks. Dividing output lines by source lines would
    # then report coverage above 100% on some files.
    #
    # The source-side question is the one the proposal asks: of the
    # significant lines in the input, how many did a rule recognise? Every
    # line the parser failed on is recorded in cfg.unmapped, so that count is
    # exactly the complement.
    ai_blocks = sum(1 for u in cfg.unmapped if u.suggestion)
    result.ai_lines = ai_blocks
    result.unmapped_lines = len(cfg.unmapped) - ai_blocks
    result.rule_lines = max(0, cfg.significant_lines - len(cfg.unmapped))

    return result


# --------------------------------------------------------------------------
# Registration of what exists so far
# --------------------------------------------------------------------------


def _autoregister() -> None:
    """Register every parser/renderer that has been written.

    Import errors are swallowed on purpose: during development half these
    modules do not exist yet, and the harness needs to run regardless.
    """
    try:
        from netmigrate.rules_cisco import parse_cisco

        register_parser(Vendor.CISCO, parse_cisco)
    except ImportError:
        pass

    try:
        from netmigrate.rules_huawei import parse_huawei

        register_parser(Vendor.HUAWEI, parse_huawei)
    except ImportError:
        pass

    try:
        from netmigrate.render_cisco import render_cisco

        register_renderer(Vendor.CISCO, render_cisco)
    except ImportError:
        pass

    try:
        from netmigrate.render_huawei import render_huawei

        register_renderer(Vendor.HUAWEI, render_huawei)
    except ImportError:
        pass


_autoregister()