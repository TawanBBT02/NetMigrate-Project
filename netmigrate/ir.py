"""
Vendor-neutral intermediate representation (IR).

This module is the contract between the conversion engine and everything else.
Parsers produce a DeviceConfig; renderers consume one. Neither knows about the
other's vendor.

Design notes
------------
* ``Interface.admin_down`` is tri-state (True / False / None). None means the
  source config did not say, and the renderer must stay silent rather than
  guess -- see proposal 2.3.2.5.
* ``OspfProcess.areas`` maps area id -> networks rather than holding a flat
  network list. This is what makes the class-S OSPF transformation
  expressible; a flat list could not be regrouped on output.
* Every object that came from source text carries ``source_line`` so per-line
  provenance survives all the way to the diff view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Vendor(str, Enum):
    CISCO = "cisco_iosxe"
    HUAWEI = "huawei_vrp"


class Provenance(str, Enum):
    """How a given output line was produced. Drives the coverage metric.

    GENERATED covers lines the renderer creates that correspond to no source
    line -- separators, the trailing ``return``. They are excluded from all
    metrics; counting them as rule output would inflate coverage.
    """

    RULE = "RULE"
    AI = "AI"
    UNMAPPED = "UNMAPPED"
    GENERATED = "GENERATED"


class LinkType(str, Enum):
    ACCESS = "access"
    TRUNK = "trunk"


class RuleClass(str, Enum):
    """Difficulty classification from the mapping spec."""

    DIRECT = "D"
    TRANSFORM = "T"
    STRUCTURAL = "S"


# --------------------------------------------------------------------------
# Configuration constructs
# --------------------------------------------------------------------------


@dataclass
class Vlan:
    vlan_id: int
    name: Optional[str] = None
    source_line: Optional[int] = None


@dataclass
class Interface:
    # Type and number are kept apart on purpose: the type is translatable,
    # the number is not (proposal 2.3.2.4).
    if_type: str = ""
    if_number: str = ""

    description: Optional[str] = None
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None

    # None = source config was silent. Do not infer a default.
    admin_down: Optional[bool] = None

    link_type: Optional[LinkType] = None
    access_vlan: Optional[int] = None
    trunk_allowed: set[int] = field(default_factory=set)
    trunk_native: Optional[int] = None

    source_line: Optional[int] = None

    @property
    def full_name(self) -> str:
        return f"{self.if_type}{self.if_number}"


@dataclass
class StaticRoute:
    prefix: str = ""
    mask: str = ""
    next_hop: str = ""  # IP address or interface name
    preference: Optional[int] = None  # Cisco: bare integer. Huawei: keyword.
    source_line: Optional[int] = None


@dataclass
class OspfNetwork:
    address: str
    wildcard: str
    source_line: Optional[int] = None


@dataclass
class OspfProcess:
    process_id: int = 1
    router_id: Optional[str] = None
    # area id (as integer) -> networks in that area
    areas: dict[int, list[OspfNetwork]] = field(default_factory=dict)
    source_line: Optional[int] = None

    def add_network(self, area_id: int, network: OspfNetwork) -> None:
        self.areas.setdefault(area_id, []).append(network)


@dataclass
class UnmappedBlock:
    """A construct the rule engine did not recognise.

    Carried through to output as a commented review tag. The count of these
    is the numerator of the fallback-invocation metric.
    """

    text: str
    source_line: int
    provenance: Provenance = Provenance.UNMAPPED
    suggestion: Optional[str] = None  # filled by the AI fallback, if enabled
    rationale: Optional[str] = None

    # Set when the line is recognised as belonging to a category the engine
    # deliberately refuses to convert -- currently only credentials. Carries
    # structural guidance for manual entry instead of a translation.
    category: Optional[str] = None
    guidance: Optional[str] = None


# --------------------------------------------------------------------------
# Root object
# --------------------------------------------------------------------------


@dataclass
class DeviceConfig:
    source_vendor: Optional[Vendor] = None
    hostname: Optional[str] = None
    vlans: list[Vlan] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)
    static_routes: list[StaticRoute] = field(default_factory=list)
    ospf: Optional[OspfProcess] = None
    unmapped: list[UnmappedBlock] = field(default_factory=list)

    # Set by the parser: total lines and significant lines (non-blank,
    # non-comment). Significant lines is the coverage denominator.
    total_lines: int = 0
    significant_lines: int = 0

    def find_interface(self, if_type: str, if_number: str) -> Optional[Interface]:
        for itf in self.interfaces:
            if itf.if_type == if_type and itf.if_number == if_number:
                return itf
        return None


# --------------------------------------------------------------------------
# Engine output -- the API contract with the web layer
# --------------------------------------------------------------------------


@dataclass
class OutputLine:
    """One line of rendered output, with where it came from."""

    text: str
    provenance: Provenance
    source_line: Optional[int] = None
    rule_id: Optional[str] = None
    needs_review: bool = False


@dataclass
class ConversionResult:
    """What the engine hands back. Stable shape -- the web layer depends on it.

    Serialise with ``to_dict()``; do not let the web layer touch the
    dataclasses directly, so the internal model stays free to change.
    """

    source_vendor: Vendor
    target_vendor: Vendor
    source_text: str
    output_text: str
    lines: list[OutputLine] = field(default_factory=list)

    total_lines: int = 0
    significant_lines: int = 0
    rule_lines: int = 0
    ai_lines: int = 0
    unmapped_lines: int = 0
    duration_ms: float = 0.0  # float: conversions run well under 1 ms

    @property
    def rule_coverage(self) -> float:
        """H1. Proportion of significant lines handled by the rule engine."""
        if self.significant_lines == 0:
            return 0.0
        return self.rule_lines / self.significant_lines

    def to_dict(self) -> dict:
        return {
            "source_vendor": self.source_vendor.value,
            "target_vendor": self.target_vendor.value,
            "source_text": self.source_text,
            "output_text": self.output_text,
            "lines": [
                {
                    "text": ln.text,
                    "provenance": ln.provenance.value,
                    "source_line": ln.source_line,
                    "rule_id": ln.rule_id,
                    "needs_review": ln.needs_review,
                }
                for ln in self.lines
            ],
            "metrics": {
                "total_lines": self.total_lines,
                "significant_lines": self.significant_lines,
                "rule_lines": self.rule_lines,
                "ai_lines": self.ai_lines,
                "unmapped_lines": self.unmapped_lines,
                "rule_coverage": round(self.rule_coverage, 4),
                "duration_ms": round(self.duration_ms, 4),
            },
        }
