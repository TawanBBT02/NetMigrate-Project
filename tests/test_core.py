"""
Tests for the block parser and the pure transforms.

Written as plain assert functions so pytest collects them directly. A
fallback runner at the bottom lets them run without pytest installed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate.blocks import parse_blocks, dump_tree  # noqa: E402
from netmigrate import transforms as tf  # noqa: E402


# --------------------------------------------------------------------------
# Block parser
# --------------------------------------------------------------------------

CISCO_SAMPLE = """!
! Last configuration change at 12:00:00 UTC
!
hostname SW1
!
vlan 10
 name SALES
!
vlan 20
 name ENG
!
interface GigabitEthernet0/0/1
 description UPLINK TO CORE
 switchport mode trunk
 switchport trunk allowed vlan 10,20
 no shutdown
!
interface Vlan10
 ip address 192.168.10.1 255.255.255.0
!
router ospf 1
 router-id 1.1.1.1
 network 192.168.10.0 0.0.0.255 area 0
 network 172.16.0.0 0.0.0.255 area 1
!
ip route 10.0.0.0 255.0.0.0 192.168.10.254
end
"""

HUAWEI_SAMPLE = """#
sysname SW1
#
vlan batch 10 20
#
vlan 10
 name SALES
#
interface GE0/0/1
 description UPLINK TO CORE
 port link-type trunk
 port trunk allow-pass vlan 10 20
 undo shutdown
#
interface Vlanif10
 ip address 192.168.10.1 255.255.255.0
#
ospf 1 router-id 1.1.1.1
 area 0.0.0.0
  network 192.168.10.0 0.0.0.255
 area 0.0.0.1
  network 172.16.0.0 0.0.0.255
