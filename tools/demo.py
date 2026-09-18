#!/usr/bin/env python3
"""
สคริปต์สาธิตการทำงานของระบบ NetMigrate แบบครบวงจร

ใช้สำหรับนำเสนออาจารย์ที่ปรึกษาและคณะกรรมการ แสดงให้เห็น
(1) ไฟล์ต้นทาง (2) ไฟล์ผลลัพธ์ (3) แหล่งที่มาของการแปลงรายบรรทัด
(4) ค่าตัวชี้วัด และ (5) ผลการทดสอบแปลงกลับ ในหน้าจอเดียว

ใช้งาน:
    python tools/demo.py                        # ใช้ไฟล์ตัวอย่างในตัว
    python tools/demo.py corpus/cisco/sw01-access.cfg
    python tools/demo.py <ไฟล์> --to cisco      # กำหนดปลายทาง
    python tools/demo.py <ไฟล์> --provenance    # แสดงตารางแหล่งที่มารายบรรทัด
    python tools/demo.py --ospf                 # สาธิตเฉพาะการแปลง OSPF

ทิศทางการแปลงตรวจจับจากเนื้อหาไฟล์โดยอัตโนมัติ ถ้าไม่ระบุ --to
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from netmigrate.engine import convert  # noqa: E402
from netmigrate.ir import Provenance, Vendor  # noqa: E402
from netmigrate.validation import round_trip  # noqa: E402

LABEL = {Vendor.CISCO: "Cisco IOS-XE", Vendor.HUAWEI: "Huawei VRP"}
SHORT = {"cisco": Vendor.CISCO, "huawei": Vendor.HUAWEI}

WIDTH = 78

# ตัวอย่างในตัว เลือกมาเพราะครอบคลุมกฎทั้งสามประเภท D / T / S
SAMPLE = """!
hostname DEMO-SW
!
vlan 10
 name SALES
!
interface GigabitEthernet0/0/1
 description UPLINK TO CORE
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30-35
 switchport trunk native vlan 99
 no shutdown
!
interface Vlan10
 ip address 192.168.10.1 255.255.255.0
!
router ospf 1
 router-id 1.1.1.1
 network 192.168.10.0 0.0.0.255 area 0
 network 172.16.0.0 0.0.0.255 area 5
!
ip route 0.0.0.0 0.0.0.0 192.168.10.254
!
enable secret 5 $1$mERr$H2sPqRtUvWxYz
!
ip nbar protocol-discovery
!
end
"""

OSPF_SAMPLE = """!
router ospf 1
 router-id 1.1.1.1
 network 10.0.0.0 0.0.0.255 area 0
 network 10.1.0.0 0.0.0.255 area 0
 network 172.16.0.0 0.0.0.255 area 1
