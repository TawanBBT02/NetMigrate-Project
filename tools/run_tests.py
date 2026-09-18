#!/usr/bin/env python3
"""
รันชุดทดสอบทั้งหมดของระบบ NetMigrate

ใช้งาน:
    python tools/run_tests.py              # รันทั้งหมด สรุปผล
    python tools/run_tests.py --verbose    # แสดงรายละเอียดทุกเทสต์ที่ล้มเหลว
    python tools/run_tests.py --suite core # รันเฉพาะไฟล์ที่ชื่อมีคำว่า core

ทำงานได้โดยไม่ต้องติดตั้ง pytest (เรียกแต่ละไฟล์เทสต์เป็นสคริปต์) ผลลัพธ์
จัดรูปแบบให้อ่านง่ายและใช้แคปหน้าจอใส่รายงานบทที่ 4 ได้

หมายเหตุ: ถ้าติดตั้ง pytest แล้ว ใช้ `pytest -v` ก็ได้ผลเหมือนกัน
สคริปต์นี้มีไว้เพื่อให้รันได้แม้ในเครื่องที่ยังไม่ได้ติดตั้ง
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# คำอธิบายว่าแต่ละชุดทดสอบครอบคลุมอะไร ใช้ในตารางสรุปและในรายงาน
SUITE_PURPOSE = {
    "test_core": "ตัวแยกวิเคราะห์บล็อก และฟังก์ชันแปลงค่า (VLAN, area, mask)",
    "test_rules_cisco": "ตัวอ่านไฟล์ Cisco IOS-XE เข้าสู่โครงสร้างข้อมูลกลาง",
    "test_roundtrip": "ตัวอ่าน Huawei, ตัวสร้าง Cisco, และการแปลงกลับ",
    "test_validation": "กลไกเปรียบเทียบ IR ที่ใช้วัดค่า H2",
    "test_golden": "การถดถอยของผลลัพธ์ (golden file) และความคงที่ของผลลัพธ์",
    "test_scope_additions": "ขีดจำกัด 40 element, Null0, undo allow-pass, รหัสผ่าน",
    "test_ai_fallback": "กลไกสำรองด้วย AI และขอบเขตความปลอดภัย",
}

RESULT_RE = re.compile(r"(\d+) passed, (\d+) failed, (\d+) total")


def discover(pattern: str | None) -> list[Path]:
    files = sorted(TESTS.glob("test_*.py"))
    if pattern:
        files = [f for f in files if pattern.lower() in f.stem.lower()]
    return files


def run_one(path: Path) -> tuple[int, int, int, str, float]:
    """รันไฟล์เทสต์หนึ่งไฟล์ คืนค่า (ผ่าน, ล้มเหลว, ทั้งหมด, output, วินาที)"""
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    elapsed = time.perf_counter() - started
    output = proc.stdout + proc.stderr

    match = RESULT_RE.search(output)
    if match:
        passed, failed, total = (int(g) for g in match.groups())
    else:
        # ไฟล์พังก่อนจะรายงานผล เช่น import ไม่ได้
        passed, failed, total = 0, 1, 1
    return passed, failed, total, output, elapsed


def main() -> int:
    ap = argparse.ArgumentParser(description="รันชุดทดสอบ NetMigrate")
    ap.add_argument("--verbose", action="store_true",
                    help="แสดง output ทั้งหมดของชุดที่ล้มเหลว")
    ap.add_argument("--suite", help="รันเฉพาะไฟล์ที่ชื่อมีคำนี้")
    args = ap.parse_args()

    files = discover(args.suite)
    if not files:
        print(f"ไม่พบไฟล์เทสต์ใน {TESTS}")
        return 1

    print("=" * 78)
    print("NetMigrate — ผลการทดสอบระบบ")
    print("=" * 78)
    print()

    width = max(len(f.stem) for f in files) + 2
    total_passed = total_failed = total_all = 0
    failures: list[tuple[str, str]] = []
    started = time.perf_counter()

    for path in files:
        passed, failed, total, output, elapsed = run_one(path)
        total_passed += passed
        total_failed += failed
        total_all += total

        mark = "ผ่าน" if failed == 0 else "ล้มเหลว"
        print(f"  {path.stem:<{width}} {passed:>4}/{total:<4} {mark:<9} "
              f"{elapsed * 1000:>7.0f} ms")
        purpose = SUITE_PURPOSE.get(path.stem)
        if purpose:
            print(f"  {'':<{width}} {purpose}")
        print()

        if failed:
            failures.append((path.stem, output))

    wall = time.perf_counter() - started

    print("-" * 78)
    print(f"  รวม {len(files)} ชุดทดสอบ  {total_passed} ผ่าน  "
          f"{total_failed} ล้มเหลว  จากทั้งหมด {total_all} เทสต์  "
          f"({wall:.1f} วินาที)")
    print("-" * 78)

    if failures:
        print()
        print("ชุดที่ล้มเหลว:")
        for name, output in failures:
            print(f"\n  ### {name}")
            lines = [ln for ln in output.splitlines()
                     if ln.startswith("FAIL") or "Error" in ln]
            for ln in (lines if not args.verbose else output.splitlines()):
                print(f"    {ln}")
        print()
        print("  หมายเหตุ: ถ้า test_golden ล้มเหลว ให้อ่าน diff ก่อน")
        print("  python tools/make_golden.py --diff")
        print("  ถ้าการเปลี่ยนแปลงเป็นไปตามที่ตั้งใจ จึงใช้ --force")
        return 1

    print()
    print("  ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    sys.exit(main())