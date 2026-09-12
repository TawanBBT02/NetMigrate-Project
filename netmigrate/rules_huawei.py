"""
Huawei VRP front end: block tree -> DeviceConfig.

Mirrors rules_cisco.py in structure. The differences worth noting:

* ``vlan batch 10 20 30`` creates several VLANs in one line and has no Cisco
  equivalent as a single statement, so it expands into separate Vlan objects.
* ``ospf 1 router-id 1.1.1.1`` carries the router-id on the process line,
  and areas are already parent blocks -- so the class-S work here is the
  reverse: flattening nested areas back into the IR's area mapping.
* ``ip address`` accepts either a dotted mask or a prefix length.
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


def parse_huawei(text: str) -> DeviceConfig:
    """Parse Huawei VRP configuration text into the IR."""
    return build_huawei_ir(parse_blocks(text))


def build_huawei_ir(parsed: ParsedConfig) -> DeviceConfig:
    cfg = DeviceConfig(
        source_vendor=Vendor.HUAWEI,
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
    cfg.unmapped.append(UnmappedBlock(text=block.text, source_line=block.line_no))
    for child in block.walk():
        if child is block:
            continue
        cfg.unmapped.append(
            UnmappedBlock(text=child.text, source_line=child.line_no)
        )


def _unmap_line(cfg: DeviceConfig, block: ConfigBlock) -> None:
    cfg.unmapped.append(UnmappedBlock(text=block.text, source_line=block.line_no))


# --------------------------------------------------------------------------
# sysname
# --------------------------------------------------------------------------


def _handle_sysname(cfg: DeviceConfig, block: ConfigBlock) -> None:
    if len(block.args) != 1:
        _unmap_line(cfg, block)
        return
    cfg.hostname = block.args[0]


# --------------------------------------------------------------------------
# vlan / vlan batch
# --------------------------------------------------------------------------


def _handle_vlan(cfg: DeviceConfig, block: ConfigBlock) -> None:
    if not block.args:
        _unmap_line(cfg, block)
        return

    args = block.args
    batch = args[0].lower() == "batch"
    spec = " ".join(args[1:] if batch else args)

    if not spec:
        _unmap_line(cfg, block)
        return

    try:
        ids = tf.parse_vlan_list_huawei(spec)
    except ValueError:
        _unmap(cfg, block)
        return

    name = None
    for child in block.children:
        if child.keyword == "name" and child.args:
            name = " ".join(child.args)
        else:
            _unmap_line(cfg, child)

    single = len(ids) == 1 and not batch
    for vlan_id in sorted(ids):
        existing = next((v for v in cfg.vlans if v.vlan_id == vlan_id), None)
        if existing is not None:
            # `vlan batch 10 20` followed by `vlan 10 / name SALES` is normal
            # VRP output. Merge rather than duplicate.
            if single and name:
                existing.name = name
            continue
        cfg.vlans.append(
            Vlan(
                vlan_id=vlan_id,
                name=name if single else None,
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
        _unmap(cfg, block)
        return

    itf = Interface(if_type=canonical, if_number=number, source_line=block.line_no)

    for child in block.children:
        if not _apply_interface_child(itf, child):
            _unmap_line(cfg, child)

    cfg.interfaces.append(itf)


def _apply_interface_child(itf: Interface, child: ConfigBlock) -> bool:
    tokens = child.text.split()
    lowered = [t.lower() for t in tokens]

    if lowered[0] == "description" and len(tokens) > 1:
        itf.description = " ".join(tokens[1:])
        return True

    if lowered == ["shutdown"]:
        itf.admin_down = True
        return True
    if lowered == ["undo", "shutdown"]:
        itf.admin_down = False
        return True

    # ip address <addr> <mask|prefixlen>
    if lowered[:2] == ["ip", "address"] and len(tokens) >= 4:
        try:
            itf.subnet_mask = tf.normalise_mask(tokens[3])
        except ValueError:
            return False
        itf.ip_address = tokens[2]
        return True

    if lowered[0] == "port":
        return _apply_port(itf, lowered, tokens)

    return False


def _apply_port(itf: Interface, lowered: list[str], tokens: list[str]) -> bool:
    # port link-type access | trunk
    if lowered[1:2] == ["link-type"] and len(tokens) >= 3:
        if lowered[2] == "access":
            itf.link_type = LinkType.ACCESS
            return True
        if lowered[2] == "trunk":
            itf.link_type = LinkType.TRUNK
            return True
        # hybrid has no Cisco equivalent in scope
        return False

    # port default vlan <id>
    if lowered[1:3] == ["default", "vlan"] and len(tokens) >= 4:
        try:
            itf.access_vlan = int(tokens[3])
        except ValueError:
            return False
        return True

    # port trunk pvid vlan <id>
    if lowered[1:4] == ["trunk", "pvid", "vlan"] and len(tokens) >= 5:
        try:
            itf.trunk_native = int(tokens[4])
        except ValueError:
            return False
        return True

    # port trunk allow-pass vlan <list>
    if lowered[1:4] == ["trunk", "allow-pass", "vlan"] and len(tokens) >= 5:
        spec = " ".join(tokens[4:])
        if spec.lower() == "all":
            # 'all' is not expressible as an explicit Cisco list in scope
            return False
        try:
            ids = tf.parse_vlan_list_huawei(spec)
        except ValueError:
            return False
        # Repeated allow-pass lines accumulate, as they do on the device.
        itf.trunk_allowed |= ids
        return True

    return False


# --------------------------------------------------------------------------
# ip route-static
# --------------------------------------------------------------------------


def _handle_ip(cfg: DeviceConfig, block: ConfigBlock) -> None:
    tokens = block.text.split()
    lowered = [t.lower() for t in tokens]

    if lowered[:2] == ["ip", "route-static"] and len(tokens) >= 5:
        try:
            mask = tf.normalise_mask(tokens[3])
        except ValueError:
            _unmap_line(cfg, block)
            return

        preference = None
        rest = tokens[5:]
        if rest:
            # VRP requires the explicit keyword; anything else is out of scope.
            if len(rest) == 2 and rest[0].lower() == "preference":
                try:
                    preference = int(rest[1])
                except ValueError:
                    _unmap_line(cfg, block)
                    return
            else:
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

    _unmap(cfg, block)


# --------------------------------------------------------------------------
# ospf -- class S, flattening nested areas into the IR mapping
# --------------------------------------------------------------------------


def _handle_ospf(cfg: DeviceConfig, block: ConfigBlock) -> None:
    if not block.args:
        _unmap(cfg, block)
        return

    try:
        process_id = int(block.args[0])
    except ValueError:
        _unmap(cfg, block)
        return

    if cfg.ospf is not None:
        _unmap(cfg, block)
        return

    ospf = OspfProcess(process_id=process_id, source_line=block.line_no)

    # router-id rides on the process line here, unlike Cisco.
    rest = [a.lower() for a in block.args[1:]]
    if len(rest) >= 2 and rest[0] == "router-id":
        ospf.router_id = block.args[2]
    elif rest:
        _unmap_line(cfg, block)

    for child in block.children:
        tokens = child.text.split()
        lowered = [t.lower() for t in tokens]

        if lowered[0] == "area" and len(tokens) == 2:
            try:
                area_id = tf.parse_area_id(tokens[1])
            except ValueError:
                _unmap(cfg, child)
                continue

            ospf.areas.setdefault(area_id, [])

            for net_block in child.children:
                net_tokens = net_block.text.split()
                if net_tokens[0].lower() == "network" and len(net_tokens) == 3:
                    ospf.add_network(
                        area_id,
                        OspfNetwork(
                            address=net_tokens[1],
                            wildcard=net_tokens[2],
                            source_line=net_block.line_no,
                        ),
                    )
                else:
                    _unmap_line(cfg, net_block)
            continue

        if lowered[0] == "router-id" and len(tokens) == 2:
            ospf.router_id = tokens[1]
            continue

        _unmap_line(cfg, child)

    cfg.ospf = ospf


# --------------------------------------------------------------------------
# Dispatch table
# --------------------------------------------------------------------------

_TOP_LEVEL = {
    "sysname": _handle_sysname,
    "vlan": _handle_vlan,
    "interface": _handle_interface,
    "ip": _handle_ip,
    "ospf": _handle_ospf,
}
