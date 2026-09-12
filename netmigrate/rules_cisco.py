"""
Cisco IOS-XE front end: block tree -> DeviceConfig.

One handler per top-level keyword. Anything without a handler, or any child
line a handler does not recognise, becomes an UnmappedBlock so it can be
flagged rather than silently dropped.

The OSPF handler is the interesting one: it consumes the whole
``router ospf`` block before producing anything, because the area lives as a
trailing argument on each ``network`` line and has to be regrouped. That is
the class-S case the IR exists for.
"""

from __future__ import annotations

from netmigrate.blocks import ConfigBlock, ParsedConfig, parse_blocks
from netmigrate.ir import (
    DeviceConfig,
    Interface,
    LinkType,
    OspfNetwork,
    OspfProcess,
    StaticRoute,
    UnmappedBlock,
    Vendor,
    Vlan,
)
from netmigrate import transforms as tf


def parse_cisco(text: str) -> DeviceConfig:
    """Parse Cisco IOS-XE configuration text into the IR."""
    parsed = parse_blocks(text)
    return build_cisco_ir(parsed)


def build_cisco_ir(parsed: ParsedConfig) -> DeviceConfig:
    cfg = DeviceConfig(
        source_vendor=Vendor.CISCO,
        total_lines=parsed.total_lines,
        significant_lines=parsed.significant_lines,
    )

    for block in parsed.blocks:
        handler = _TOP_LEVEL.get(block.keyword)
        if handler is None:
            _unmap(cfg, block)
            continue
        handler(cfg, block)

    return cfg


# --------------------------------------------------------------------------
# Unmapped handling
# --------------------------------------------------------------------------


def _unmap(cfg: DeviceConfig, block: ConfigBlock) -> None:
    """Record a block (and its children) as unconvertible."""
    cfg.unmapped.append(
        UnmappedBlock(text=block.text, source_line=block.line_no)
    )
    for child in block.children:
        cfg.unmapped.append(
            UnmappedBlock(text=child.text, source_line=child.line_no)
        )


def _unmap_line(cfg: DeviceConfig, block: ConfigBlock) -> None:
    cfg.unmapped.append(
        UnmappedBlock(text=block.text, source_line=block.line_no)
    )


# --------------------------------------------------------------------------
# hostname
# --------------------------------------------------------------------------


def _handle_hostname(cfg: DeviceConfig, block: ConfigBlock) -> None:
    if len(block.args) != 1:
        _unmap_line(cfg, block)
        return
    cfg.hostname = block.args[0]


# --------------------------------------------------------------------------
# vlan
# --------------------------------------------------------------------------


def _handle_vlan(cfg: DeviceConfig, block: ConfigBlock) -> None:
    """``vlan 10`` with optional ``name`` child. Also ``vlan 10,20,30-35``."""
    if not block.args:
        _unmap_line(cfg, block)
        return

    try:
        ids = tf.parse_vlan_list_cisco(" ".join(block.args))
    except ValueError:
        _unmap(cfg, block)
        return

    name = None
    for child in block.children:
        if child.keyword == "name" and child.args:
            name = " ".join(child.args)
        else:
            _unmap_line(cfg, child)

    # A name only makes sense for a single VLAN. If the line created several,
    # drop the name rather than apply it to all of them.
    for vlan_id in sorted(ids):
        cfg.vlans.append(
            Vlan(
                vlan_id=vlan_id,
                name=name if len(ids) == 1 else None,
                source_line=block.line_no,
            )
        )


# --------------------------------------------------------------------------
# interface
# --------------------------------------------------------------------------


def _handle_interface(cfg: DeviceConfig, block: ConfigBlock) -> None:
    if len(block.args) != 1:
        _unmap(cfg, block)
        return

    try:
        raw_type, number = tf.split_interface_name(block.args[0])
    except ValueError:
        _unmap(cfg, block)
        return

    canonical = tf.canonical_interface_type(raw_type)
    if canonical is None:
        # Unknown interface type (Serial, ATM, Tunnel...). Out of scope.
        _unmap(cfg, block)
        return

    itf = Interface(
        if_type=canonical,
        if_number=number,
        source_line=block.line_no,
    )

    for child in block.children:
        if not _apply_interface_child(itf, child):
            _unmap_line(cfg, child)

    cfg.interfaces.append(itf)


def _apply_interface_child(itf: Interface, child: ConfigBlock) -> bool:
    """Apply one line inside an interface block. False if unrecognised."""
    tokens = child.text.split()
    lowered = [t.lower() for t in tokens]

    # description <text>
    if lowered[0] == "description" and len(tokens) > 1:
        itf.description = " ".join(tokens[1:])
        return True

    # shutdown / no shutdown
    if lowered == ["shutdown"]:
        itf.admin_down = True
        return True
    if lowered == ["no", "shutdown"]:
        itf.admin_down = False
        return True

    # ip address <addr> <mask>
    if lowered[:2] == ["ip", "address"] and len(tokens) >= 4:
        try:
            itf.subnet_mask = tf.normalise_mask(tokens[3])
        except ValueError:
            return False
        itf.ip_address = tokens[2]
        return True

    # switchport ...
    if lowered[0] == "switchport":
        return _apply_switchport(itf, lowered, tokens)

    return False


