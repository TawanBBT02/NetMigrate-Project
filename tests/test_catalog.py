"""
Tests that keep the rule catalog synchronised with the code.

Appendix A of the thesis is generated from netmigrate/rule_catalog.py. These
tests assert that the catalog and the renderers agree, so a rule added or
renamed in the code without updating the catalog fails the suite rather than
producing a quietly wrong appendix.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate import rule_catalog as cat  # noqa: E402
from netmigrate.engine import convert  # noqa: E402
from netmigrate.ir import Provenance, Vendor  # noqa: E402
from netmigrate.transforms import INTERFACE_TYPES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RENDERERS = [
    ROOT / "netmigrate" / "render_cisco.py",
    ROOT / "netmigrate" / "render_huawei.py",
]

# Matches the rule_id argument in _rule(...) calls.
RULE_ID_RE = re.compile(r'"([a-z]+\.[a-z-]+)"')

C, H = Vendor.CISCO, Vendor.HUAWEI


def rule_ids_in_code() -> set[str]:
    found: set[str] = set()
    for path in RENDERERS:
        found |= set(RULE_ID_RE.findall(path.read_text(encoding="utf-8")))
    return found


# --------------------------------------------------------------------------
# Catalog / code agreement
# --------------------------------------------------------------------------


def test_every_code_rule_is_catalogued():
    """A rule emitted by a renderer must appear in the catalog."""
    missing = rule_ids_in_code() - cat.rule_ids()
    assert not missing, (
        f"rule_id(s) used in the renderers but absent from rule_catalog.py: "
        f"{sorted(missing)}. Add them, or Appendix A will be incomplete."
    )


def test_every_catalogued_rule_exists_in_code():
    """A catalogued rule must actually be emitted by a renderer."""
    extra = cat.rule_ids() - rule_ids_in_code()
    assert not extra, (
        f"rule_id(s) catalogued but not found in any renderer: "
        f"{sorted(extra)}. Either the rule was removed or the id was renamed."
    )


def test_all_rule_ids_use_dotted_form():
    """Naming consistency: every rule id is <group>.<name>."""
    for rule in cat.CATALOG:
        assert "." in rule.rule_id, rule.rule_id
        group, name = rule.rule_id.split(".", 1)
        assert group and name, rule.rule_id
        assert rule.rule_id == rule.rule_id.lower(), rule.rule_id


def test_interface_type_catalog_matches_transforms():
    """The appendix interface table must match the implementation."""
    catalogued = {i.canonical for i in cat.INTERFACE_TYPE_CATALOG}
    implemented = set(INTERFACE_TYPES)
    assert catalogued == implemented, (
        f"catalog {sorted(catalogued)} != code {sorted(implemented)}"
    )

    for itype in cat.INTERFACE_TYPE_CATALOG:
        cisco, huawei = INTERFACE_TYPES[itype.canonical]
        assert itype.cisco == cisco, itype.canonical
        assert itype.huawei == huawei, itype.canonical


# --------------------------------------------------------------------------
# Catalog integrity
# --------------------------------------------------------------------------


def test_rule_classes_are_valid():
    for rule in cat.CATALOG:
        assert rule.rule_class in ("D", "T", "S"), rule.rule_id


def test_statuses_are_valid():
    valid = ("DOC", "EX", "SIM", "UNVER")
    for rule in cat.CATALOG:
        assert rule.status in valid, (rule.rule_id, rule.status)
    for itype in cat.INTERFACE_TYPE_CATALOG:
        assert itype.status in valid, (itype.canonical, itype.status)


def test_references_resolve():
    """Every reference key must exist in the REFERENCES table."""
    for rule in cat.CATALOG:
        assert rule.reference in cat.REFERENCES, (
            f"{rule.rule_id} cites unknown reference {rule.reference!r}"
        )
    for itype in cat.INTERFACE_TYPE_CATALOG:
        assert itype.reference in cat.REFERENCES, itype.canonical


def test_verified_rules_cite_a_real_reference():
    """DOC/EX/SIM status requires an actual reference, not the '-' placeholder."""
    for rule in cat.CATALOG:
        if rule.status in ("DOC", "EX", "SIM"):
            assert rule.reference != "-", (
                f"{rule.rule_id} is marked {rule.status} but cites no reference"
            )
    for itype in cat.INTERFACE_TYPE_CATALOG:
        if itype.status in ("DOC", "EX", "SIM"):
            assert itype.reference != "-", itype.canonical


def test_unverified_rules_are_flagged_in_the_note():
    """An UNVER rule must say so in its note, so the appendix is honest."""
    for rule in cat.CATALOG:
        if rule.status == "UNVER":
            assert "ยังไม่ยืนยัน" in rule.note, (
                f"{rule.rule_id} is UNVER but its note does not say so"
            )


def test_no_duplicate_rule_ids():
    ids = [r.rule_id for r in cat.CATALOG]
    assert len(ids) == len(set(ids)), "duplicate rule_id in catalog"


def test_ospf_asymmetry_is_documented():
    """ospf.router-id and ospf.area appear in one renderer each, by design.
    That asymmetry IS the class-S transformation, so it must be explained."""
    for rule_id in ("ospf.router-id", "ospf.area"):
        rule = next(r for r in cat.CATALOG if r.rule_id == rule_id)
        assert rule.rule_class == "S", rule_id
        assert rule.note, f"{rule_id} needs a note explaining the asymmetry"


# --------------------------------------------------------------------------
# Conformance figure used in the thesis
# --------------------------------------------------------------------------


def test_conformance_is_computable_and_sane():
    value = cat.conformance()
    assert 0.0 <= value <= 1.0
    counts = cat.status_counts()
    assert sum(counts.values()) == len(cat.CATALOG) + len(
        cat.INTERFACE_TYPE_CATALOG
    )


def test_conformance_counts_only_evidenced_statuses():
    """UNVER must never count toward the H3b figure."""
    counts = cat.status_counts()
    evidenced = (counts.get("DOC", 0) + counts.get("EX", 0)
                 + counts.get("SIM", 0))
    total = sum(counts.values())
    assert abs(cat.conformance() - evidenced / total) < 1e-9


# --------------------------------------------------------------------------
# Catalogued rule ids actually appear in conversion output
# --------------------------------------------------------------------------


def test_catalogued_rules_appear_in_a_real_conversion():
    """Smoke test: convert a config exercising most rules and confirm the
    rule_ids attached to output lines are all catalogued."""
    src = (
        "hostname SW1\n"
        "vlan 10\n name SALES\n"
        "interface GigabitEthernet0/0/1\n"
        " description UPLINK\n"
        " switchport mode trunk\n"
        " switchport trunk allowed vlan 10,20\n"
        " switchport trunk native vlan 99\n"
        " no shutdown\n"
        "interface Vlan10\n"
        " ip address 10.0.0.1 255.255.255.0\n"
        "router ospf 1\n"
        " router-id 1.1.1.1\n"
        " network 10.0.0.0 0.0.0.255 area 0\n"
        "ip route 0.0.0.0 0.0.0.0 10.0.0.254\n"
    )
    for target in (H, C):
        source = C if target is H else H
        text = src if source is C else convert(src, C, H).output_text
        result = convert(text, source, target)
        seen = {
            line.rule_id for line in result.lines
            if line.provenance is Provenance.RULE and line.rule_id
        }
        assert seen, "no rule_ids attached to output"
        unknown = seen - cat.rule_ids()
        assert not unknown, f"uncatalogued rule_id in output: {sorted(unknown)}"


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {exc}")
        else:
            passed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
