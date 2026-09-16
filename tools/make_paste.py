#!/usr/bin/env python3
"""
Emit paste-ready configuration files for simulator validation (H3).

Golden files are not directly pasteable: they carry a generated-file banner,
and NETMIGRATE review-tag comments will be rejected by a live CLI. This
strips every comment, wraps the body in the target vendor's config-mode
preamble, and writes one file per conversion into corpus/paste/.

It also splits long configs into numbered chunks. eNSP's console drops
characters on large pastes, and a dropped character produces a syntax error
that looks like a mapping bug but isn't -- which would corrupt your H3
measurement.

Usage
-----
    python tools/make_paste.py                 # default 25-line chunks
    python tools/make_paste.py --chunk 15      # smaller chunks
    python tools/make_paste.py --no-chunk      # one file per config

Then, per file:
    eNSP  S5700   ->  system-view, paste, check for '^' errors
    PT    2960    ->  enable, conf t, paste, check for '%' errors
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from netmigrate.engine import can_convert, convert  # noqa: E402
from netmigrate.ir import Vendor  # noqa: E402

CORPUS = ROOT / "corpus"
PASTE = CORPUS / "paste"

PAIRS = [(Vendor.CISCO, Vendor.HUAWEI), (Vendor.HUAWEI, Vendor.CISCO)]
DIRNAME = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}
SHORT = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}

PREAMBLE = {
    Vendor.HUAWEI: ["system-view", "screen-length 0 temporary"],
    Vendor.CISCO: ["enable", "configure terminal", "terminal length 0"],
}
POSTAMBLE = {
    Vendor.HUAWEI: ["return"],
    Vendor.CISCO: ["end"],
}


def strip_comments(text: str, marker: str) -> list[str]:
    """Drop every comment and blank line. Keep indentation.

    Also drops the renderer's own trailing terminator (``return`` / ``end``),
    since the postamble adds one -- otherwise the paste ends with it twice.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(marker):
            continue
        # Never paste advisory content, whatever marker it used.
        if "NETMIGRATE" in line:
            continue
        kept.append(line.rstrip())

    while kept and kept[-1].strip().lower() in ("return", "end", "exit", "quit"):
        kept.pop()

    return kept


def chunk(lines: list[str], size: int) -> list[list[str]]:
    """Split into chunks, never breaking inside an indented block.

    A chunk that ends between `interface GE0/0/1` and its indented children
    would leave the device in interface view when the paste stops, and the
    next chunk's top-level command would be interpreted in the wrong context.
    """
    if size <= 0:
        return [lines]

    chunks: list[list[str]] = []
    current: list[str] = []

    for i, line in enumerate(lines):
        current.append(line)
        if len(current) < size:
            continue
        # Only break where the NEXT line starts a new top-level block.
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        if next_line is None or not next_line.startswith(" "):
            chunks.append(current)
            current = []

    if current:
        chunks.append(current)
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit paste-ready configs")
    ap.add_argument("--chunk", type=int, default=25,
                    help="max lines per chunk (default 25)")
    ap.add_argument("--no-chunk", action="store_true",
                    help="write one file per config, no splitting")
    args = ap.parse_args()

    size = 0 if args.no_chunk else args.chunk

    PASTE.mkdir(parents=True, exist_ok=True)
    written = 0

    for source, target in PAIRS:
        if not can_convert(source, target):
            continue

        directory = CORPUS / DIRNAME[source]
        if not directory.is_dir():
            continue

        marker = "#" if target is Vendor.HUAWEI else "!"

        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in (".cfg", ".txt", ".conf"):
                continue

            result = convert(path.read_text(encoding="utf-8"), source, target)
            body = strip_comments(result.output_text, marker)
            parts = chunk(body, size)

            for n, part in enumerate(parts, start=1):
                suffix = "" if len(parts) == 1 else f".part{n}"
                out = PASTE / f"{path.stem}.{SHORT[target]}{suffix}.txt"

                lines = []
                if n == 1:
                    lines.extend(PREAMBLE[target])
                lines.extend(part)
                if n == len(parts):
                    lines.extend(POSTAMBLE[target])

                out.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print(f"write {out.name}  ({len(part)} config lines)")
                written += 1

    print()
    print(f"{written} file(s) in {PASTE.relative_to(ROOT)}")
    print("Paste each part in order. Stop at the first error and record it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
