"""
Pure value transforms shared by several rules (class T in the mapping spec).

These are the highest-risk functions in the project: a wrong VLAN list
silently isolates a network segment. They take no dependencies and are tested
independently of the rules that call them.
"""

from __future__ import annotations

import ipaddress
import re

# --------------------------------------------------------------------------
# VLAN lists
#   Cisco:  comma-separated, hyphen ranges      "10,20,30-35"
#   Huawei: space-separated, 'to' ranges        "10 20 30 to 35"
# --------------------------------------------------------------------------

VLAN_MIN, VLAN_MAX = 1, 4094


def parse_vlan_list_cisco(spec: str) -> set[int]:
    """Parse Cisco VLAN list notation into a set of ids."""
    ids: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            ids.update(range(lo, hi + 1))
        else:
            ids.add(int(part))
    _validate(ids)
    return ids


def parse_vlan_list_huawei(spec: str) -> set[int]:
    """Parse Huawei VLAN list notation into a set of ids."""
    tokens = spec.split()
    ids: set[int] = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.lower() == "to":
            # "<lo> to <hi>" -- lo was the previous token
            if i == 0 or i + 1 >= len(tokens):
                raise ValueError(f"malformed Huawei VLAN range near 'to': {spec!r}")
            lo = int(tokens[i - 1])
            hi = int(tokens[i + 1])
            if lo > hi:
                lo, hi = hi, lo
            ids.update(range(lo, hi + 1))
            i += 2
            continue
        ids.add(int(tok))
        i += 1
    _validate(ids)
    return ids


def _validate(ids: set[int]) -> None:
    bad = [v for v in ids if not (VLAN_MIN <= v <= VLAN_MAX)]
    if bad:
        raise ValueError(f"VLAN id(s) out of range {VLAN_MIN}-{VLAN_MAX}: {sorted(bad)}")


def _collapse(ids: set[int]) -> list[tuple[int, int]]:
    """Group sorted ids into (lo, hi) runs."""
    if not ids:
        return []
    runs: list[tuple[int, int]] = []
    ordered = sorted(ids)
    lo = prev = ordered[0]
    for v in ordered[1:]:
        if v == prev + 1:
            prev = v
            continue
        runs.append((lo, prev))
        lo = prev = v
    runs.append((lo, prev))
    return runs


def render_vlan_list_cisco(ids: set[int]) -> str:
    """Render as Cisco notation. Runs of 2 are written out, not ranged."""
    parts = []
    for lo, hi in _collapse(ids):
        if lo == hi:
            parts.append(str(lo))
        elif hi - lo == 1:
            parts.extend([str(lo), str(hi)])
        else:
            parts.append(f"{lo}-{hi}")
    return ",".join(parts)


def render_vlan_list_huawei(ids: set[int]) -> str:
    """Render as Huawei notation. Runs of 2 are written out, not ranged."""
    parts = []
    for lo, hi in _collapse(ids):
        if lo == hi:
            parts.append(str(lo))
        elif hi - lo == 1:
            parts.extend([str(lo), str(hi)])
        else:
            parts.append(f"{lo} to {hi}")
    return " ".join(parts)


# --------------------------------------------------------------------------
# OSPF area identifiers
#   Cisco accepts both "area 0" and "area 0.0.0.0"
#   Huawei requires dotted-decimal: "area 0.0.0.0"
#   Note 0.0.0.1 is area 1, NOT area 1.0.0.0 -- it is a 32-bit int in IPv4
#   notation, big-endian.
# --------------------------------------------------------------------------


def parse_area_id(spec: str) -> int:
    """Accept either integer or dotted-decimal form, return an integer."""
    spec = spec.strip()
    if "." in spec:
        return int(ipaddress.IPv4Address(spec))
    value = int(spec)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"area id out of range: {spec!r}")
    return value


def render_area_id_dotted(area_id: int) -> str:
    """Render as dotted-decimal, for Huawei."""
    return str(ipaddress.IPv4Address(area_id))


def render_area_id_int(area_id: int) -> str:
    """Render as a plain integer, for Cisco."""
    return str(area_id)


# --------------------------------------------------------------------------
# Subnet masks
#   Cisco emits dotted mask. Huawei accepts dotted mask or prefix length.
#   We accept both on input and emit dotted mask for consistency.
# --------------------------------------------------------------------------


