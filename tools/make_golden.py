#!/usr/bin/env python3
"""
Generate golden files from the current renderer output.

Golden files freeze known-good output so that an unintended renderer change
breaks a test loudly instead of quietly. That only works if regenerating them
is a deliberate act -- so this lives in its own script rather than behind a
flag on the test run, and it refuses to overwrite without --force.

Usage
-----
    python tools/make_golden.py              # create missing goldens only
    python tools/make_golden.py --force      # overwrite existing goldens
    python tools/make_golden.py --diff       # show what would change, write nothing

Workflow: when you change a renderer on purpose, run --diff first and read
every line of the output. If the change is what you intended, run --force and
commit the new goldens alongside the code change. If you did not intend it,
you have found a bug.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from netmigrate.engine import can_convert, convert  # noqa: E402
from netmigrate.ir import Vendor  # noqa: E402
from netmigrate.validation import normalise_text  # noqa: E402

CORPUS = ROOT / "corpus"
EXPECTED = CORPUS / "expected"

PAIRS = [(Vendor.CISCO, Vendor.HUAWEI), (Vendor.HUAWEI, Vendor.CISCO)]
DIRNAME = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}
SHORT = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}

HEADER = (
    "GENERATED FILE -- do not edit by hand.\n"
    "Produced by tools/make_golden.py from {src}.\n"
    "If this file needs to change, change the renderer and regenerate."
)


def golden_path(stem: str, target: Vendor) -> Path:
    return EXPECTED / f"{stem}.{SHORT[target]}.cfg"


def source_files(vendor: Vendor) -> list[Path]:
    directory = CORPUS / DIRNAME[vendor]
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir()
        if p.suffix.lower() in (".cfg", ".txt", ".conf")
    )


def banner(source: Vendor, target: Vendor, src_name: str) -> str:
    marker = "!" if target is Vendor.CISCO else "#"
    body = HEADER.format(src=f"{DIRNAME[source]}/{src_name}")
    return "\n".join(f"{marker} {line}" for line in body.splitlines())


def strip_banner(text: str) -> str:
    """Drop the generated-file header so comparison sees only config."""
    lines = text.splitlines()
    kept: list[str] = []
    in_banner = True
    for line in lines:
        stripped = line.strip()
        if in_banner and stripped[:1] in ("!", "#") and "GENERATED FILE" in line:
            continue
        if in_banner and stripped[:1] in ("!", "#") and (
            "tools/make_golden.py" in line or "regenerate" in line
        ):
            continue
        in_banner = False
        kept.append(line)
    return "\n".join(kept)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate NetMigrate golden files")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing golden files")
    ap.add_argument("--diff", action="store_true",
                    help="show differences without writing anything")
    args = ap.parse_args()

    EXPECTED.mkdir(parents=True, exist_ok=True)

    written = skipped = changed = 0

    for source, target in PAIRS:
        if not can_convert(source, target):
            print(f"skip  {SHORT[source]} -> {SHORT[target]}: not implemented")
            continue

        for path in source_files(source):
            out = golden_path(path.stem, target)
            result = convert(path.read_text(encoding="utf-8"), source, target)
            content = (
                banner(source, target, path.name) + "\n" + result.output_text + "\n"
            )

            if out.exists():
                current = strip_banner(out.read_text(encoding="utf-8"))
                fresh = strip_banner(content)
                if normalise_text(current) == normalise_text(fresh):
                    print(f"same  {out.name}")
                    skipped += 1
                    continue

                changed += 1
                if args.diff or not args.force:
                    print(f"\nDIFF  {out.name}")
                    for line in difflib.unified_diff(
                        normalise_text(current).splitlines(),
                        normalise_text(fresh).splitlines(),
                        fromfile="golden (on disk)",
                        tofile="current (renderer output)",
                        lineterm="",
                    ):
                        print(f"      {line}")
                    if not args.force:
                        print(f"      not overwritten -- use --force if intended")
                    continue

            if args.diff:
                if not out.exists():
                    print(f"new   {out.name} (would be created)")
                continue

            out.write_text(content, encoding="utf-8")
            print(f"write {out.name}  ({len(result.output_text.splitlines())} lines)")
            written += 1

    print()
    print(f"{written} written, {skipped} unchanged, {changed} differ")

    if changed and not args.force and not args.diff:
        print("\nSome goldens differ from current output. Read the diffs above.")
        print("If the change is intended, rerun with --force and commit both.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
