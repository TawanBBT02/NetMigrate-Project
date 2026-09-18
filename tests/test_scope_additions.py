"""Tests for the scope additions of 17 Sep: VLAN limit, Null0, undo
allow-pass, and credential handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate import transforms as tf  # noqa: E402
from netmigrate.engine import convert  # noqa: E402
from netmigrate.ir import Vendor  # noqa: E402
from netmigrate.rules_cisco import parse_cisco  # noqa: E402
from netmigrate.rules_huawei import parse_huawei  # noqa: E402
from netmigrate.validation import ir_equal, round_trip  # noqa: E402

C, H = Vendor.CISCO, Vendor.HUAWEI


def to_huawei(t: str) -> str:
    return convert(t, C, H).output_text


def to_cisco(t: str) -> str:
    return convert(t, H, C).output_text


# --------------------------------------------------------------------------
# VLAN element limit (&<1-40>)
# --------------------------------------------------------------------------


def test_short_list_is_one_command():
    assert tf.split_vlan_list_huawei({10, 20, 30}) == ["10 20 30"]


def test_exactly_forty_elements_is_one_command():
    ids = set(range(1, 81, 2))  # 40 discrete, non-contiguous
    assert len(tf.split_vlan_list_huawei(ids)) == 1


def test_forty_one_elements_splits():
    ids = set(range(1, 83, 2))  # 41 discrete
    parts = tf.split_vlan_list_huawei(ids)
    assert len(parts) == 2
    assert len(parts[0].split()) == 40
    assert len(parts[1].split()) == 1


def test_range_counts_as_one_element_not_many():
    """10 to 200 is 191 VLANs but a single syntax element."""
    parts = tf.split_vlan_list_huawei(set(range(10, 201)))
    assert parts == ["10 to 200"]


def test_mixed_ranges_and_singles_counted_by_element():
    # 30 ranges of 3 + 30 singles = 60 elements -> 2 commands
    ids: set[int] = set()
    for i in range(30):
        base = 100 + i * 10
        ids.update({base, base + 1, base + 2})
    ids.update(range(1, 60, 2))
    parts = tf.split_vlan_list_huawei(ids)
    assert len(parts) == 2
    assert all(len(p.split()) <= 40 * 3 for p in parts)


def test_split_preserves_every_vlan():
    ids = set(range(1, 200, 2))  # 100 discrete
    parts = tf.split_vlan_list_huawei(ids)
    recovered: set[int] = set()
    for part in parts:
        recovered |= tf.parse_vlan_list_huawei(part)
    assert recovered == ids


def test_empty_set_yields_no_commands():
    assert tf.split_vlan_list_huawei(set()) == []


def test_renderer_emits_multiple_allow_pass_lines():
    vl = ",".join(str(v) for v in range(1, 91, 2))  # 45 discrete
    out = to_huawei(
        f"interface Gi0/1\n switchport mode trunk\n"
        f" switchport trunk allowed vlan {vl}\n"
    )
    lines = [ln for ln in out.splitlines() if "allow-pass" in ln]
    assert len(lines) == 2, lines
    for ln in lines:
        elements = ln.split("vlan", 1)[1].split()
        assert len(elements) <= 40


def test_long_list_round_trips_through_split():
    vl = ",".join(str(v) for v in range(1, 121, 2))  # 60 discrete
    src = (
        f"interface Gi0/1\n switchport mode trunk\n"
        f" switchport trunk allowed vlan {vl}\n"
    )
    report = round_trip(src, C, H)
    assert report.ok, report.differences


# --------------------------------------------------------------------------
# Null interface
# --------------------------------------------------------------------------


def test_null_interface_type_mapping():
    key = tf.canonical_interface_type("Null0")
    assert key == "null"
    assert tf.render_interface_type(key, "cisco") == "Null"
    assert tf.render_interface_type(key, "huawei") == "NULL"


def test_null_route_cisco_to_huawei():
    out = to_huawei("ip route 172.16.0.0 255.255.0.0 Null0\n")
    assert "ip route-static 172.16.0.0 255.255.0.0 NULL0" in out


def test_null_route_huawei_to_cisco():
    """Huawei's own OSPF example contains 'ip route-static ... NULL0'."""
    out = to_cisco("ip route-static 172.16.0.0 255.255.0.0 NULL0\n")
    assert "ip route 172.16.0.0 255.255.0.0 Null0" in out


def test_null_route_round_trips():
    assert round_trip("ip route 10.0.0.0 255.0.0.0 Null0\n", C, H).ok


def test_null_case_insensitive_on_input():
    for spelling in ("Null0", "NULL0", "null0", "Nu0"):
        cfg = parse_cisco(f"ip route 10.0.0.0 255.0.0.0 {spelling}\n")
        assert cfg.static_routes, spelling


# --------------------------------------------------------------------------
# undo port trunk allow-pass
# --------------------------------------------------------------------------


def test_undo_allow_pass_removes_vlans():
    cfg = parse_huawei(
        "interface GE0/0/1\n"
        " port link-type trunk\n"
        " port trunk allow-pass vlan 10 20 30\n"
        " undo port trunk allow-pass vlan 20\n"
    )
    assert cfg.interfaces[0].trunk_allowed == {10, 30}


