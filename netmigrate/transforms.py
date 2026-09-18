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


# Huawei documents the trunk allow-pass syntax as:
#   port trunk allow-pass vlan { { vlan-id1 [ to vlan-id2 ] } &<1-40> | all }
# The &<1-40> is a repetition limit: at most 40 elements per command, where a
# range counts as ONE element. A trunk with many discrete non-contiguous VLANs
# therefore needs several commands. Repeated allow-pass lines accumulate on
# the device, and our Huawei parser accumulates them too, so splitting is
# safe in both directions.
HUAWEI_VLAN_ELEMENTS_PER_COMMAND = 40


def split_vlan_list_huawei(
    ids: set[int],
    limit: int = HUAWEI_VLAN_ELEMENTS_PER_COMMAND,
) -> list[str]:
    """Render a VLAN set as one or more Huawei VLAN list strings.

    Splits on *element* count, not VLAN count: ``10 to 200`` is a single
    element even though it covers 191 VLANs. Returns an empty list for an
    empty set.
    """
    runs = _collapse(ids)
    if not runs:
        return []

    out: list[str] = []
    for start in range(0, len(runs), limit):
        group = runs[start:start + limit]
        parts = []
        for lo, hi in group:
            if lo == hi:
                parts.append(str(lo))
            elif hi - lo == 1:
                parts.extend([str(lo), str(hi)])
            else:
                parts.append(f"{lo} to {hi}")
        out.append(" ".join(parts))
    return out


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
    "null": ("Null", "NULL"),
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
    # Null interface: Cisco spells it Null0, Huawei NULL0. Appears as a
    # static-route next hop for discard routes.
    "null": "null", "null0": "null", "nu": "null",
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


# --------------------------------------------------------------------------
# Credential detection
# --------------------------------------------------------------------------

# Password material cannot be converted between vendors. Cisco type 5 is
# salted MD5, type 8 PBKDF2-SHA256, type 9 scrypt; Huawei
# irreversible-cipher uses its own scheme. These are one-way functions with
# different algorithms, salts and encodings -- there is no transformation
# from one to the other without the plaintext, which a configuration file
# does not contain.
#
# So the engine never attempts conversion. It detects credential lines and
# emits structural guidance with an explicit manual-entry marker, which is
# the only honest behaviour. See proposal Chapter 5.

CREDENTIAL_PATTERNS = (
    # Cisco
    "enable secret", "enable password", "username ", "password ",
    "secret ", "key-string", "authentication-key", "md5 ",
    # Huawei
    "local-user", "irreversible-cipher", "cipher ", "simple ",
    "authentication-mode", "aaa",
)

# Tokens that indicate the line actually carries a secret VALUE, as opposed to
# merely configuring the credential subsystem. `aaa`, `line vty 0 4` and
# `authentication-mode aaa` match CREDENTIAL_PATTERNS but hold no secret, so
# emitting password guidance for them would be nonsense.
VALUE_BEARING_TOKENS = (
    "secret", "password", "cipher", "key-string",
    "authentication-key", "md5",
)

# Markers showing the credential VALUE is already a one-way digest.
#   Cisco:  type 5 salted MD5, type 8 PBKDF2-SHA256, type 9 scrypt, type 7
#           reversible obfuscation
#   Huawei: irreversible-cipher storage, %^%# wrapped cipher text
HASH_MARKERS = (
    "secret 5 ", "secret 8 ", "secret 9 ", "secret 4 ",
    "password 5 ", "password 7 ", "password 8 ", "password 9 ",
    "irreversible-cipher", "%^%#",
)

# Any dollar-delimited prefix, not just formats we recognise. An
# unrecognised hash format must be treated as hashed: telling the user "an
# equivalent exists" when they actually hold an unconvertible digest is the
# damaging direction to be wrong in.
_DOLLAR_HASH = re.compile(r"\$[^$\s]{1,12}\$")

# Credential classifications returned by classify_credential().
CRED_HASHED = "hashed"
CRED_PLAINTEXT = "plaintext"
CRED_NO_VALUE = "no-value"