def _apply_switchport(itf: Interface, lowered: list[str], tokens: list[str]) -> bool:
    # switchport mode access | trunk
    if lowered[1:3] == ["mode", "access"]:
        itf.link_type = LinkType.ACCESS
        return True
    if lowered[1:3] == ["mode", "trunk"]:
        itf.link_type = LinkType.TRUNK
        return True

    # switchport access vlan <id>
    if lowered[1:3] == ["access", "vlan"] and len(tokens) >= 4:
        try:
            itf.access_vlan = int(tokens[3])
        except ValueError:
            return False
        return True

    # switchport trunk native vlan <id>
    if lowered[1:4] == ["trunk", "native", "vlan"] and len(tokens) >= 5:
        try:
            itf.trunk_native = int(tokens[4])
        except ValueError:
            return False
        return True

    # switchport trunk allowed vlan [add|remove] <list>
    if lowered[1:4] == ["trunk", "allowed", "vlan"] and len(tokens) >= 5:
        verb = lowered[4]
        if verb in ("add", "remove"):
            spec = " ".join(tokens[5:])
            if not spec:
                return False
        else:
            verb = "set"
            spec = " ".join(tokens[4:])
        try:
            ids = tf.parse_vlan_list_cisco(spec)
        except ValueError:
            return False
        if verb == "set":
            itf.trunk_allowed = ids
        elif verb == "add":
            itf.trunk_allowed |= ids
        else:
            itf.trunk_allowed -= ids
        return True

    return False


# --------------------------------------------------------------------------
# ip route / ip <other>
# --------------------------------------------------------------------------


def _handle_ip(cfg: DeviceConfig, block: ConfigBlock) -> None:
    tokens = block.text.split()
    lowered = [t.lower() for t in tokens]

    # ip route <prefix> <mask> <next-hop> [distance]
    if lowered[:2] == ["ip", "route"] and len(tokens) >= 5:
        try:
            mask = tf.normalise_mask(tokens[3])
        except ValueError:
            _unmap_line(cfg, block)
            return

        preference = None
        if len(tokens) >= 6:
            try:
                preference = int(tokens[5])
            except ValueError:
                # Trailing token that is not a distance (name, tag, track...)
                _unmap_line(cfg, block)
                return

        cfg.static_routes.append(
            StaticRoute(
                prefix=tokens[2],
                mask=mask,
                next_hop=tokens[4],
                preference=preference,
                source_line=block.line_no,
            )
        )
        return

    # Everything else under 'ip' is out of scope (ip nbar, ip sla, ip domain...)
    _unmap(cfg, block)


# --------------------------------------------------------------------------
# router ospf -- class S
# --------------------------------------------------------------------------


def _handle_router(cfg: DeviceConfig, block: ConfigBlock) -> None:
    if len(block.args) < 2 or block.args[0].lower() != "ospf":
        # BGP, EIGRP, RIP, IS-IS all out of scope.
        _unmap(cfg, block)
        return

    try:
        process_id = int(block.args[1])
    except ValueError:
        _unmap(cfg, block)
        return

    if cfg.ospf is not None:
        # Multi-process OSPF is out of scope (proposal 2.3.2.3). Keep the
        # first, flag the rest.
        _unmap(cfg, block)
        return

    ospf = OspfProcess(process_id=process_id, source_line=block.line_no)

    for child in block.children:
        tokens = child.text.split()
        lowered = [t.lower() for t in tokens]

        # router-id <id>
        if lowered[0] == "router-id" and len(tokens) == 2:
            ospf.router_id = tokens[1]
            continue

        # network <addr> <wildcard> area <area-id>
        if (
            lowered[0] == "network"
            and len(tokens) == 5
            and lowered[3] == "area"
        ):
            try:
                area_id = tf.parse_area_id(tokens[4])
            except ValueError:
                _unmap_line(cfg, child)
                continue
            ospf.add_network(
                area_id,
                OspfNetwork(
                    address=tokens[1],
                    wildcard=tokens[2],
                    source_line=child.line_no,
                ),
            )
            continue

        # passive-interface, redistribute, area authentication, etc.
        _unmap_line(cfg, child)

    cfg.ospf = ospf


# --------------------------------------------------------------------------
# Dispatch table
# --------------------------------------------------------------------------

_TOP_LEVEL = {
    "hostname": _handle_hostname,
    "vlan": _handle_vlan,
    "interface": _handle_interface,
    "ip": _handle_ip,
    "router": _handle_router,
}