#!/usr/bin/env python3
"""
Corpus evaluation runner. Produces the Chapter 4 data table.

Usage
-----
    python tools/evaluate.py                 # run everything, print summary
    python tools/evaluate.py --csv out.csv   # also write the CSV
    python tools/evaluate.py --verbose       # show round-trip differences

Expected corpus layout
----------------------
    corpus/
      cisco/*.cfg            Cisco-source test files
      huawei/*.cfg           Huawei-source test files
      expected/<name>.huawei.cfg   optional golden output
      expected/<name>.cisco.cfg    optional golden output

Every file in corpus/cisco is converted to Huawei and round-tripped; every
file in corpus/huawei is converted to Cisco and round-tripped. Where a
matching file exists under corpus/expected, a golden comparison runs too.

Metrics collected per file map directly onto the hypotheses:
    rule_coverage     -> H1  (target >= 0.85)
    round_trip ok     -> H2  (target >= 0.95 of files)
    duration_ms       -> H4  (compare against the manual baseline)
    ai_lines          -> fallback invocation rate
Simulator load success (H3) is recorded by hand; this script leaves a column
for it.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from netmigrate.engine import can_convert  # noqa: E402
from netmigrate.ir import Vendor  # noqa: E402
from netmigrate.validation import check_golden, round_trip  # noqa: E402

CORPUS = ROOT / "corpus"

VENDOR_DIRS = {
    Vendor.CISCO: "cisco",
    Vendor.HUAWEI: "huawei",
}
SHORT = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}


def collect_files(vendor: Vendor) -> list[Path]:
    directory = CORPUS / VENDOR_DIRS[vendor]
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir()
        if p.suffix.lower() in (".cfg", ".txt", ".conf")
    )


def evaluate() -> list[dict]:
    rows: list[dict] = []

    for source, target in [
        (Vendor.CISCO, Vendor.HUAWEI),
        (Vendor.HUAWEI, Vendor.CISCO),
    ]:
        for path in collect_files(source):
            text = path.read_text(encoding="utf-8")
            report = round_trip(text, source, target)

            golden_path = CORPUS / "expected" / f"{path.stem}.{SHORT[target]}.cfg"
            if golden_path.is_file():
                golden = check_golden(
                    path.stem, text, golden_path.read_text(encoding="utf-8"),
                    source, target,
                )
                golden_state = (
                    "skip" if golden.skipped else ("pass" if golden.ok else "FAIL")
                )
            else:
                golden = None
                golden_state = "-"

            rows.append({
                "file": path.name,
                "direction": f"{SHORT[source]}->{SHORT[target]}",
                "significant_lines": report.significant_lines,
                "rule_lines": report.rule_lines,
                "ai_lines": report.ai_lines,
                "unmapped_lines": report.unmapped_lines,
                "rule_coverage": round(report.rule_coverage, 4),
                "round_trip": (
                    "skip" if report.skipped else ("pass" if report.ok else "FAIL")
                ),
                "round_trip_diffs": len(report.differences),
                "golden": golden_state,
                "duration_ms": report.duration_ms,
                "simulator_load": "",  # filled in by hand on 26 Sep
                "_report": report,
                "_golden": golden,
            })

    return rows


def summarise(rows: list[dict]) -> None:
    if not rows:
        print("No corpus files found under", CORPUS)
        print("Create corpus/cisco/ and corpus/huawei/ and add .cfg files.")
        return

    graded = [r for r in rows if r["round_trip"] != "skip"]
    skipped = [r for r in rows if r["round_trip"] == "skip"]

    print(f"{'file':<28} {'direction':<16} {'sig':>5} {'rule':>5} "
          f"{'ai':>4} {'unmap':>6} {'cov':>7} {'round-trip':>11} {'golden':>7}")
    print("-" * 100)
    for r in rows:
        print(f"{r['file']:<28} {r['direction']:<16} "
              f"{r['significant_lines']:>5} {r['rule_lines']:>5} "
              f"{r['ai_lines']:>4} {r['unmapped_lines']:>6} "
              f"{r['rule_coverage']:>7.1%} {r['round_trip']:>11} {r['golden']:>7}")

    print()
    if skipped:
        print(f"{len(skipped)} file(s) skipped -- "
              f"{skipped[0]['_report'].reason}")
        print()

    if not graded:
        print("Nothing gradeable yet. Write the renderers, then re-run.")
        return

    total_sig = sum(r["significant_lines"] for r in graded)
    total_rule = sum(r["rule_lines"] for r in graded)
    total_ai = sum(r["ai_lines"] for r in graded)
    total_unmapped = sum(r["unmapped_lines"] for r in graded)
    rt_pass = sum(1 for r in graded if r["round_trip"] == "pass")

    coverage = total_rule / total_sig if total_sig else 0.0
    fidelity = rt_pass / len(graded)

    print("=== Hypothesis results ===")
    print(f"H1  rule coverage        {coverage:>7.1%}   target >= 85%    "
          f"{'PASS' if coverage >= 0.85 else 'BELOW TARGET'}")
    print(f"H2  round-trip fidelity  {fidelity:>7.1%}   target >= 95%    "
          f"{'PASS' if fidelity >= 0.95 else 'BELOW TARGET'}")
    print(f"H3  simulator load       (record by hand -- see corpus notes)")
    print(f"H4  mean conversion time "
          f"{sum(r['duration_ms'] for r in graded) / len(graded):>6.1f} ms   "
          f"compare against manual baseline")
    print(f"H5  fallback invocation  "
          f"{total_ai / total_sig if total_sig else 0:>7.1%}   no target set")
    print()
    print(f"    files graded {len(graded)}, round-trip pass {rt_pass}, "
          f"unmapped lines {total_unmapped} of {total_sig} significant")


def show_failures(rows: list[dict]) -> None:
    for r in rows:
        report = r["_report"]
        if report.differences:
            print(f"\n--- round-trip differences: {r['file']} "
                  f"({r['direction']}) ---")
            for d in report.differences[:25]:
                print(f"    {d}")
            if len(report.differences) > 25:
                print(f"    ... {len(report.differences) - 25} more")

        golden = r["_golden"]
        if golden is not None and golden.diff:
            print(f"\n--- golden mismatch: {r['file']} ---")
            print(golden.diff)


def write_csv(rows: list[dict], path: Path) -> None:
    columns = [
        "file", "direction", "significant_lines", "rule_lines", "ai_lines",
        "unmapped_lines", "rule_coverage", "round_trip", "round_trip_diffs",
        "golden", "duration_ms", "simulator_load",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in columns})
    print(f"\nWrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="NetMigrate corpus evaluation")
    ap.add_argument("--csv", type=Path, help="write results to CSV")
    ap.add_argument("--verbose", action="store_true",
                    help="show round-trip and golden differences")
    args = ap.parse_args()

    print("Registered conversions:")
    for s, t in [(Vendor.CISCO, Vendor.HUAWEI), (Vendor.HUAWEI, Vendor.CISCO)]:
        state = "ready" if can_convert(s, t) else "not implemented"
        print(f"  {SHORT[s]:>6} -> {SHORT[t]:<6}  {state}")
    print()

    rows = evaluate()
    summarise(rows)

    if args.verbose:
        show_failures(rows)

    if args.csv:
        write_csv(rows, args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
