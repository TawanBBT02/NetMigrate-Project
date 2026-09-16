"""
Golden file tests: current renderer output must match frozen known-good output.

These are regression tests, not correctness tests. They do not prove the
mapping is right -- only eNSP, Packet Tracer and vendor documentation can do
that. What they prove is that output has not changed *unintentionally*, which
is what protects working rules while later ones are being written.

If one of these fails:
  1. Read the diff. Decide whether the change was intended.
  2. If intended -- run `python tools/make_golden.py --force` and commit the
     new goldens alongside the code change.
  3. If not intended -- you have found a bug. Do not regenerate.

Never regenerate goldens to make a red test go green without reading the
diff first. That defeats the entire purpose of having them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netmigrate.engine import can_convert, convert  # noqa: E402
from netmigrate.ir import Vendor  # noqa: E402
from netmigrate.validation import check_golden, normalise_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
EXPECTED = CORPUS / "expected"

PAIRS = [(Vendor.CISCO, Vendor.HUAWEI), (Vendor.HUAWEI, Vendor.CISCO)]
DIRNAME = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}
SHORT = {Vendor.CISCO: "cisco", Vendor.HUAWEI: "huawei"}

BANNER_MARKERS = ("GENERATED FILE", "tools/make_golden.py", "regenerate")


def strip_banner(text: str) -> str:
    kept = []
    in_banner = True
    for line in text.splitlines():
        if in_banner and line.strip()[:1] in ("!", "#") and any(
            m in line for m in BANNER_MARKERS
        ):
            continue
        in_banner = False
        kept.append(line)
    return "\n".join(kept)


def cases() -> list[tuple[Path, Path, Vendor, Vendor]]:
    found = []
    for source, target in PAIRS:
        directory = CORPUS / DIRNAME[source]
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in (".cfg", ".txt", ".conf"):
                continue
            golden = EXPECTED / f"{path.stem}.{SHORT[target]}.cfg"
            if golden.is_file():
                found.append((path, golden, source, target))
    return found


def test_golden_files_exist():
    """A corpus file with no golden is a gap, not a pass."""
    missing = []
    for source, target in PAIRS:
        if not can_convert(source, target):
            continue
        directory = CORPUS / DIRNAME[source]
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in (".cfg", ".txt", ".conf"):
                continue
            golden = EXPECTED / f"{path.stem}.{SHORT[target]}.cfg"
            if not golden.is_file():
                missing.append(golden.name)
    assert not missing, (
        f"no golden file for: {missing}. "
        f"Run: python tools/make_golden.py"
    )


def test_output_matches_golden():
    """The core regression check, across every corpus file."""
    found = cases()
    assert found, "no golden files found -- run tools/make_golden.py"

    failures = []
    for path, golden, source, target in found:
        report = check_golden(
            path.stem,
            path.read_text(encoding="utf-8"),
            strip_banner(golden.read_text(encoding="utf-8")),
            source,
            target,
        )
        if report.skipped:
            continue
        if not report.ok:
            failures.append(f"{path.name} -> {SHORT[target]}:\n{report.diff}")

    assert not failures, "\n\n".join(failures)


def test_conversion_is_deterministic():
    """Same input must give byte-identical output every time.

    A golden file is worthless if the renderer is non-deterministic -- dict
    ordering, set iteration, or a timestamp leaking into output would make
    these tests flap rather than fail.
    """
    for path, _golden, source, target in cases():
        text = path.read_text(encoding="utf-8")
        first = convert(text, source, target).output_text
        for _ in range(5):
            assert convert(text, source, target).output_text == first, (
                f"{path.name} produced different output on repeat conversion"
            )


def test_golden_has_no_uncommented_ai_output():
    """Safety invariant: nothing advisory may sit in the config body."""
    for golden in sorted(EXPECTED.glob("*.cfg")):
        marker = "!" if ".cisco." in golden.name else "#"
        for lineno, line in enumerate(
            golden.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "AI-REVIEW" in line or "suggested:" in line:
                assert line.lstrip().startswith(marker), (
                    f"{golden.name}:{lineno} advisory content outside a comment"
                )


def test_golden_uses_target_comment_marker():
    """A Huawei golden must not contain Cisco '!' separators, and vice versa."""
    for golden in sorted(EXPECTED.glob("*.cfg")):
        body = strip_banner(golden.read_text(encoding="utf-8"))
        wrong = "!" if ".huawei." in golden.name else "#"
        offending = [
            ln for ln in body.splitlines()
            if ln.strip() == wrong
        ]
        assert not offending, (
            f"{golden.name} contains {wrong!r} separators from the wrong vendor"
        )


def test_golden_round_trips_back():
    """A golden file, fed back through the engine, must parse cleanly.

    This catches output that looks right but that our own parser cannot read
    -- which would mean one of the two modules is wrong about the syntax.
    """
    from netmigrate.rules_cisco import parse_cisco
    from netmigrate.rules_huawei import parse_huawei

    for golden in sorted(EXPECTED.glob("*.cfg")):
        body = strip_banner(golden.read_text(encoding="utf-8"))
        parse = parse_cisco if ".cisco." in golden.name else parse_huawei
        cfg = parse(body)
        # Review-tag comments are stripped by the parser, so anything left in
        # unmapped means the renderer emitted config our parser rejects.
        real_unmapped = [
            u for u in cfg.unmapped if "NETMIGRATE" not in u.text
        ]
        assert not real_unmapped, (
            f"{golden.name}: our own parser rejected "
            f"{[u.text for u in real_unmapped]}"
        )


def test_normalise_text_used_consistently():
    """Guard against trailing-whitespace churn making goldens flap."""
    for golden in sorted(EXPECTED.glob("*.cfg")):
        raw = golden.read_text(encoding="utf-8")
        assert raw == raw.replace(" \n", "\n"), (
            f"{golden.name} has trailing whitespace"
        )


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {exc}")
        else:
            passed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
