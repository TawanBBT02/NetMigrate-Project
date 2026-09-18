"""
Cisco IOS-XE back end: DeviceConfig -> output lines.

The OSPF renderer here performs the inverse of the Huawei one: areas stop
being parent blocks and collapse back into a trailing argument on each
``network`` line, and the router-id drops from the process declaration down
into a child line. Same IR, opposite structure -- which is the point.
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

COMMENT = "!"
REVIEW_TAG = "[NETMIGRATE-REVIEW]"
AI_TAG = "[NETMIGRATE-AI-REVIEW]"


def render_cisco(cfg: DeviceConfig) -> list[OutputLine]:
    """Render a DeviceConfig as Cisco IOS-XE configuration."""
    out: list[OutputLine] = []

    _separator(out)

    if cfg.hostname is not None:
        _rule(out, f"hostname {cfg.hostname}", "system.hostname", cfg)
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

    _generated(out, "end")

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
    out.append(OutputLine(text=text, provenance=Provenance.GENERATED))


def _separator(out: list[OutputLine]) -> None:
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
    if_type = tf.render_interface_type(itf.if_type, "cisco")
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
        _rule(out, "switchport mode access", "port.link-type", itf, indent=1)
        if itf.access_vlan is not None:
            _rule(out, f"switchport access vlan {itf.access_vlan}",
                  "port.access-vlan", itf, indent=1)

    elif itf.link_type is LinkType.TRUNK:
        _rule(out, "switchport mode trunk", "port.link-type", itf, indent=1)
        if itf.trunk_allowed:
            vlan_list = tf.render_vlan_list_cisco(itf.trunk_allowed)
            _rule(out, f"switchport trunk allowed vlan {vlan_list}",
                  "port.trunk-allowed", itf, indent=1)
        if itf.trunk_native is not None:
            _rule(out, f"switchport trunk native vlan {itf.trunk_native}",
                  "port.trunk-native", itf, indent=1)

    if itf.admin_down is True:
        _rule(out, "shutdown", "interface.shutdown", itf, indent=1)
    elif itf.admin_down is False:
        _rule(out, "no shutdown", "interface.shutdown", itf, indent=1)


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
        f"(VRP preference 60 vs Cisco administrative distance 1), so relative "
        f"precedence against dynamic routes may change. Verify intended "
        f"route selection on the target device.",
        None,
    )


def _render_static_route(out: list[OutputLine], route: StaticRoute) -> None:
    next_hop = route.next_hop
    try:
        raw_type, number = tf.split_interface_name(next_hop)
        canonical = tf.canonical_interface_type(raw_type)
    except ValueError:
        canonical = None
    if canonical is not None:
        next_hop = tf.render_interface_type(canonical, "cisco") + number

    text = f"ip route {route.prefix} {route.mask} {next_hop}"
    if route.preference is not None:
        # Cisco takes administrative distance as a bare trailing integer.
        text += f" {route.preference}"
    _rule(out, text, "route.static", route)


# --------------------------------------------------------------------------
# OSPF -- class S, inverse of the Huawei renderer
# --------------------------------------------------------------------------


def _render_ospf(out: list[OutputLine], ospf: OspfProcess) -> None:
    _rule(out, f"router ospf {ospf.process_id}", "ospf.process", ospf)

    # router-id demotes from the process line to a child line.
    if ospf.router_id:
        _rule(out, f"router-id {ospf.router_id}", "ospf.router-id",
              ospf, indent=1)

    # Areas stop being blocks: each network carries its area as a trailing
    # argument, rendered as a plain integer rather than dotted-decimal.
    for area_id in sorted(ospf.areas):
        for net in ospf.areas[area_id]:
            _rule(
                out,
                f"network {net.address} {net.wildcard} "
                f"area {tf.render_area_id_int(area_id)}",
                "ospf.network",
                net,
                indent=1,
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
                for line in tf.credential_guidance("cisco").splitlines():
                    out.append(
                        OutputLine(
                            text=f"{COMMENT}   {line}",
                            provenance=Provenance.UNMAPPED,
                            source_line=block.source_line,
                            needs_review=True,
                        )
                    )
