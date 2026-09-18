# NetMigrate

Bi-directional network configuration translator: **Cisco IOS-XE ↔ Huawei VRP**.

Senior special project (ปริญญานิพนธ์) by วัชรากร ชูศรียิ่ง and วรานนท์ ใจตรง.
See [`CLAUDE.md`](CLAUDE.md) for the full project context, architecture
rationale, and hard rules — this file is just the quick-start.

## What it does

Parses a saved Cisco IOS-XE or Huawei VRP configuration into a vendor-neutral
intermediate representation, then renders it back out in the other vendor's
syntax:

```
source text -> block-aware parser -> vendor-neutral IR -> renderer -> target text
```

Unrecognised lines are never dropped silently — they're emitted as a
commented review tag using the target vendor's comment marker. An optional,
bounded AI fallback (Gemini) can suggest a translation for those lines only;
its output is always a commented suggestion, never written into the live
config body, and credential lines are excluded from the fallback entirely.

## Status

The conversion engine (`netmigrate/`) is **feature-complete and frozen**. The
web layer (SQLite persistence, FastAPI API, Jinja2 templates) is built
against the engine's `ConversionResult.to_dict()` contract; see
[`CLAUDE.md`](CLAUDE.md) section 1 for exactly what's wired up versus still
pending.

## Running it

```bash
pip install -r requirements.txt

# Run the full test suite
python tools/run_tests.py          # or: pytest -v

# Corpus evaluation -> Chapter 4 data
python tools/evaluate.py

# Command-line demo of a single conversion
python tools/demo.py

# API server (see docs/web-layer-spec.md for endpoints)
uvicorn netmigrate.api:app --reload
```

## Layout

```
netmigrate/     Conversion engine (frozen) + web layer (persistence, API, deploy sim)
templates/      Jinja2 page shells for the web UI
static/         Shared frontend JS (fetch helpers, theme, diff view)
tests/          pytest suites — engine and web layer
tools/          run_tests.py, evaluate.py, make_golden.py, make_paste.py, demo.py, make_appendix.py
docs/           Mapping spec, verification register, web layer spec, thesis chapters
```