#
ip route-static 10.0.0.0 255.0.0.0 192.168.10.254
return
"""


def test_parses_top_level_blocks():
    parsed = parse_blocks(CISCO_SAMPLE)
    keywords = [b.keyword for b in parsed.blocks]
    assert "hostname" in keywords
    assert keywords.count("vlan") == 2
    assert keywords.count("interface") == 2
    assert "router" in keywords


def test_comments_and_blanks_excluded_from_tree_but_counted():
    parsed = parse_blocks(CISCO_SAMPLE)
    # No '!' lines should appear as blocks
    for block in parsed.walk():
        assert not block.text.startswith("!")
    assert parsed.comment_lines > 0
    assert parsed.significant_lines < parsed.total_lines


def test_nesting_by_indentation():
    parsed = parse_blocks(CISCO_SAMPLE)
    itf = [b for b in parsed.blocks if b.keyword == "interface"][0]
    child_text = [c.text for c in itf.children]
    assert "description UPLINK TO CORE" in child_text
    assert "switchport mode trunk" in child_text
    assert "no shutdown" in child_text
    # children must not have leaked to top level
    assert "description UPLINK TO CORE" not in [b.text for b in parsed.blocks]


def test_deep_nesting_huawei_ospf():
    """Huawei nests network under area under ospf -- three levels."""
    parsed = parse_blocks(HUAWEI_SAMPLE)
    ospf = [b for b in parsed.blocks if b.keyword == "ospf"][0]
    areas = ospf.children_with_keyword("area")
    assert len(areas) == 2
    assert areas[0].text == "area 0.0.0.0"
    nets = areas[0].children_with_keyword("network")
    assert len(nets) == 1
    assert nets[0].text == "network 192.168.10.0 0.0.0.255"


def test_cisco_ospf_is_two_levels():
    """Cisco puts area on the network line -- networks are direct children."""
    parsed = parse_blocks(CISCO_SAMPLE)
    ospf = [b for b in parsed.blocks if b.keyword == "router"][0]
    nets = ospf.children_with_keyword("network")
    assert len(nets) == 2
    assert nets[0].text.endswith("area 0")
    assert ospf.child_with_keyword("router-id").text == "router-id 1.1.1.1"


def test_terminators_consumed_not_emitted():
    parsed = parse_blocks(CISCO_SAMPLE)
    assert "end" not in [b.keyword for b in parsed.walk()]
    parsed_h = parse_blocks(HUAWEI_SAMPLE)
    assert "return" not in [b.keyword for b in parsed_h.walk()]


def test_explicit_exit_closes_block():
    text = "interface GE0/0/1\n description A\nexit\ninterface GE0/0/2\n description B\n"
    parsed = parse_blocks(text)
    assert len(parsed.blocks) == 2
    assert len(parsed.blocks[0].children) == 1
    assert len(parsed.blocks[1].children) == 1


def test_line_numbers_preserved():
    parsed = parse_blocks(CISCO_SAMPLE)
    hostname = [b for b in parsed.blocks if b.keyword == "hostname"][0]
    assert CISCO_SAMPLE.splitlines()[hostname.line_no - 1].strip() == "hostname SW1"


def test_empty_input():
    parsed = parse_blocks("")
    assert parsed.blocks == []
    assert parsed.total_lines == 0
    assert parsed.significant_lines == 0


def test_keyword_and_args():
    parsed = parse_blocks("ip route 10.0.0.0 255.0.0.0 192.168.1.1\n")
    b = parsed.blocks[0]
    assert b.keyword == "ip"
    assert b.args == ["route", "10.0.0.0", "255.0.0.0", "192.168.1.1"]


# --------------------------------------------------------------------------
# VLAN list transforms -- the highest-risk functions in the project
# --------------------------------------------------------------------------


def test_vlan_single():
    assert tf.parse_vlan_list_cisco("10") == {10}
    assert tf.parse_vlan_list_huawei("10") == {10}


def test_vlan_simple_list():
    assert tf.parse_vlan_list_cisco("10,20,30") == {10, 20, 30}
    assert tf.parse_vlan_list_huawei("10 20 30") == {10, 20, 30}


def test_vlan_range():
    assert tf.parse_vlan_list_cisco("30-35") == {30, 31, 32, 33, 34, 35}
    assert tf.parse_vlan_list_huawei("30 to 35") == {30, 31, 32, 33, 34, 35}


def test_vlan_mixed():
    expected = {10, 20, 30, 31, 32, 33, 34, 35, 40}
    assert tf.parse_vlan_list_cisco("10,20,30-35,40") == expected
    assert tf.parse_vlan_list_huawei("10 20 30 to 35 40") == expected


def test_vlan_adjacent_pair_not_ranged():
    """10,11 must render as two ids, not as a range -- spec edge case."""
    ids = {10, 11}
    assert tf.render_vlan_list_cisco(ids) == "10,11"
    assert tf.render_vlan_list_huawei(ids) == "10 11"


def test_vlan_range_of_three_is_ranged():
    ids = {10, 11, 12}
    assert tf.render_vlan_list_cisco(ids) == "10-12"
    assert tf.render_vlan_list_huawei(ids) == "10 to 12"


def test_vlan_unsorted_and_duplicate_input():
    assert tf.parse_vlan_list_cisco("30,10,20,10") == {10, 20, 30}
    assert tf.render_vlan_list_cisco({30, 10, 20}) == "10,20,30"


def test_vlan_reversed_range_tolerated():
    assert tf.parse_vlan_list_cisco("35-30") == set(range(30, 36))
    assert tf.parse_vlan_list_huawei("35 to 30") == set(range(30, 36))


def test_vlan_round_trip_cisco_to_huawei_to_cisco():
    for spec in ["10", "10,20", "10,11", "1-5", "10,20,30-35,40", "100-200,300"]:
        ids = tf.parse_vlan_list_cisco(spec)
        huawei = tf.render_vlan_list_huawei(ids)
        back = tf.parse_vlan_list_huawei(huawei)
        assert back == ids, f"round trip lost data for {spec!r} via {huawei!r}"
        assert tf.parse_vlan_list_cisco(tf.render_vlan_list_cisco(ids)) == ids


def test_vlan_out_of_range_rejected():
    for bad in ["0", "4095", "1,5000"]:
        try:
            tf.parse_vlan_list_cisco(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_vlan_empty_render():
    assert tf.render_vlan_list_cisco(set()) == ""
    assert tf.render_vlan_list_huawei(set()) == ""


# --------------------------------------------------------------------------
# OSPF area identifiers
# --------------------------------------------------------------------------


def test_area_integer_form():
    assert tf.parse_area_id("0") == 0
    assert tf.parse_area_id("1") == 1
    assert tf.parse_area_id("100") == 100


def test_area_dotted_form():
    assert tf.parse_area_id("0.0.0.0") == 0
    assert tf.parse_area_id("0.0.0.1") == 1


def test_area_one_is_not_one_dot_zero_zero_zero():
    """The classic mistake: area 1 is 0.0.0.1, not 1.0.0.0."""
    assert tf.render_area_id_dotted(1) == "0.0.0.1"
    assert tf.render_area_id_dotted(1) != "1.0.0.0"


def test_area_large_value():
    assert tf.render_area_id_dotted(256) == "0.0.1.0"
    assert tf.parse_area_id("0.0.1.0") == 256


def test_area_round_trip():
    for value in [0, 1, 2, 10, 255, 256, 65535]:
        dotted = tf.render_area_id_dotted(value)
        assert tf.parse_area_id(dotted) == value
        assert tf.parse_area_id(tf.render_area_id_int(value)) == value


# --------------------------------------------------------------------------
# Masks
# --------------------------------------------------------------------------


def test_mask_conversions():
    assert tf.mask_to_prefix_len("255.255.255.0") == 24
    assert tf.prefix_len_to_mask(24) == "255.255.255.0"
    assert tf.prefix_len_to_mask(30) == "255.255.255.252"


def test_normalise_mask_accepts_both_forms():
    assert tf.normalise_mask("255.255.255.0") == "255.255.255.0"
    assert tf.normalise_mask("24") == "255.255.255.0"
    assert tf.normalise_mask("8") == "255.0.0.0"


def test_invalid_mask_rejected():
    try:
        tf.normalise_mask("255.0.255.0")
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-contiguous mask")


# --------------------------------------------------------------------------
# Interface names
# --------------------------------------------------------------------------


def test_split_interface_name():
    assert tf.split_interface_name("GigabitEthernet0/0/1") == ("GigabitEthernet", "0/0/1")
    assert tf.split_interface_name("GE0/0/1") == ("GE", "0/0/1")
    assert tf.split_interface_name("Vlanif10") == ("Vlanif", "10")
    assert tf.split_interface_name("Eth-Trunk1") == ("Eth-Trunk", "1")
    assert tf.split_interface_name("Loopback0") == ("Loopback", "0")


def test_canonical_types():
    assert tf.canonical_interface_type("GigabitEthernet") == "gigabit"
    assert tf.canonical_interface_type("GE") == "gigabit"
    assert tf.canonical_interface_type("Gi") == "gigabit"
    assert tf.canonical_interface_type("XGE") == "tengigabit"
    assert tf.canonical_interface_type("TenGigabitEthernet") == "tengigabit"
    assert tf.canonical_interface_type("Vlanif") == "vlan"
    assert tf.canonical_interface_type("Port-channel") == "portchannel"
    assert tf.canonical_interface_type("Eth-Trunk") == "portchannel"
    assert tf.canonical_interface_type("Serial") is None


def test_interface_type_rendering_both_directions():
    cases = [
        ("GigabitEthernet", "GE"),
        ("TenGigabitEthernet", "XGE"),
        ("Loopback", "LoopBack"),
        ("Vlan", "Vlanif"),
        ("Port-channel", "Eth-Trunk"),
    ]
    for cisco, huawei in cases:
        key = tf.canonical_interface_type(cisco)
        assert tf.render_interface_type(key, "cisco") == cisco
        assert tf.render_interface_type(key, "huawei") == huawei
        key_back = tf.canonical_interface_type(huawei)
        assert key_back == key, f"{huawei} did not map back to {key}"


def test_vlan_interface_not_confused_with_vlan_block():
    """Vlan10 the interface maps to Vlanif10, which is easy to get wrong."""
    if_type, if_number = tf.split_interface_name("Vlan10")
    key = tf.canonical_interface_type(if_type)
    assert tf.render_interface_type(key, "huawei") + if_number == "Vlanif10"


def test_slot_review_flag():
    assert tf.slot_needs_review("0/0/1", "gigabit") is False
    assert tf.slot_needs_review("1/0/1", "gigabit") is True
    assert tf.slot_needs_review("0/1", "gigabit") is False
    assert tf.slot_needs_review("", "gigabit") is False


def test_slot_review_exempts_logical_interfaces():
    """Vlanif10 is VLAN 10, not slot 10 -- must not warn."""
    assert tf.slot_needs_review("10", "vlan") is False
    assert tf.slot_needs_review("1", "loopback") is False
    assert tf.slot_needs_review("1", "portchannel") is False


def test_slot_review_needs_slash_notation():
    """A bare number is an index, not a slot."""
    assert tf.slot_needs_review("10", "gigabit") is False
    assert tf.slot_needs_review("1/1", "gigabit") is True


# --------------------------------------------------------------------------
# Fallback runner
# --------------------------------------------------------------------------

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