!
end
"""


def rule(title: str = "") -> None:
    if title:
        print()
        print("=" * WIDTH)
        print(f" {title}")
        print("=" * WIDTH)
    else:
        print("-" * WIDTH)


def detect_vendor(text: str) -> Vendor:
    """เดาผู้ผลิตต้นทางจากคำสั่งที่พบ"""
    lowered = text.lower()
    huawei_markers = ("sysname", "port link-type", "undo shutdown",
                      "ip route-static", "vlan batch", "allow-pass")
    cisco_markers = ("hostname", "switchport", "no shutdown", "ip route ")
    h = sum(m in lowered for m in huawei_markers)
    c = sum(m in lowered for m in cisco_markers)
    return Vendor.HUAWEI if h > c else Vendor.CISCO


def side_by_side(left: str, right: str, lhead: str, rhead: str) -> None:
    """แสดงต้นทางและผลลัพธ์เทียบกันสองคอลัมน์"""
    col = (WIDTH - 3) // 2
    llines = left.splitlines()
    rlines = right.splitlines()
    print(f"{lhead[:col]:<{col}} | {rhead[:col]:<{col}}")
    print(f"{'-' * col}-+-{'-' * col}")
    for i in range(max(len(llines), len(rlines))):
        a = llines[i][:col] if i < len(llines) else ""
        b = rlines[i][:col] if i < len(rlines) else ""
        print(f"{a:<{col}} | {b}")


def show_provenance(result) -> None:
    """ตารางแหล่งที่มาของการแปลงรายบรรทัด"""
    rule("แหล่งที่มาของการแปลงรายบรรทัด (per-line provenance)")
    print(f"{'บรรทัด':>6}  {'แหล่งที่มา':<11} {'กฎ':<22} {'ตรวจสอบ':<9} ข้อความ")
    print("-" * WIDTH)
    for line in result.lines:
        if line.provenance is Provenance.GENERATED and not line.needs_review:
            continue
        src = str(line.source_line) if line.source_line else "-"
        review = "ต้องตรวจ" if line.needs_review else ""
        print(f"{src:>6}  {line.provenance.value:<11} "
              f"{(line.rule_id or '-'):<22} {review:<9} {line.text[:24]}")


def show_metrics(result) -> None:
    rule("ค่าตัวชี้วัด")
    m = result.to_dict()["metrics"]
    rows = [
        ("บรรทัดทั้งหมด", m["total_lines"]),
        ("บรรทัดที่มีนัยสำคัญ (ตัวส่วน)", m["significant_lines"]),
        ("แปลงด้วย Rule Engine", m["rule_lines"]),
        ("แปลงด้วย AI (คำแนะนำ)", m["ai_lines"]),
        ("ไม่มีกฎรองรับ", m["unmapped_lines"]),
        ("ความครอบคลุมของกฎ (H1)", f"{m['rule_coverage']:.1%}"),
        ("เวลาที่ใช้", f"{m['duration_ms']:.3f} ms"),
    ]
    for label, value in rows:
        print(f"  {label:<34} {value}")


def run_demo(text: str, source: Vendor, target: Vendor, provenance: bool) -> None:
    rule(f"NetMigrate — สาธิตการแปลง {LABEL[source]} → {LABEL[target]}")

    result = convert(text, source, target)

    rule("เปรียบเทียบไฟล์ต้นทางและผลลัพธ์")
    side_by_side(text, result.output_text,
                 f"ต้นทาง: {LABEL[source]}",
                 f"ผลลัพธ์: {LABEL[target]}")

    show_metrics(result)

    if provenance:
        show_provenance(result)

    rule("ผลการทดสอบแปลงกลับ (H2 — เทียบที่ระดับ IR ไม่ใช่ข้อความ)")
    report = round_trip(text, source, target)
    if report.skipped:
        print(f"  ข้าม: {report.reason}")
    elif report.ok:
        print(f"  ผ่าน — แปลง {LABEL[source]} → {LABEL[target]} → "
              f"{LABEL[source]} แล้วได้เจตนาการตั้งค่าเดิมครบถ้วน")
        print(f"  (ข้อความต่างกันได้ เช่น # กับ ! หรือลำดับบล็อก "
              f"แต่ความหมายไม่เปลี่ยน)")
    else:
        print(f"  ไม่ผ่าน — พบความแตกต่าง {len(report.differences)} จุด")
        for diff in report.differences[:10]:
            print(f"    {diff}")

    rule()
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="สาธิตการทำงานของ NetMigrate")
    ap.add_argument("path", nargs="?", help="ไฟล์กำหนดค่าต้นทาง")
    ap.add_argument("--to", choices=["cisco", "huawei"],
                    help="ผู้ผลิตปลายทาง (ค่าเริ่มต้น: ตรงข้ามกับต้นทาง)")
    ap.add_argument("--provenance", action="store_true",
                    help="แสดงตารางแหล่งที่มารายบรรทัด")
    ap.add_argument("--ospf", action="store_true",
                    help="สาธิตเฉพาะการแปลง OSPF (กฎประเภท S)")
    args = ap.parse_args()

    if args.ospf:
        text = OSPF_SAMPLE
    elif args.path:
        path = Path(args.path)
        if not path.is_file():
            print(f"ไม่พบไฟล์: {path}")
            return 1
        text = path.read_text(encoding="utf-8")
    else:
        text = SAMPLE

    source = detect_vendor(text)
    if args.to:
        target = SHORT[args.to]
        if target is source:
            source = (Vendor.CISCO if target is Vendor.HUAWEI
                      else Vendor.HUAWEI)
    else:
        target = (Vendor.HUAWEI if source is Vendor.CISCO else Vendor.CISCO)

    run_demo(text, source, target, args.provenance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
