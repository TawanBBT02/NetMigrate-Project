"""Tests for the Cisco IOS-XE front end."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate.ir import LinkType, Vendor  # noqa: E402
from netmigrate.rules_cisco import parse_cisco  # noqa: E402


# --------------------------------------------------------------------------
# hostname
# --------------------------------------------------------------------------


def test_hostname():
    cfg = parse_cisco("hostname SW-CORE-01\n")
    assert cfg.hostname == "SW-CORE-01"
    assert cfg.source_vendor == Vendor.CISCO


def test_hostname_malformed_is_unmapped():
    cfg = parse_cisco("hostname\n")
    assert cfg.hostname is None
    assert len(cfg.unmapped) == 1


# --------------------------------------------------------------------------
# vlan
# --------------------------------------------------------------------------


def test_vlan_with_name():
    cfg = parse_cisco("vlan 10\n name SALES\n")
    assert len(cfg.vlans) == 1
    assert cfg.vlans[0].vlan_id == 10
    assert cfg.vlans[0].name == "SALES"


def test_vlan_without_name():
    cfg = parse_cisco("vlan 20\n")
    assert cfg.vlans[0].vlan_id == 20
    assert cfg.vlans[0].name is None


def test_vlan_name_with_spaces():
    cfg = parse_cisco("vlan 30\n name GUEST WIFI\n")
    assert cfg.vlans[0].name == "GUEST WIFI"


def test_vlan_multi_create_expands():
    cfg = parse_cisco("vlan 10,20,30-32\n")
    assert [v.vlan_id for v in cfg.vlans] == [10, 20, 30, 31, 32]
    # No name applied when the line created several VLANs
    assert all(v.name is None for v in cfg.vlans)


def test_vlan_unknown_child_is_unmapped():
    cfg = parse_cisco("vlan 10\n name SALES\n private-vlan primary\n")
    assert cfg.vlans[0].name == "SALES"
    assert any("private-vlan" in u.text for u in cfg.unmapped)


def test_vlan_out_of_range_is_unmapped():
    cfg = parse_cisco("vlan 5000\n")
    assert cfg.vlans == []
    assert len(cfg.unmapped) >= 1


# --------------------------------------------------------------------------
# interface
# --------------------------------------------------------------------------


def test_interface_basic():
    cfg = parse_cisco(
        "interface GigabitEthernet0/0/1\n"
        " description UPLINK TO CORE\n"
        " no shutdown\n"
    )
    itf = cfg.interfaces[0]
    assert itf.if_type == "gigabit"
    assert itf.if_number == "0/0/1"
    assert itf.description == "UPLINK TO CORE"
    assert itf.admin_down is False


def test_interface_shutdown_tristate():
    assert parse_cisco("interface Gi0/1\n shutdown\n").interfaces[0].admin_down is True
    assert parse_cisco("interface Gi0/1\n no shutdown\n").interfaces[0].admin_down is False
    # Silent source must stay None -- never inferred
    assert parse_cisco("interface Gi0/1\n description X\n").interfaces[0].admin_down is None


def test_interface_ip_address():
    cfg = parse_cisco("interface Vlan10\n ip address 192.168.10.1 255.255.255.0\n")
    itf = cfg.interfaces[0]
    assert itf.if_type == "vlan"
    assert itf.if_number == "10"
    assert itf.ip_address == "192.168.10.1"
    assert itf.subnet_mask == "255.255.255.0"


def test_interface_access_port():
    cfg = parse_cisco(
        "interface Gi0/1\n switchport mode access\n switchport access vlan 10\n"
    )
    itf = cfg.interfaces[0]
    assert itf.link_type == LinkType.ACCESS
    assert itf.access_vlan == 10


def test_interface_trunk_port():
    cfg = parse_cisco(
        "interface Gi0/1\n"
        " switchport mode trunk\n"
        " switchport trunk allowed vlan 10,20,30-32\n"
        " switchport trunk native vlan 99\n"
    )
    itf = cfg.interfaces[0]
    assert itf.link_type == LinkType.TRUNK
    assert itf.trunk_allowed == {10, 20, 30, 31, 32}
    assert itf.trunk_native == 99


def test_interface_trunk_allowed_add_accumulates():
    cfg = parse_cisco(
        "interface Gi0/1\n"
        " switchport trunk allowed vlan 10,20\n"
        " switchport trunk allowed vlan add 30,40\n"
    )
    assert cfg.interfaces[0].trunk_allowed == {10, 20, 30, 40}


def test_interface_trunk_allowed_remove():
    cfg = parse_cisco(
        "interface Gi0/1\n"
        " switchport trunk allowed vlan 10,20,30\n"
        " switchport trunk allowed vlan remove 20\n"
    )
    assert cfg.interfaces[0].trunk_allowed == {10, 30}


def test_interface_abbreviated_names():
    for name, expect_type in [
        ("Gi0/1", "gigabit"),
        ("Te1/0/1", "tengigabit"),
        ("Fa0/1", "fast"),
        ("Lo0", "loopback"),
        ("Po1", "portchannel"),
    ]:
        cfg = parse_cisco(f"interface {name}\n description X\n")
        assert cfg.interfaces[0].if_type == expect_type, name


def test_interface_unknown_type_is_unmapped():
    cfg = parse_cisco("interface Serial0/0/0\n ip address 10.0.0.1 255.255.255.252\n")
    assert cfg.interfaces == []
    assert len(cfg.unmapped) == 2  # the interface line and its child


def test_interface_unknown_child_is_unmapped():
    cfg = parse_cisco(
        "interface Gi0/1\n description OK\n ip helper-address 10.1.1.1\n"
    )
    assert cfg.interfaces[0].description == "OK"
    assert any("helper-address" in u.text for u in cfg.unmapped)


def test_multiple_interfaces():
    cfg = parse_cisco(
        "interface Gi0/1\n description A\n"
        "interface Gi0/2\n description B\n"
        "interface Gi0/3\n description C\n"
    )
    assert len(cfg.interfaces) == 3
    assert [i.description for i in cfg.interfaces] == ["A", "B", "C"]


def test_find_interface():
    cfg = parse_cisco("interface Gi0/1\n description A\n")
    assert cfg.find_interface("gigabit", "0/1") is not None
    assert cfg.find_interface("gigabit", "9/9") is None


# --------------------------------------------------------------------------
# static routes
# --------------------------------------------------------------------------


def test_static_route():
    cfg = parse_cisco("ip route 10.0.0.0 255.0.0.0 192.168.1.254\n")
    rt = cfg.static_routes[0]
    assert rt.prefix == "10.0.0.0"
    assert rt.mask == "255.0.0.0"
    assert rt.next_hop == "192.168.1.254"
    assert rt.preference is None


def test_static_route_with_distance():
    cfg = parse_cisco("ip route 10.0.0.0 255.0.0.0 192.168.1.254 200\n")
    assert cfg.static_routes[0].preference == 200


def test_static_route_via_interface():
    cfg = parse_cisco("ip route 10.0.0.0 255.0.0.0 GigabitEthernet0/0/1\n")
    assert cfg.static_routes[0].next_hop == "GigabitEthernet0/0/1"


def test_other_ip_commands_unmapped():
    cfg = parse_cisco("ip nbar protocol-discovery\nip domain-name example.com\n")
    assert cfg.static_routes == []
    assert len(cfg.unmapped) == 2


def test_static_route_with_trailing_name_unmapped():
    cfg = parse_cisco("ip route 10.0.0.0 255.0.0.0 192.168.1.254 name BACKUP\n")
    assert cfg.static_routes == []
    assert len(cfg.unmapped) == 1


# --------------------------------------------------------------------------
# OSPF -- class S
# --------------------------------------------------------------------------


def test_ospf_basic():
    cfg = parse_cisco(
        "router ospf 1\n"
        " router-id 1.1.1.1\n"
        " network 10.0.0.0 0.0.0.255 area 0\n"
    )
    assert cfg.ospf is not None
    assert cfg.ospf.process_id == 1
    assert cfg.ospf.router_id == "1.1.1.1"
    assert list(cfg.ospf.areas.keys()) == [0]
    assert cfg.ospf.areas[0][0].address == "10.0.0.0"
    assert cfg.ospf.areas[0][0].wildcard == "0.0.0.255"


def test_ospf_networks_regrouped_by_area():
    """The class S transformation: networks group under their area."""
    cfg = parse_cisco(
        "router ospf 1\n"
        " router-id 1.1.1.1\n"
        " network 10.0.0.0 0.0.0.255 area 0\n"
        " network 10.1.0.0 0.0.0.255 area 0\n"
        " network 172.16.0.0 0.0.0.255 area 1\n"
    )
    areas = cfg.ospf.areas
    assert sorted(areas.keys()) == [0, 1]
    assert len(areas[0]) == 2
    assert len(areas[1]) == 1
    assert [n.address for n in areas[0]] == ["10.0.0.0", "10.1.0.0"]


def test_ospf_dotted_area_accepted():
    cfg = parse_cisco(
        "router ospf 1\n network 172.16.0.0 0.0.0.255 area 0.0.0.1\n"
    )
    assert list(cfg.ospf.areas.keys()) == [1]


def test_ospf_area_ordering_independent():
    """Areas out of order must still group correctly."""
    cfg = parse_cisco(
        "router ospf 1\n"
        " network 10.0.0.0 0.0.0.255 area 1\n"
        " network 10.1.0.0 0.0.0.255 area 0\n"
        " network 10.2.0.0 0.0.0.255 area 1\n"
    )
    assert len(cfg.ospf.areas[1]) == 2
    assert len(cfg.ospf.areas[0]) == 1


def test_ospf_no_router_id():
    cfg = parse_cisco("router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\n")
    assert cfg.ospf.router_id is None


def test_ospf_unsupported_child_unmapped():
    cfg = parse_cisco(
        "router ospf 1\n"
        " router-id 1.1.1.1\n"
        " passive-interface default\n"
        " redistribute connected subnets\n"
    )
    assert cfg.ospf.router_id == "1.1.1.1"
    assert len(cfg.unmapped) == 2


def test_second_ospf_process_unmapped():
    cfg = parse_cisco(
        "router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\n"
        "router ospf 2\n network 10.1.0.0 0.0.0.255 area 0\n"
    )
    assert cfg.ospf.process_id == 1
    assert any("router ospf 2" in u.text for u in cfg.unmapped)


def test_bgp_unmapped():
    cfg = parse_cisco("router bgp 65000\n neighbor 10.0.0.1 remote-as 65001\n")
    assert cfg.ospf is None
    assert len(cfg.unmapped) == 2


# --------------------------------------------------------------------------
# Whole-file behaviour
# --------------------------------------------------------------------------

FULL = """!
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
interface GigabitEthernet0/0/2
 description USER PORT
 switchport mode access
 switchport access vlan 10
