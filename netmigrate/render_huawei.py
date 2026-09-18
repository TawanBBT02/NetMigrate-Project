"""
Huawei VRP back end: DeviceConfig -> output lines.

Each emitted line carries its provenance and the id of the rule that produced
it, so the diff view can colour per line and the audit history can explain
any line after the fact.

The OSPF renderer is where the intermediate representation earns its place.
It walks ``ospf.areas`` -- a mapping of area to networks -- and emits nested
``area`` blocks with dotted-decimal identifiers. A line-by-line translator
cannot do this, because the area lives as a trailing argument on each Cisco
``network`` line and the grouping does not exist until the whole block has
been read.
"""

from __future__ import annotations

from netmigrate.ir import (
    DeviceConfig,
    Interface,
    LinkType,
    OspfProcess,
    OutputLine,
    Provenance,
    StaticRoute,
    UnmappedBlock,
    Vlan,
)
from netmigrate import transforms as tf

COMMENT = "#"
REVIEW_TAG = "[NETMIGRATE-REVIEW]"
AI_TAG = "[NETMIGRATE-AI-REVIEW]"


def render_huawei(cfg: DeviceConfig) -> list[OutputLine]:
    """Render a DeviceConfig as Huawei VRP configuration."""
    out: list[OutputLine] = []

    _separator(out)

    if cfg.hostname is not None:
        _rule(out, f"sysname {cfg.hostname}", "system.hostname", cfg)
        _separator(out)

    for vlan in cfg.vlans:
        _render_vlan(out, vlan)
        _separator(out)

    for itf in cfg.interfaces:
        _render_interface(out, itf)
        _separator(out)

    if cfg.ospf is not None:
        _render_ospf(out, cfg.ospf)
        _separator(out)

    if any(r.preference is None for r in cfg.static_routes):
        _render_preference_warning(out)
    for route in cfg.static_routes:
        _render_static_route(out, route)
    if cfg.static_routes:
        _separator(out)

    if cfg.unmapped:
        _render_unmapped(out, cfg.unmapped)
        _separator(out)

    _generated(out, "return")

    return out


# --------------------------------------------------------------------------
# Line emitters
# --------------------------------------------------------------------------


def _rule(
    out: list[OutputLine],
    text: str,
    rule_id: str,
    src: object = None,
    indent: int = 0,
    needs_review: bool = False,
) -> None:
    """Emit a line produced by a deterministic rule."""
    out.append(
        OutputLine(
            text=" " * indent + text,
            provenance=Provenance.RULE,
            source_line=getattr(src, "source_line", None),
            rule_id=rule_id,
            needs_review=needs_review,
        )
    )


def _generated(out: list[OutputLine], text: str) -> None:
    """Emit a line that corresponds to no source line. Excluded from metrics."""
    out.append(OutputLine(text=text, provenance=Provenance.GENERATED))


def _separator(out: list[OutputLine]) -> None:
    # Avoid two separators in a row, which happens when a section is empty.
    if out and out[-1].text == COMMENT:
        return
    _generated(out, COMMENT)


def _review_comment(out: list[OutputLine], text: str, src_line: int | None) -> None:
    out.append(
        OutputLine(
            text=f"{COMMENT} {text}",
            provenance=Provenance.GENERATED,
            source_line=src_line,
            needs_review=True,
        )
    )


# --------------------------------------------------------------------------
# VLAN
# --------------------------------------------------------------------------


def _render_vlan(out: list[OutputLine], vlan: Vlan) -> None:
    _rule(out, f"vlan {vlan.vlan_id}", "vlan.create", vlan)
    if vlan.name:
        _rule(out, f"name {vlan.name}", "vlan.name", vlan, indent=1)


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------


def _render_interface(out: list[OutputLine], itf: Interface) -> None:
    if_type = tf.render_interface_type(itf.if_type, "huawei")
    review = tf.slot_needs_review(itf.if_number, itf.if_type)

    if review:
        _review_comment(
            out,
            f"{REVIEW_TAG} interface {if_type}{itf.if_number} has a non-zero "
            f"slot number; verify this port exists on the target device",
            itf.source_line,
        )

    _rule(
        out,
        f"interface {if_type}{itf.if_number}",
        "interface.name",
        itf,
        needs_review=review,
    )

    if itf.description:
        _rule(out, f"description {itf.description}", "interface.description",
              itf, indent=1)

    if itf.ip_address and itf.subnet_mask:
        _rule(
            out,
            f"ip address {itf.ip_address} {itf.subnet_mask}",
            "interface.ip",
            itf,
            indent=1,
        )

    if itf.link_type is LinkType.ACCESS:
        _rule(out, "port link-type access", "port.link-type", itf, indent=1)
        if itf.access_vlan is not None:
            _rule(out, f"port default vlan {itf.access_vlan}",
                  "port.access-vlan", itf, indent=1)

    elif itf.link_type is LinkType.TRUNK:
        _rule(out, "port link-type trunk", "port.link-type", itf, indent=1)
        if itf.trunk_allowed:
            # VRP permits at most 40 elements per allow-pass command
            # (&<1-40> in the documented syntax), so a long discrete list
            # needs several commands. Repeated lines accumulate on the
            # device, and our parser accumulates them too.
            for vlan_list in tf.split_vlan_list_huawei(itf.trunk_allowed):
                _rule(out, f"port trunk allow-pass vlan {vlan_list}",
                      "port.trunk-allowed", itf, indent=1)
        if itf.trunk_native is not None:
            _rule(out, f"port trunk pvid vlan {itf.trunk_native}",
                  "port.trunk-native", itf, indent=1)

    # Tri-state: None means the source config was silent, so stay silent.
    if itf.admin_down is True:
        _rule(out, "shutdown", "interface.shutdown", itf, indent=1)
    elif itf.admin_down is False:
        _rule(out, "undo shutdown", "interface.shutdown", itf, indent=1)


