"""Tests for the validation harness itself.

The IR comparison grades H2, so it has to be trustworthy before any
round-trip number means anything. These tests verify it catches real
differences and ignores cosmetic ones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate.ir import LinkType  # noqa: E402
from netmigrate.rules_cisco import parse_cisco  # noqa: E402
from netmigrate.validation import (  # noqa: E402
    ir_diff,
    ir_equal,
    normalise_text,
)

BASE = """hostname SW1
vlan 10
 name SALES
interface GigabitEthernet0/1
 description USER
 switchport mode access
 switchport access vlan 10
router ospf 1
 router-id 1.1.1.1
 network 10.0.0.0 0.0.0.255 area 0
ip route 0.0.0.0 0.0.0.0 10.0.0.254
"""


def test_identical_configs_compare_equal():
    assert ir_equal(parse_cisco(BASE), parse_cisco(BASE))


def test_line_numbers_ignored():
    """Leading comments shift every line number but change no intent."""
    shifted = "!\n!\n!\n" + BASE
    assert ir_equal(parse_cisco(BASE), parse_cisco(shifted))


def test_comment_marker_ignored():
    a = parse_cisco("! a comment\n" + BASE)
    b = parse_cisco("# a comment\n" + BASE)
    assert ir_equal(a, b)


def test_hostname_change_detected():
    diffs = ir_diff(parse_cisco(BASE), parse_cisco(BASE.replace("SW1", "SW2")))
    assert diffs
    assert any("hostname" in d for d in diffs)


def test_vlan_name_change_detected():
    diffs = ir_diff(parse_cisco(BASE), parse_cisco(BASE.replace("SALES", "MKT")))
    assert any("name" in d for d in diffs)


def test_missing_vlan_detected():
    reduced = BASE.replace("vlan 10\n name SALES\n", "")
    diffs = ir_diff(parse_cisco(BASE), parse_cisco(reduced))
    assert any("length" in d for d in diffs)


def test_access_vlan_change_detected():
    diffs = ir_diff(
        parse_cisco(BASE),
        parse_cisco(BASE.replace("switchport access vlan 10", "switchport access vlan 99")),
    )
    assert any("access_vlan" in d for d in diffs)


def test_trunk_vlan_set_difference_detected():
    a = parse_cisco(
        "interface Gi0/1\n switchport trunk allowed vlan 10,20\n"
    )
    b = parse_cisco(
        "interface Gi0/1\n switchport trunk allowed vlan 10,20,30\n"
    )
    diffs = ir_diff(a, b)
    assert any("trunk_allowed" in d for d in diffs)


def test_admin_down_tristate_distinguished():
    silent = parse_cisco("interface Gi0/1\n description X\n")
    up = parse_cisco("interface Gi0/1\n description X\n no shutdown\n")
    down = parse_cisco("interface Gi0/1\n description X\n shutdown\n")
    assert ir_diff(silent, up)
    assert ir_diff(up, down)
    assert ir_diff(silent, down)


def test_ospf_area_regrouping_difference_detected():
    """Moving a network to a different area must be caught."""
    a = parse_cisco("router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\n")
    b = parse_cisco("router ospf 1\n network 10.0.0.0 0.0.0.255 area 1\n")
    diffs = ir_diff(a, b)
    assert diffs


def test_ospf_dotted_vs_integer_area_equal():
    """area 1 and area 0.0.0.1 are the same area -- must compare equal."""
    a = parse_cisco("router ospf 1\n network 10.0.0.0 0.0.0.255 area 1\n")
    b = parse_cisco("router ospf 1\n network 10.0.0.0 0.0.0.255 area 0.0.0.1\n")
    assert ir_equal(a, b)


def test_mask_and_prefix_forms_equal():
    """Cisco mask and Huawei prefix length express the same subnet."""
    a = parse_cisco("interface Vlan10\n ip address 10.0.0.1 255.255.255.0\n")
    b = parse_cisco("interface Vlan10\n ip address 10.0.0.1 24\n")
    assert ir_equal(a, b)


def test_route_preference_change_detected():
    a = parse_cisco("ip route 10.0.0.0 255.0.0.0 192.168.1.1\n")
    b = parse_cisco("ip route 10.0.0.0 255.0.0.0 192.168.1.1 200\n")
    assert any("preference" in d for d in ir_diff(a, b))


def test_diff_path_is_readable():
    diffs = ir_diff(parse_cisco(BASE), parse_cisco(BASE.replace("SW1", "SW2")))
    assert diffs[0].startswith("hostname"), diffs


def test_normalise_text_collapses_blanks():
    assert normalise_text("a\n\n\n\nb\n") == "a\n\nb"
    assert normalise_text("  a  \n  b  ") == "  a\n  b"
    assert normalise_text("\n\na\n\n") == "a"


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
