"""Tests for the Huawei front end, the Cisco back end, and round tripping."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate.engine import convert  # noqa: E402
from netmigrate.ir import LinkType, Vendor  # noqa: E402
from netmigrate.rules_cisco import parse_cisco  # noqa: E402
from netmigrate.rules_huawei import parse_huawei  # noqa: E402
from netmigrate.validation import ir_diff, ir_equal, round_trip  # noqa: E402

C, H = Vendor.CISCO, Vendor.HUAWEI


def to_huawei(text: str) -> str:
    return convert(text, C, H).output_text


def to_cisco(text: str) -> str:
    return convert(text, H, C).output_text


# --------------------------------------------------------------------------
# Huawei parser
# --------------------------------------------------------------------------


def test_sysname():
    assert parse_huawei("sysname SW02\n").hostname == "SW02"


def test_vlan_batch_expands():
    cfg = parse_huawei("vlan batch 10 20 30 to 32\n")
    assert [v.vlan_id for v in cfg.vlans] == [10, 20, 30, 31, 32]
    assert all(v.name is None for v in cfg.vlans)


def test_vlan_batch_then_named_block_merges():
    """Real VRP output declares batch first, then names individually."""
    cfg = parse_huawei("vlan batch 10 20\nvlan 10\n name SALES\n")
    assert len(cfg.vlans) == 2
    named = {v.vlan_id: v.name for v in cfg.vlans}
    assert named == {10: "SALES", 20: None}


def test_port_access():
    cfg = parse_huawei(
        "interface GE0/0/1\n port link-type access\n port default vlan 10\n"
    )
    itf = cfg.interfaces[0]
    assert itf.link_type is LinkType.ACCESS
    assert itf.access_vlan == 10


def test_port_trunk():
    cfg = parse_huawei(
        "interface GE0/0/1\n"
        " port link-type trunk\n"
        " port trunk allow-pass vlan 10 20 30 to 32\n"
        " port trunk pvid vlan 99\n"
    )
    itf = cfg.interfaces[0]
    assert itf.link_type is LinkType.TRUNK
    assert itf.trunk_allowed == {10, 20, 30, 31, 32}
    assert itf.trunk_native == 99


def test_repeated_allow_pass_accumulates():
    cfg = parse_huawei(
        "interface GE0/0/1\n"
        " port trunk allow-pass vlan 10 20\n"
        " port trunk allow-pass vlan 30\n"
    )
    assert cfg.interfaces[0].trunk_allowed == {10, 20, 30}


def test_allow_pass_all_unmapped():
    """'all' has no explicit Cisco list equivalent in scope."""
    cfg = parse_huawei("interface GE0/0/1\n port trunk allow-pass vlan all\n")
    assert cfg.interfaces[0].trunk_allowed == set()
    assert any("allow-pass" in u.text for u in cfg.unmapped)


def test_hybrid_link_type_unmapped():
    cfg = parse_huawei("interface GE0/0/1\n port link-type hybrid\n")
    assert cfg.interfaces[0].link_type is None
    assert any("hybrid" in u.text for u in cfg.unmapped)


def test_undo_shutdown():
    assert parse_huawei("interface GE0/0/1\n undo shutdown\n").interfaces[0].admin_down is False
    assert parse_huawei("interface GE0/0/1\n shutdown\n").interfaces[0].admin_down is True


def test_ip_address_prefix_length_form():
    cfg = parse_huawei("interface Vlanif20\n ip address 192.168.20.1 24\n")
    itf = cfg.interfaces[0]
    assert itf.ip_address == "192.168.20.1"
    assert itf.subnet_mask == "255.255.255.0"


def test_huawei_interface_types():
    for name, expect in [
        ("GE0/0/1", "gigabit"),
        ("XGE0/0/25", "tengigabit"),
        ("Vlanif20", "vlan"),
        ("LoopBack0", "loopback"),
        ("Eth-Trunk1", "portchannel"),
    ]:
        cfg = parse_huawei(f"interface {name}\n description X\n")
        assert cfg.interfaces[0].if_type == expect, name


def test_route_static_with_preference():
    cfg = parse_huawei(
        "ip route-static 172.16.0.0 255.255.0.0 10.0.0.1 preference 150\n"
    )
    assert cfg.static_routes[0].preference == 150


def test_route_static_bare_integer_rejected():
    """VRP requires the keyword; a bare trailing integer is not valid here."""
    cfg = parse_huawei("ip route-static 172.16.0.0 255.255.0.0 10.0.0.1 150\n")
    assert cfg.static_routes == []
    assert len(cfg.unmapped) == 1


def test_ospf_router_id_on_process_line():
    cfg = parse_huawei(
        "ospf 1 router-id 2.2.2.2\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.255\n"
    )
    assert cfg.ospf.router_id == "2.2.2.2"
    assert list(cfg.ospf.areas) == [0]


def test_ospf_nested_areas_flatten_into_mapping():
    cfg = parse_huawei(
        "ospf 1 router-id 2.2.2.2\n"
        " area 0.0.0.0\n"
        "  network 10.0.0.0 0.0.0.255\n"
        "  network 10.1.0.0 0.0.0.255\n"
        " area 0.0.0.5\n"
        "  network 10.5.0.0 0.0.0.255\n"
    )
    assert sorted(cfg.ospf.areas) == [0, 5]
    assert len(cfg.ospf.areas[0]) == 2
    assert len(cfg.ospf.areas[5]) == 1


def test_empty_area_preserved():
    cfg = parse_huawei("ospf 1\n area 0.0.0.0\n")
    assert cfg.ospf.areas == {0: []}


def test_unknown_top_level_unmapped():
    cfg = parse_huawei("undo info-center enable\nsnmp-agent\n")
    assert len(cfg.unmapped) == 2


# --------------------------------------------------------------------------
# Cisco renderer
# --------------------------------------------------------------------------


def test_render_cisco_basics():
    out = to_cisco("sysname SW1\n")
    assert "hostname SW1" in out
    assert out.strip().endswith("end")
    assert out.lstrip().startswith("!")


def test_render_cisco_access_port():
    out = to_cisco(
        "interface GE0/0/1\n port link-type access\n port default vlan 10\n"
    )
    assert "interface GigabitEthernet0/0/1" in out
    assert "switchport mode access" in out
    assert "switchport access vlan 10" in out


def test_render_cisco_trunk_vlan_notation():
    out = to_cisco(
        "interface GE0/0/1\n"
        " port link-type trunk\n"
        " port trunk allow-pass vlan 10 20 30 to 35\n"
    )
    assert "switchport trunk allowed vlan 10,20,30-35" in out


def test_render_cisco_ospf_flattens_areas():
    out = to_cisco(
        "ospf 1 router-id 2.2.2.2\n"
        " area 0.0.0.0\n"
        "  network 10.0.0.0 0.0.0.255\n"
        " area 0.0.0.5\n"
        "  network 10.5.0.0 0.0.0.255\n"
    )
    assert "router ospf 1" in out
    assert " router-id 2.2.2.2" in out
    assert "network 10.0.0.0 0.0.0.255 area 0" in out
    assert "network 10.5.0.0 0.0.0.255 area 5" in out
    # Areas must NOT appear as blocks in Cisco output
    assert "area 0.0.0.0" not in out


def test_render_cisco_route_preference_is_bare_integer():
    out = to_cisco("ip route-static 10.0.0.0 255.0.0.0 10.0.0.1 preference 200\n")
    assert "ip route 10.0.0.0 255.0.0.0 10.0.0.1 200" in out
    assert "preference" not in out


def test_render_huawei_ospf_nests_areas():
    out = to_huawei(
        "router ospf 1\n"
        " router-id 1.1.1.1\n"
        " network 10.0.0.0 0.0.0.255 area 0\n"
        " network 172.16.0.0 0.0.0.255 area 1\n"
    )
    assert "ospf 1 router-id 1.1.1.1" in out
    assert " area 0.0.0.0" in out
    assert " area 0.0.0.1" in out
    assert "  network 10.0.0.0 0.0.0.255" in out
    # router-id must not remain a child line in VRP output
    assert "\n router-id" not in out


def test_silent_admin_state_stays_silent_both_ways():
    out_h = to_huawei("interface Gi0/1\n description X\n")
    assert "shutdown" not in out_h
    out_c = to_cisco("interface GE0/0/1\n description X\n")
    assert "shutdown" not in out_c


def test_unmapped_uses_target_comment_marker():
    out_h = to_huawei("ip nbar protocol-discovery\n")
    assert "# [NETMIGRATE-REVIEW]" in out_h
    out_c = to_cisco("undo info-center enable\n")
    assert "! [NETMIGRATE-REVIEW]" in out_c


def test_ai_output_never_uncommented():
    """A suggestion must only ever appear inside a comment."""
    from netmigrate.ir import UnmappedBlock
    from netmigrate.render_huawei import render_huawei
    from netmigrate.rules_cisco import parse_cisco as pc

    cfg = pc("ip nbar protocol-discovery\n")
    cfg.unmapped[0].suggestion = "traffic classifier DANGEROUS"
    cfg.unmapped[0].rationale = "no direct equivalent"
    text = "\n".join(ln.text for ln in render_huawei(cfg))
    for line in text.splitlines():
        if "DANGEROUS" in line:
            assert line.lstrip().startswith("#"), line


# --------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------

CISCO_FULL = """!
hostname SW1
!
vlan 10
 name SALES