_HASHED_GUIDANCE = {
    "cisco": (
        "Password hashes cannot be converted between vendors (one-way,\n"
        "vendor-specific algorithms). Set credentials manually on the target:\n"
        "  privilege-escalation password (from Huawei super password):\n"
        "    enable secret <PASSWORD>\n"
        "  user account (from Huawei local-user):\n"
        "    username <NAME> privilege 15 secret <PASSWORD>"
    ),
    "huawei": (
        "Password hashes cannot be converted between vendors (one-way,\n"
        "vendor-specific algorithms). Set credentials manually on the target:\n"
        "  privilege-escalation password (from Cisco enable secret):\n"
        "    super password level 15 cipher <PASSWORD>\n"
        "  user account (from Cisco username ... secret):\n"
        "    aaa\n"
        "     local-user <NAME> password irreversible-cipher <PASSWORD>\n"
        "     local-user <NAME> privilege level 15"
    ),
}

# Both target forms are listed rather than guessing which applies. Detecting
# the source command type is more code and another thing that can be subtly
# wrong; listing both with labels cannot be wrong, and the operator knows
# which they need.
_PLAINTEXT_GUIDANCE = {
    "cisco": (
        "This value appears to be plaintext, so an equivalent credential\n"
        "exists on the target -- but it is NOT applied automatically:\n"
        "credentials must be set deliberately by an operator, and this\n"
        "generated file may be shared or committed. Suggested target forms,\n"
        "choose per the source command:\n"
        "  privilege-escalation password (from super password):\n"
        "    enable secret <PASSWORD>\n"
        "  user account (from local-user):\n"
        "    username <NAME> privilege 15 secret <PASSWORD>"
    ),
    "huawei": (
        "This value appears to be plaintext, so an equivalent credential\n"
        "exists on the target -- but it is NOT applied automatically:\n"
        "credentials must be set deliberately by an operator, and this\n"
        "generated file may be shared or committed. Suggested target forms,\n"
        "choose per the source command:\n"
        "  privilege-escalation password (from enable secret/password):\n"
        "    super password level 15 cipher <PASSWORD>\n"
        "  user account (from username ... secret):\n"
        "    aaa\n"
        "     local-user <NAME> password irreversible-cipher <PASSWORD>\n"
        "     local-user <NAME> privilege level 15"
    ),
}


def is_credential_line(text: str) -> bool:
    """True if a configuration line carries or configures credential material.

    Deliberately broad: a false positive costs one extra review comment, a
    false negative silently copies a hash the target device cannot use.
    """
    lowered = text.strip().lower()
    return any(lowered.startswith(p) or f" {p}" in lowered
               for p in CREDENTIAL_PATTERNS)


def classify_credential(text: str) -> str:
    """Classify a credential line as hashed, plaintext, or carrying no value.

    Three outcomes, because the right message differs for each:

    * ``CRED_NO_VALUE`` -- the line configures the credential subsystem but
      holds no secret (``aaa``, ``line vty 0 4``, ``authentication-mode aaa``).
      Password guidance would be meaningless, so none is emitted.
    * ``CRED_HASHED`` -- the value is a one-way digest. No conversion exists
      without the plaintext, which a saved configuration does not contain.
    * ``CRED_PLAINTEXT`` -- an equivalent exists, but the system still refuses
      to apply it: writing a live credential into a generated file that may be
      shared or committed is a security problem regardless of feasibility.

    Conservative by design: anything ambiguous is reported as hashed, because
    the hashed message is the safer of the two to be wrong about.
    """
    lowered = text.strip().lower()

    if not any(token in lowered for token in VALUE_BEARING_TOKENS):
        return CRED_NO_VALUE

    if any(marker in lowered for marker in HASH_MARKERS):
        return CRED_HASHED

    if _DOLLAR_HASH.search(lowered):
        return CRED_HASHED

    return CRED_PLAINTEXT


def credential_guidance(target_vendor: str, kind: str = CRED_HASHED) -> str:
    """Guidance text for the target vendor and credential kind.

    Returns an empty string for CRED_NO_VALUE -- the caller emits only the
    plain review tag in that case.
    """
    if kind == CRED_NO_VALUE:
        return ""
    table = _PLAINTEXT_GUIDANCE if kind == CRED_PLAINTEXT else _HASHED_GUIDANCE
    return table[target_vendor]
