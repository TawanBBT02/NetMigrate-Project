"""
Rule catalog: the single source of truth for Appendix A of the thesis.

Why this exists
---------------
Appendix A must list every translation rule with its command forms, its
class, and its verification status. Hand-writing that table guarantees it
drifts from the code the first time a rule changes. Instead the table lives
here as data, `tools/make_appendix.py` renders it, and
`tests/test_catalog.py` asserts that the catalog and the renderers agree —
so a rule added to the code without a catalog entry fails the test suite.

Verification status
-------------------
    DOC    confirmed against an official vendor command reference
    EX     confirmed by an official vendor configuration example
    SIM    loaded successfully in a device simulator
    UNVER  not yet verified against a primary source

UNVER is not a claim. Any rule still UNVER at submission must be named in
Chapter 5 as an unverified mapping, not presented as validated.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str          # grouping for the appendix table
    cisco: str             # Cisco IOS-XE command form
    huawei: str            # Huawei VRP command form
    rule_class: str        # D | T | S
    status: str            # DOC | EX | SIM | UNVER
    reference: str         # short reference key, see REFERENCES
    note: str = ""


REFERENCES: dict[str, str] = {
    "H-VLAN": (
        "Configuring Interface-based VLAN Assignment — CloudEngine S5700/S6700 "
        "V600R022C00 Configuration Guide, Ethernet Switching. "
        "support.huawei.com/enterprise/en/doc/EDOC1100278261/c213d155"
    ),
    "H-ROUTE": (
        "ip route-static — S1700/S2720/S5700/S6700 V200R020C00 Command "
        "Reference. support.huawei.com/enterprise/en/doc/EDOC1100176877/ac7caed7"
    ),
    "H-IFBASE": (
        "Basic Interface Configuration Commands — S1700/S2720/S5700/S6700 "
        "V200R019C10 Command Reference. "
        "support.huawei.com/enterprise/en/doc/EDOC1100127035/cdd85713"
    ),
    "H-ETH": (
        "Eth-Trunk Interface Configuration — NE5000E V800R022C00SPC500 "
        "Configuration Guide. "
        "support.huawei.com/enterprise/en/doc/EDOC1100278760/20c76fcd"
    ),
    "H-EX-VLAN": (
        "Typical VLAN Configuration — S300/S500/S2700/S3700/S5700/S6700/"
        "S7700/S9700 Typical Configuration Examples (V200). "
        "support.huawei.com/enterprise/en/doc/EDOC1000069520/b699322c"
    ),
    "H-EX-OSPF": (
        "Typical OSPF Configuration — same series, Typical Configuration "
        "Examples. support.huawei.com/enterprise/en/doc/EDOC1000069520/a25a2d1a"
    ),
    "H-VLANCMD": (
        "VLAN Configuration Commands — S5700/S6700 V200R025C00 Command "
        "Reference (NOT YET READ). "
        "support.huawei.com/enterprise/en/doc/EDOC1100514211/834147df"
    ),
    "-": "(no primary reference yet)",
}


CATALOG: tuple[Rule, ...] = (
    # ---- system level ----------------------------------------------------
    Rule(
        "system.hostname", "ระดับระบบ",
        "hostname SW1", "sysname SW1",
        "D", "EX", "H-EX-VLAN",
        "ปรากฏในไฟล์กำหนดค่าตัวอย่างของ Huawei ในรูป `# sysname SwitchA`",
    ),

    # ---- VLAN ------------------------------------------------------------
    Rule(
        "vlan.create", "VLAN",
        "vlan 10", "vlan 10",
        "D", "DOC", "H-VLAN",
        "Cisco รองรับ `vlan 10,20,30-35` ซึ่งระบบขยายเป็นบล็อกแยกรายการ; "
        "Huawei รองรับ `vlan batch` ซึ่งระบบขยายเช่นเดียวกัน",
    ),
    Rule(
        "vlan.name", "VLAN",
        "name SALES", "name SALES",
        "D", "UNVER", "H-VLANCMD",
        "**ยังไม่ยืนยัน** — ไม่ปรากฏในไฟล์ตัวอย่างทั้งสองฉบับ ต้องเปิดเอกสาร "
        "H-VLANCMD เพื่อยืนยัน",
    ),

    # ---- interface -------------------------------------------------------
    Rule(
        "interface.name", "Interface",
        "interface GigabitEthernet0/0/1", "interface GE0/0/1",
        "D", "EX", "H-EX-OSPF",
        "แปลงเฉพาะส่วนประเภท คงส่วนตัวเลขไว้ตามเดิม (ดูข้อจำกัด 2.3.2.4)",
    ),
    Rule(
        "interface.description", "Interface",
        "description UPLINK", "description UPLINK",
        "D", "UNVER", "-",
        "**ยังไม่ยืนยัน** — รูปแบบเหมือนกันทั้งสองผู้ผลิต ความเสี่ยงต่ำ",
    ),
    Rule(
        "interface.ip", "Interface",
        "ip address 10.0.0.1 255.255.255.0",
        "ip address 10.0.0.1 255.255.255.0",
        "T", "EX", "H-EX-OSPF",
        "Huawei รับรูปแบบความยาว Prefix ด้วย (`ip address 10.0.0.1 24`) "
        "ระบบรับทั้งสองรูปแบบเป็นข้อมูลเข้า และสร้างรูปแบบ Subnet Mask เป็นผลลัพธ์",
    ),
    Rule(
        "interface.shutdown", "Interface",
        "shutdown / no shutdown", "shutdown / undo shutdown",
        "D", "EX", "H-ETH",
        "ค่าสามสถานะ: หากไฟล์ต้นทางไม่ระบุ ระบบไม่สร้างคำสั่งใด "
        "เพราะค่าเริ่มต้นของผู้ผลิตไม่ตรงกัน",
    ),

    # ---- switchport / port link-type -------------------------------------
    Rule(
        "port.link-type", "รูปแบบพอร์ต",
        "switchport mode access | trunk", "port link-type access | trunk",
        "D", "DOC", "H-VLAN",
        "`port link-type hybrid` ของ Huawei อยู่นอกขอบเขต",
    ),
    Rule(
        "port.access-vlan", "รูปแบบพอร์ต",
        "switchport access vlan 10", "port default vlan 10",
        "D", "DOC", "H-VLAN", "",
    ),
    Rule(
        "port.trunk-allowed", "รูปแบบพอร์ต",
        "switchport trunk allowed vlan 10,20,30-35",
        "port trunk allow-pass vlan 10 20 30 to 35",
        "T", "DOC", "H-VLAN",
        "เอกสารกำหนดรูปแบบเป็น `&<1-40>` คือสูงสุด 40 องค์ประกอบต่อคำสั่ง "
        "โดยช่วงนับเป็นหนึ่งองค์ประกอบ ระบบแบ่งเป็นหลายคำสั่งเมื่อเกิน; "
        "`allow-pass vlan all` อยู่นอกขอบเขต",
    ),
    Rule(
        "port.trunk-native", "รูปแบบพอร์ต",
        "switchport trunk native vlan 99", "port trunk pvid vlan 99",
        "D", "DOC", "H-VLAN", "",
    ),

    # ---- static routing --------------------------------------------------
    Rule(
        "route.static", "การจัดเส้นทางคงที่",
        "ip route 10.0.0.0 255.0.0.0 192.168.1.1 [200]",
        "ip route-static 10.0.0.0 255.0.0.0 192.168.1.1 [preference 200]",
        "T", "DOC", "H-ROUTE",
        "Cisco รับค่า Administrative Distance เป็นจำนวนเต็มต่อท้าย VRP ต้องใช้ "
        "คำสำคัญ `preference`; **ค่าเริ่มต้นไม่เท่ากัน** (Cisco 1, VRP 60) "
        "ระบบจึงแจ้งเตือนหนึ่งครั้งต่อไฟล์เมื่อมีเส้นทางที่อาศัยค่าเริ่มต้น",
    ),

    # ---- OSPF — class S --------------------------------------------------
    Rule(
        "ospf.process", "OSPF",
        "router ospf 1", "ospf 1 router-id 1.1.1.1",
        "S", "EX", "H-EX-OSPF",
        "VRP บรรจุ router-id บนบรรทัดประกาศ Process",
    ),
    Rule(
        "ospf.router-id", "OSPF",
        "router-id 1.1.1.1 (บรรทัดลูก)", "(อยู่บนบรรทัด ospf)",
        "S", "EX", "H-EX-OSPF",
        "รหัสกฎนี้ปรากฏเฉพาะในตัวสร้างไฟล์ฝั่ง Cisco ตามความไม่สมมาตรเชิงโครงสร้าง",
    ),
    Rule(
        "ospf.area", "OSPF",
        "(เป็นอาร์กิวเมนต์ท้ายบรรทัด network)", "area 0.0.0.0 (บล็อกแม่)",
        "S", "EX", "H-EX-OSPF",
        "รหัสกฎนี้ปรากฏเฉพาะในตัวสร้างไฟล์ฝั่ง Huawei; หมายเลข Area แปลงระหว่าง "
        "จำนวนเต็มและเลขฐานสิบแบบมีจุด โดย `area 1` คือ `0.0.0.1`",
    ),
    Rule(
        "ospf.network", "OSPF",
        "network 10.0.0.0 0.0.0.255 area 0", "network 10.0.0.0 0.0.0.255",
        "S", "EX", "H-EX-OSPF",
        "ต้องจัดกลุ่มตาม Area จึงไม่สามารถสร้างผลลัพธ์ได้จนอ่านบล็อกจนจบ",
    ),
)


# --------------------------------------------------------------------------
# Interface type mapping (separate table in the appendix)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class InterfaceType:
    canonical: str
    cisco: str
    cisco_abbrev: str
    huawei: str
    status: str
    reference: str


INTERFACE_TYPE_CATALOG: tuple[InterfaceType, ...] = (
    InterfaceType("gigabit", "GigabitEthernet", "Gi", "GE", "EX", "H-EX-OSPF"),
    InterfaceType("tengigabit", "TenGigabitEthernet", "Te", "XGE",
                  "DOC", "H-IFBASE"),
    InterfaceType("fast", "FastEthernet", "Fa", "Ethernet", "UNVER", "-"),
    InterfaceType("loopback", "Loopback", "Lo", "LoopBack", "UNVER", "-"),
    InterfaceType("vlan", "Vlan", "Vl", "Vlanif", "EX", "H-EX-OSPF"),
    InterfaceType("portchannel", "Port-channel", "Po", "Eth-Trunk",
                  "EX", "H-ETH"),
    InterfaceType("null", "Null", "Nu", "NULL", "EX", "H-EX-OSPF"),
)


# --------------------------------------------------------------------------
# Deliberate rejections (also an appendix table)
# --------------------------------------------------------------------------

REJECTIONS: tuple[tuple[str, str], ...] = (
    ("port trunk allow-pass vlan all",
     "ไม่สามารถแสดงเป็นรายการ VLAN ที่ระบุชัดเจนของ Cisco ในขอบเขตได้"),
    ("port link-type hybrid",
     "ไม่มีคำสั่งเทียบเคียงใน Cisco ภายในขอบเขต"),
    ("ip route-static ... 150 (ไม่มีคำสำคัญ preference)",
     "ไม่ใช่ไวยากรณ์ที่ถูกต้องของ VRP"),
    ("ip route ... name BACKUP",
     "หากแปลงจะทิ้งชื่อเส้นทางโดยไม่แจ้งผู้ใช้"),
    ("vlan 10,20 พร้อมคำสั่ง name",
     "ชื่อเดียวไม่สามารถใช้กับ VLAN หลายรายการได้"),
    ("enable secret / local-user password (ข้อมูลรหัสผ่าน)",
     "ค่าแฮชเป็นฟังก์ชันทางเดียวและต่างอัลกอริทึม ไม่มีการแปลงในทางหลักการ"),
    ("interface Serial / Tunnel / ATM",
     "ประเภท Interface อยู่นอกขอบเขต"),
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def rule_ids() -> set[str]:
    return {r.rule_id for r in CATALOG}


def by_category() -> dict[str, list[Rule]]:
    grouped: dict[str, list[Rule]] = {}
    for rule in CATALOG:
        grouped.setdefault(rule.category, []).append(rule)
    return grouped


def status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule in CATALOG:
        counts[rule.status] = counts.get(rule.status, 0) + 1
    for itype in INTERFACE_TYPE_CATALOG:
        counts[itype.status] = counts.get(itype.status, 0) + 1
    return counts


def conformance() -> float:
    """H3b: proportion of catalogued items carrying primary evidence."""
    counts = status_counts()
    total = sum(counts.values())
    evidenced = counts.get("DOC", 0) + counts.get("EX", 0) + counts.get("SIM", 0)
    return evidenced / total if total else 0.0