def mask_to_prefix_len(mask: str) -> int:
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def prefix_len_to_mask(prefix_len: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").netmask)


def normalise_mask(token: str) -> str:
    """Turn either '255.255.255.0' or '24' into '255.255.255.0'."""
    token = token.strip()
    if "." in token:
        # Validate it is a real mask, not an arbitrary address.
        mask_to_prefix_len(token)
        return token
    return prefix_len_to_mask(int(token))


# --------------------------------------------------------------------------
# Interface type names
# --------------------------------------------------------------------------

# Canonical type -> (cisco form, huawei form)
INTERFACE_TYPES: dict[str, tuple[str, str]] = {
    "gigabit": ("GigabitEthernet", "GE"),
    "tengigabit": ("TenGigabitEthernet", "XGE"),
    "fast": ("FastEthernet", "Ethernet"),
    "loopback": ("Loopback", "LoopBack"),
    "vlan": ("Vlan", "Vlanif"),
    "portchannel": ("Port-channel", "Eth-Trunk"),
}

# Recognised spellings (including abbreviations) -> canonical key.
# Longest match wins, so order matters when scanning.
_ALIASES: dict[str, str] = {
    # gigabit
    "gigabitethernet": "gigabit", "gigabit": "gigabit", "gi": "gigabit", "ge": "gigabit",
    # ten gigabit -- must be checked before 'te' / 'gigabit'
    "tengigabitethernet": "tengigabit", "tengige": "tengigabit",
    "xgigabitethernet": "tengigabit", "xge": "tengigabit", "te": "tengigabit",
    # fast
    "fastethernet": "fast", "fa": "fast", "ethernet": "fast", "eth": "fast",
    # loopback
    "loopback": "loopback", "lo": "loopback",
    # vlan interface
    "vlanif": "vlan", "vlan": "vlan", "vl": "vlan",
    # aggregate
    "port-channel": "portchannel", "portchannel": "portchannel",
    "po": "portchannel", "eth-trunk": "portchannel",
}

_IF_SPLIT = re.compile(r"^([A-Za-z][A-Za-z\-]*)\s*([\d/.:]*)$")


def split_interface_name(name: str) -> tuple[str, str]:
    """Split 'GigabitEthernet0/0/1' into ('GigabitEthernet', '0/0/1')."""
    m = _IF_SPLIT.match(name.strip())
    if not m:
        raise ValueError(f"unrecognised interface name: {name!r}")
    return m.group(1), m.group(2)


def canonical_interface_type(type_token: str) -> str | None:
    """Map any recognised spelling to a canonical key, or None if unknown."""
    return _ALIASES.get(type_token.strip().lower().replace(" ", ""))


def render_interface_type(canonical: str, vendor: str) -> str:
    """Render a canonical type key in the given vendor's spelling.

    ``vendor`` is 'cisco' or 'huawei'.
    """
    if canonical not in INTERFACE_TYPES:
        raise ValueError(f"unknown canonical interface type: {canonical!r}")
    cisco, huawei = INTERFACE_TYPES[canonical]
    return cisco if vendor == "cisco" else huawei


# Logical interfaces have no physical slot -- their number is an index or a
# VLAN id, so the slot-mismatch warning does not apply to them.
LOGICAL_TYPES = {"loopback", "vlan", "portchannel"}


def slot_needs_review(if_number: str, canonical_type: str | None = None) -> bool:
    """True if the numeric portion has a non-zero leading slot.

    Port numbering is not algorithmically translatable (proposal 2.3.2.4), so
    a non-zero slot means the target device may not have that port.

    Two guards against false warnings:

    * Logical interfaces (Loopback, Vlanif, Eth-Trunk) are exempt -- their
      number is an index, not a slot. ``Vlanif10`` is VLAN 10, not slot 10.
    * Slot/port notation requires a separator. A bare number is an index, so
      ``GigabitEthernet1`` is not treated as slot 1.
    """
    if canonical_type in LOGICAL_TYPES:
        return False
    if "/" not in if_number:
        return False
    first = if_number.split("/")[0]
    try:
        return int(first) != 0
    except ValueError:
        return False
