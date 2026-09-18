#!/usr/bin/env python3
"""
สร้างภาคผนวก ก (ตารางกฎการแปลงคำสั่ง) จาก netmigrate/rule_catalog.py

ใช้งาน:
    python tools/make_appendix.py                   # แสดงผลทางหน้าจอ
    python tools/make_appendix.py -o docs/appendix-a.md

ภาคผนวก ก ถูกสร้างจากข้อมูลในโค้ด ไม่ได้เขียนด้วยมือ ทำให้ตารางในปริญญานิพนธ์
ไม่คลาดเคลื่อนจากระบบที่พัฒนาจริง ชุดทดสอบ tests/test_catalog.py กำกับไว้ว่า
กฎที่ปรากฏในโค้ดต้องมีรายการในแคตาล็อก และกลับกัน
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from netmigrate import rule_catalog as cat  # noqa: E402

CLASS_LABEL = {
    "D": "D (แทนที่ตรง)",
    "T": "T (แปลงอาร์กิวเมนต์)",
    "S": "S (เปลี่ยนโครงสร้าง)",
}

STATUS_LABEL = {
    "DOC": "ยืนยันแล้ว (เอกสารอ้างอิงคำสั่ง)",
    "EX": "ยืนยันแล้ว (ตัวอย่างการกำหนดค่าของผู้ผลิต)",
    "SIM": "ยืนยันแล้ว (โปรแกรมจำลองอุปกรณ์)",
    "UNVER": "ยังไม่ยืนยัน",
}

CATEGORY_ORDER = [
    "ระดับระบบ", "VLAN", "Interface", "รูปแบบพอร์ต",
    "การจัดเส้นทางคงที่", "OSPF",
]


def render() -> str:
    out: list[str] = []
    w = out.append

    w("# ภาคผนวก ก")
    w("# ตารางกฎการแปลงคำสั่งระหว่าง Cisco IOS-XE และ Huawei VRP")
    w("")
    w("> เอกสารนี้สร้างขึ้นโดยอัตโนมัติจาก `netmigrate/rule_catalog.py`")
    w("> ด้วยคำสั่ง `python tools/make_appendix.py` — ห้ามแก้ไขด้วยมือ")
    w("> หากต้องการแก้ไขให้แก้ที่แคตาล็อกในโค้ดแล้วสร้างใหม่")
    w("")

    # ---- summary ---------------------------------------------------------
    counts = cat.status_counts()
    total = sum(counts.values())
    evidenced = (counts.get("DOC", 0) + counts.get("EX", 0)
                 + counts.get("SIM", 0))

    w("## ก.1 สรุปภาพรวม")
    w("")
    w("| รายการ | จำนวน |")
    w("|---|---|")
    w(f"| กฎการแปลงคำสั่ง | {len(cat.CATALOG)} |")
    w(f"| ประเภท Interface ที่รองรับ | {len(cat.INTERFACE_TYPE_CATALOG)} |")
    w(f"| รายการที่ยืนยันกับเอกสารผู้ผลิตแล้ว | {evidenced} จาก {total} "
      f"({evidenced / total:.0%}) |")
    w(f"| รายการที่ยังไม่ยืนยัน | {counts.get('UNVER', 0)} |")
    w("")

    classes: dict[str, int] = {}
    for rule in cat.CATALOG:
        classes[rule.rule_class] = classes.get(rule.rule_class, 0) + 1
    w("**สัดส่วนตามประเภทของกฎ**")
    w("")
    w("| ประเภท | จำนวน | สัดส่วน |")
    w("|---|---|---|")
    for key in ("D", "T", "S"):
        n = classes.get(key, 0)
        w(f"| {CLASS_LABEL[key]} | {n} | {n / len(cat.CATALOG):.0%} |")
    w("")
    w("> กฎประเภท S คือกฎที่สถาปัตยกรรมแบบแทนที่รายบรรทัดไม่สามารถแสดงออกได้")
    w("> และเป็นเหตุผลที่ระบบต้องใช้โครงสร้างข้อมูลกลาง (ดูหัวข้อ 3.2.3)")
    w("")

    # ---- rules by category ----------------------------------------------
    w("## ก.2 ตารางกฎการแปลงคำสั่ง")
    w("")
    grouped = cat.by_category()
    for index, category in enumerate(CATEGORY_ORDER, start=1):
        rules = grouped.get(category)
        if not rules:
            continue
        w(f"### ก.2.{index} {category}")
        w("")
        w("| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |")
        w("|---|---|---|---|---|---|")
        for rule in rules:
            status = "ยืนยันแล้ว" if rule.status != "UNVER" else "**ยังไม่ยืนยัน**"
            ref = rule.reference if rule.reference != "-" else "—"
            w(f"| `{rule.rule_id}` | `{rule.cisco}` | `{rule.huawei}` | "
              f"{rule.rule_class} | {status} ({rule.status}) | {ref} |")
        w("")
        notes = [r for r in rules if r.note]
        if notes:
            w("**หมายเหตุ**")
            w("")
            for rule in notes:
                w(f"- `{rule.rule_id}` — {rule.note}")
            w("")

    # ---- interface types -------------------------------------------------
    w("## ก.3 ตารางแปลงชื่อประเภท Interface")
    w("")
    w("| ชื่อภายในระบบ | Cisco (เต็ม) | Cisco (ย่อ) | Huawei | สถานะ | อ้างอิง |")
    w("|---|---|---|---|---|---|")
    for itype in cat.INTERFACE_TYPE_CATALOG:
        status = "ยืนยันแล้ว" if itype.status != "UNVER" else "**ยังไม่ยืนยัน**"
        ref = itype.reference if itype.reference != "-" else "—"
        w(f"| `{itype.canonical}` | `{itype.cisco}` | `{itype.cisco_abbrev}` | "
          f"`{itype.huawei}` | {status} ({itype.status}) | {ref} |")
    w("")
    w("> ระบบแปลงเฉพาะส่วนที่เป็น**ประเภท**ของ Interface และคงส่วนที่เป็น")
    w("> **ตัวเลข**ไว้ตามเดิม เนื่องจากรูปแบบการนับหมายเลขพอร์ตสะท้อนโครงสร้าง")
    w("> ฮาร์ดแวร์ทางกายภาพ จึงไม่มีการแมปที่ถูกต้องสมบูรณ์ด้วยอัลกอริทึม")
    w("> (ดูข้อจำกัด 2.3.2.4)")
    w("")

    # ---- deliberate rejections ------------------------------------------
    w("## ก.4 คำสั่งที่ระบบปฏิเสธการแปลงโดยเจตนา")
    w("")
    w("รายการต่อไปนี้ถูกส่งไปยังรายการคำสั่งที่ไม่มีกฎรองรับ **โดยเจตนา** "
      "ไม่ใช่ข้อบกพร่อง การออกแบบเลือกยอมเสียค่าความครอบคลุม "
      "เพื่อไม่ให้ข้อมูลสูญหายโดยไม่มีการแจ้งเตือน")
    w("")
    w("| คำสั่ง | เหตุผล |")
    w("|---|---|")
    for command, reason in cat.REJECTIONS:
        w(f"| `{command}` | {reason} |")
    w("")

    # ---- unverified items ------------------------------------------------
    unver_rules = [r for r in cat.CATALOG if r.status == "UNVER"]
    unver_types = [i for i in cat.INTERFACE_TYPE_CATALOG
                   if i.status == "UNVER"]
    w("## ก.5 รายการที่ยังไม่ได้ยืนยันกับเอกสารผู้ผลิต")
    w("")
    if not unver_rules and not unver_types:
        w("ไม่มี — ทุกรายการยืนยันแล้ว")
    else:
        w("รายการต่อไปนี้ยังไม่ได้ยืนยันกับแหล่งข้อมูลปฐมภูมิ "
          "และถูกระบุไว้เป็นข้อจำกัดในบทที่ 5 "
          "**ไม่ได้นำเสนอว่าเป็นรายการที่ผ่านการตรวจสอบแล้ว**")
        w("")
        w("| รายการ | ประเภท | หมายเหตุ |")
        w("|---|---|---|")
        for rule in unver_rules:
            w(f"| `{rule.rule_id}` | กฎการแปลง | {rule.note} |")
        for itype in unver_types:
            w(f"| `{itype.canonical}` | ชื่อ Interface | "
              f"`{itype.cisco}` ↔ `{itype.huawei}` — ยังไม่พบเอกสารอ้างอิง |")
        w("")

    # ---- references ------------------------------------------------------
    w("## ก.6 เอกสารอ้างอิงที่ใช้ยืนยันกฎการแปลง")
    w("")
    used = {r.reference for r in cat.CATALOG}
    used |= {i.reference for i in cat.INTERFACE_TYPE_CATALOG}
    w("| รหัส | เอกสาร |")
    w("|---|---|")
    for key in sorted(used):
        if key == "-":
            continue
        w(f"| **{key}** | {cat.REFERENCES[key]} |")
    w("")
    w("> ต้องตรวจสอบเลขรุ่นเอกสารและวันที่เข้าถึงอีกครั้งก่อนส่งฉบับสมบูรณ์")
    w("> และจัดรูปแบบการอ้างอิงตามเกณฑ์ของภาควิชา")
    w("")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="สร้างภาคผนวก ก")
    ap.add_argument("-o", "--output", type=Path,
                    help="ไฟล์ปลายทาง (ไม่ระบุ = แสดงทางหน้าจอ)")
    args = ap.parse_args()

    text = render()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"เขียนไฟล์ {args.output} "
              f"({len(text.splitlines())} บรรทัด)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