def test_undo_default_vlan_before_allow_is_noop():
    """The common real-world ordering. VLAN 1 was never explicitly allowed,
    so removing it changes nothing in our explicit-allow model."""
    cfg = parse_huawei(
        "interface GE0/0/1\n"
        " port link-type trunk\n"
        " undo port trunk allow-pass vlan 1\n"
        " port trunk allow-pass vlan 166 200\n"
    )
    assert cfg.interfaces[0].trunk_allowed == {166, 200}
    assert not [u for u in cfg.unmapped if "allow-pass" in u.text]


def test_undo_allow_pass_all_clears_set():
    cfg = parse_huawei(
        "interface GE0/0/1\n"
        " port trunk allow-pass vlan 10 20\n"
        " undo port trunk allow-pass vlan all\n"
    )
    assert cfg.interfaces[0].trunk_allowed == set()


def test_undo_allow_pass_range():
    cfg = parse_huawei(
        "interface GE0/0/1\n"
        " port trunk allow-pass vlan 10 to 20\n"
        " undo port trunk allow-pass vlan 15 to 20\n"
    )
    assert cfg.interfaces[0].trunk_allowed == {10, 11, 12, 13, 14}


# --------------------------------------------------------------------------
# Credentials -- never converted, always flagged with guidance
# --------------------------------------------------------------------------


def test_credential_detection():
    assert tf.is_credential_line("enable secret 5 $1$abc")
    assert tf.is_credential_line("username admin privilege 15 secret 9 $9$x")
    assert tf.is_credential_line("local-user admin password irreversible-cipher x")
    assert tf.is_credential_line("authentication-mode aaa")
    assert not tf.is_credential_line("interface GigabitEthernet0/0/1")
    assert not tf.is_credential_line("vlan 10")
    assert not tf.is_credential_line("ip route 10.0.0.0 255.0.0.0 10.0.0.1")


def test_cisco_credentials_categorised():
    cfg = parse_cisco("enable secret 5 $1$mERr$H2s\n")
    assert cfg.unmapped[0].category == "credential"


def test_huawei_credentials_categorised():
    cfg = parse_huawei(
        "aaa\n local-user admin password irreversible-cipher $1c$K\n"
    )
    assert any(u.category == "credential" for u in cfg.unmapped)


def test_credential_never_appears_uncommented():
    """The safety invariant: no hash may reach the config body."""
    for src, fn in (
        ("enable secret 5 $1$mERr$H2s\nusername bob secret 9 $9$xyz\n", to_huawei),
        ("aaa\n local-user bob password irreversible-cipher $1c$K\n", to_cisco),
    ):
        out = fn(src)
        marker = "#" if fn is to_huawei else "!"
        for line in out.splitlines():
            if "$" in line:
                assert line.lstrip().startswith(marker), line


def test_credential_guidance_emitted_for_target_vendor():
    out = to_huawei("enable secret 5 $1$mERr$H2s\n")
    assert "irreversible-cipher" in out
    assert "<PLAINTEXT>" in out

    out = to_cisco("aaa\n local-user bob password irreversible-cipher $1c$K\n")
    assert "enable secret" in out
    assert "<PLAINTEXT>" in out


def test_no_guidance_for_ordinary_unmapped():
    out = to_huawei("ip nbar protocol-discovery\n")
    assert "PLAINTEXT" not in out
    assert "Password hashes" not in out


def test_credentials_count_as_unmapped_not_rule():
    result = convert("hostname SW1\nenable secret 5 $1$abc\n", C, H)
    assert result.unmapped_lines == 1
    assert result.rule_coverage < 1.0


def test_credential_lines_do_not_break_round_trip():
    """Credentials survive as comments, which is counted, not a fidelity fail."""
    report = round_trip("hostname SW1\nenable secret 5 $1$abc\n", C, H)
    assert report.ok
    assert report.unmapped_lines == 1


# --------------------------------------------------------------------------
# Static route default preference divergence
# --------------------------------------------------------------------------


def test_preference_warning_when_default_relied_on():
    """Cisco static default AD is 1; VRP static default preference is 60.
    An unqualified route therefore changes precedence across vendors."""
    out = to_huawei("ip route 0.0.0.0 0.0.0.0 10.0.0.1\n")
    assert "preference/distance" in out
    assert "administrative distance 1" in out
    assert "preference 60" in out


def test_no_warning_when_preference_explicit():
    out = to_huawei("ip route 172.16.0.0 255.255.0.0 10.0.0.2 200\n")
    assert "preference/distance" not in out
    assert "preference 200" in out


def test_warning_emitted_once_not_per_route():
    out = to_huawei(
        "ip route 10.0.0.0 255.0.0.0 10.0.0.1\n"
        "ip route 11.0.0.0 255.0.0.0 10.0.0.1\n"
        "ip route 12.0.0.0 255.0.0.0 10.0.0.1\n"
    )
    assert out.count("preference/distance") == 1


def test_warning_both_directions():
    out = to_cisco("ip route-static 0.0.0.0 0.0.0.0 10.0.0.1\n")
    assert "preference/distance" in out


def test_warning_is_a_comment_not_config():
    out = to_huawei("ip route 0.0.0.0 0.0.0.0 10.0.0.1\n")
    for line in out.splitlines():
        if "preference/distance" in line:
            assert line.lstrip().startswith("#")


def test_warning_does_not_affect_coverage_or_fidelity():
    src = "ip route 0.0.0.0 0.0.0.0 10.0.0.1\n"
    result = convert(src, C, H)
    assert result.unmapped_lines == 0
    assert round_trip(src, C, H).ok


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