!
vlan 20
 name ENG
!
interface GigabitEthernet0/0/1
 description TRUNK
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30-35
 switchport trunk native vlan 99
 no shutdown
!
interface GigabitEthernet0/0/2
 description USER
 switchport mode access
 switchport access vlan 10
 shutdown
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
interface Vlan10
 ip address 192.168.10.1 255.255.255.0
!
router ospf 1
 router-id 1.1.1.1
 network 192.168.10.0 0.0.0.255 area 0
 network 1.1.1.1 0.0.0.0 area 0
 network 172.16.0.0 0.0.0.255 area 5
!
ip route 0.0.0.0 0.0.0.0 192.168.10.254
ip route 172.16.0.0 255.255.0.0 192.168.10.253 200
!
end
"""


def test_round_trip_cisco_full():
    report = round_trip(CISCO_FULL, C, H)
    assert not report.skipped
    assert report.ok, report.differences


def test_round_trip_preserves_every_field():
    """Explicit field-level check, not just the harness verdict."""
    original = parse_cisco(CISCO_FULL)
    returned = parse_cisco(to_cisco(to_huawei(CISCO_FULL)))

    assert returned.hostname == original.hostname
    assert [(v.vlan_id, v.name) for v in returned.vlans] == \
           [(v.vlan_id, v.name) for v in original.vlans]

    for a, b in zip(original.interfaces, returned.interfaces):
        assert (a.if_type, a.if_number) == (b.if_type, b.if_number)
        assert a.description == b.description
        assert a.ip_address == b.ip_address
        assert a.subnet_mask == b.subnet_mask
        assert a.admin_down == b.admin_down
        assert a.link_type == b.link_type
        assert a.access_vlan == b.access_vlan
        assert a.trunk_allowed == b.trunk_allowed
        assert a.trunk_native == b.trunk_native

    assert original.ospf.router_id == returned.ospf.router_id
    assert set(original.ospf.areas) == set(returned.ospf.areas)
    for area in original.ospf.areas:
        assert [(n.address, n.wildcard) for n in original.ospf.areas[area]] == \
               [(n.address, n.wildcard) for n in returned.ospf.areas[area]]


def test_round_trip_huawei_source():
    text = (
        "#\n"
        "sysname SW02\n"
        "#\n"
        "vlan 10\n"
        " name SALES\n"
        "#\n"
        "interface XGE0/0/25\n"
        " description UPLINK\n"
        " port link-type trunk\n"
        " port trunk allow-pass vlan 10 20 30 to 35\n"
        " undo shutdown\n"
        "#\n"
        "ospf 1 router-id 2.2.2.2\n"
        " area 0.0.0.5\n"
        "  network 10.5.0.0 0.0.0.255\n"
        "#\n"
        "ip route-static 0.0.0.0 0.0.0.0 10.0.0.1 preference 150\n"
        "#\n"
        "return\n"
    )
    report = round_trip(text, H, C)
    assert report.ok, report.differences


def test_round_trip_is_idempotent_after_first_pass():
    """Second round trip must change nothing -- catches normalisation drift."""
    once = to_cisco(to_huawei(CISCO_FULL))
    twice = to_cisco(to_huawei(once))
    assert ir_equal(parse_cisco(once), parse_cisco(twice))


def test_vlan_batch_expansion_is_semantically_lossless():
    """Documented normalisation: 'vlan batch' expands and does not return.

    The text differs, the meaning does not. This is why fidelity is measured
    on the IR (see validation.py) rather than on the output text.
    """
    text = "sysname SW\nvlan batch 10 20 30\n"
    returned = to_huawei(to_cisco(text))
    assert "vlan batch" not in returned          # text changed
    original_ir = parse_huawei(text)
    returned_ir = parse_huawei(returned)
    assert ir_equal(original_ir, returned_ir)    # meaning did not


def test_prefix_length_mask_normalises_to_dotted():
    """Documented normalisation: '24' becomes '255.255.255.0' and stays."""
    text = "interface Vlanif20\n ip address 192.168.20.1 24\n"
    returned = to_huawei(to_cisco(text))
    assert "255.255.255.0" in returned
    assert ir_equal(parse_huawei(text), parse_huawei(returned))


def test_unmapped_excluded_from_fidelity_not_from_count():
    report = round_trip(
        "hostname SW1\nip nbar protocol-discovery\n", C, H
    )
    assert report.ok                   # unmapped does not fail fidelity
    assert report.unmapped_lines == 1  # but it is counted
    assert report.rule_coverage < 1.0


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