# --------------------------------------------------------------------------
# Static routes
# --------------------------------------------------------------------------


def _render_preference_warning(out: list[OutputLine]) -> None:
    """Warn once when any static route relies on the vendor default.

    The defaults are not equivalent: a Cisco static route defaults to
    administrative distance 1, a VRP static route to preference 60. An
    unqualified static route therefore has a different precedence relative
    to dynamic routing protocols on each platform, and the syntax-level
    translation cannot express that. Emitted once per configuration rather
    than per route, to stay readable.
    """
    _review_comment(
        out,
        f"{REVIEW_TAG} one or more static routes below specify no "
        f"preference/distance. Defaults differ between vendors "
        f"(Cisco administrative distance 1 vs VRP preference 60), so relative "
        f"precedence against dynamic routes may change. Verify intended "
        f"route selection on the target device.",
        None,
    )


def _render_static_route(out: list[OutputLine], route: StaticRoute) -> None:
    next_hop = route.next_hop
    # An interface next hop needs its type token translated.
    canonical = None
    try:
        raw_type, number = tf.split_interface_name(next_hop)
        canonical = tf.canonical_interface_type(raw_type)
    except ValueError:
        canonical = None
    if canonical is not None:
        next_hop = tf.render_interface_type(canonical, "huawei") + number

    text = f"ip route-static {route.prefix} {route.mask} {next_hop}"
    if route.preference is not None:
        # Cisco takes a bare integer; VRP requires the explicit keyword.
        text += f" preference {route.preference}"
    _rule(out, text, "route.static", route)


# --------------------------------------------------------------------------
# OSPF -- the class S transformation
# --------------------------------------------------------------------------


def _render_ospf(out: list[OutputLine], ospf: OspfProcess) -> None:
    # router-id promotes from a child line onto the process declaration.
    header = f"ospf {ospf.process_id}"
    if ospf.router_id:
        header += f" router-id {ospf.router_id}"
    _rule(out, header, "ospf.process", ospf)

    # Areas become parent blocks, with networks grouped beneath them. Cisco
    # carried the area as a trailing argument on each network line; here the
    # grouping is the structure.
    for area_id in sorted(ospf.areas):
        _rule(
            out,
            f"area {tf.render_area_id_dotted(area_id)}",
            "ospf.area",
            ospf,
            indent=1,
        )
        for net in ospf.areas[area_id]:
            _rule(
                out,
                f"network {net.address} {net.wildcard}",
                "ospf.network",
                net,
                indent=2,
            )


# --------------------------------------------------------------------------
# Unmapped constructs
# --------------------------------------------------------------------------


def _render_unmapped(out: list[OutputLine], blocks: list[UnmappedBlock]) -> None:
    _review_comment(
        out,
        f"{REVIEW_TAG} {len(blocks)} line(s) had no translation rule and "
        f"require manual review",
        None,
    )

    for block in blocks:
        if block.suggestion:
            # AI output never enters the uncommented config body.
            out.append(
                OutputLine(
                    text=f"{COMMENT} {AI_TAG} source line {block.source_line}: "
                         f"{block.text}",
                    provenance=Provenance.AI,
                    source_line=block.source_line,
                    needs_review=True,
                )
            )
            for suggested in block.suggestion.splitlines():
                out.append(
                    OutputLine(
                        text=f"{COMMENT}   suggested: {suggested}",
                        provenance=Provenance.AI,
                        source_line=block.source_line,
                        needs_review=True,
                    )
                )
            if block.rationale:
                out.append(
                    OutputLine(
                        text=f"{COMMENT}   rationale: {block.rationale}",
                        provenance=Provenance.AI,
                        source_line=block.source_line,
                        needs_review=True,
                    )
                )
        else:
            out.append(
                OutputLine(
                    text=f"{COMMENT} {REVIEW_TAG} source line "
                         f"{block.source_line}: {block.text}",
                    provenance=Provenance.UNMAPPED,
                    source_line=block.source_line,
                    needs_review=True,
                )
            )
            # Credential lines get structural guidance rather than a bare
            # review tag: password hashes are one-way and vendor-specific,
            # so there is nothing to translate and the engine says so
            # explicitly instead of leaving the engineer to work it out.
            if block.category == "credential":
                # Three outcomes: a hashed value cannot be converted at all,
                # a plaintext value could be but is deliberately withheld,
                # and a line with no secret in it (aaa, line vty) gets no
                # password guidance because that would be meaningless.
                kind = tf.classify_credential(block.text)
                guidance = tf.credential_guidance("huawei", kind)
                for line in guidance.splitlines() if guidance else []:
                    out.append(
                        OutputLine(
                            text=f"{COMMENT}   {line}",
                            provenance=Provenance.UNMAPPED,
                            source_line=block.source_line,
                            needs_review=True,
                        )
                    )