!
interface Vlan10
 ip address 192.168.10.1 255.255.255.0
!
router ospf 1
 router-id 1.1.1.1
 network 192.168.10.0 0.0.0.255 area 0
!
ip route 0.0.0.0 0.0.0.0 192.168.10.254
!
ip nbar protocol-discovery
end
"""


def test_full_config():
    cfg = parse_cisco(FULL)
    assert cfg.hostname == "SW1"
    assert len(cfg.vlans) == 2
    assert len(cfg.interfaces) == 3
    assert len(cfg.static_routes) == 1
    assert cfg.ospf is not None
    # Only the nbar line should be unmapped
    assert len(cfg.unmapped) == 1
    assert "nbar" in cfg.unmapped[0].text


def test_line_accounting():
    cfg = parse_cisco(FULL)
    assert cfg.total_lines == len(FULL.splitlines())
    assert cfg.significant_lines < cfg.total_lines
    assert cfg.significant_lines > 0


def test_empty_config():
    cfg = parse_cisco("")
    assert cfg.hostname is None
    assert cfg.vlans == []
    assert cfg.interfaces == []
    assert cfg.unmapped == []


def test_comments_only():
    cfg = parse_cisco("!\n! just comments\n!\n")
    assert cfg.unmapped == []
    assert cfg.significant_lines == 0


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