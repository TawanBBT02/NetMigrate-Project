# NetMigrate — project context

Bi-directional network configuration translator: **Cisco IOS-XE ↔ Huawei VRP**.
Senior special project (ปริญญานิพนธ์), two students. **Hard deadline 30 Sep 2026.**

Read this file before changing anything. The decisions below were made
deliberately, several of them after finding that the obvious approach fails.
If a change would contradict something here, say so and ask rather than
proceeding.

---

## 1. Architecture — do not change without discussion

```
source text → block-aware parser → vendor-neutral IR → renderer → target text
```

**This is NOT line-by-line regex substitution.** That approach was considered
and rejected, because OSPF cannot be expressed with it:

```
! Cisco                          # Huawei
router ospf 1                    ospf 1 router-id 1.1.1.1
 router-id 1.1.1.1                area 0.0.0.0
 network 10.0.0.0 0.0.0.255 area 0   network 10.0.0.0 0.0.0.255
 network 172.16.0.0 0.0.0.255 area 1  area 0.0.0.1
                                      network 172.16.0.0 0.0.0.255
```

Three things happen at once: `router-id` promotes onto the process line,
areas become parent blocks requiring networks to be regrouped, and area IDs
convert between integer and dotted-decimal. Output cannot begin until the
whole block has been read. The IR exists for this reason.

Adding a vendor means writing one parser and one renderer — *n* + *n*
components, not *n*² pairwise mappings. This is what makes the future-work
claim of additional vendor support credible.

### Rule classification

Every rule is **D**, **T**, or **S**:

| Class | Meaning | Example |
|---|---|---|
| D | direct 1:1 substitution | `hostname` ↔ `sysname`, `no` ↔ `undo` |
| T | 1:1 line, argument reformatted | VLAN lists, route preference |
| S | block nesting or ordering changes | OSPF |

`docs/netmigrate-mapping-spec.md` is the authoritative rule table. When
implementing a rule, follow the spec; if the spec looks wrong, flag it rather
than silently diverging.

---

## 2. Hard rules — violations are bugs

1. **Single Python runtime.** No Node.js. Python 3.11+.
2. **SQLite for persistence**, never in-memory. An audit history that dies on
   restart is not an audit history.
3. **AI fallback fires ONLY when the parser emits an `UnmappedBlock`.** Never
   merely because an API key exists. If AI ran on every conversion, the
   rule-coverage metric would be meaningless.
4. **AI output is NEVER written into the uncommented config body.** Always a
   commented suggestion with `[NETMIGRATE-AI-REVIEW]`. There is a test for
   this (`test_ai_output_never_uncommented`) — do not weaken it.
5. **Model self-reported confidence is displayed but excluded from all
   metrics.** It is not a validated reliability measure.
6. **Never drop an unrecognised line silently.** It goes to `cfg.unmapped`
   and is emitted as a commented review tag using the *target* vendor's
   comment marker. Silent loss is the failure mode this whole design exists
   to prevent.
7. **`admin_down` is tri-state.** `None` means the source config was silent —
   emit nothing. Do not infer platform defaults. (Cisco switchports default
   up, Cisco router ports default down, Huawei ports default up — they are
   not the same, so guessing is wrong.)
8. **Interface type is translated; the numeric portion is preserved
   verbatim.** Port numbering reflects physical hardware and has no lossless
   algorithmic mapping. Non-zero slot in slash notation → emit a review
   warning. Logical interfaces (Loopback, Vlanif, Eth-Trunk) are exempt:
   `Vlanif10` is VLAN 10, not slot 10.
9. **Coverage is measured SOURCE-side**, not output-side:
   `rule_lines = significant_lines - len(cfg.unmapped)`.
   Output-side counting is wrong because OSPF turns 3 lines into 4 and
   `vlan 10,20` turns 1 line into 2 blocks — the ratio could exceed 100%.
10. **`Provenance.GENERATED`** is for renderer-created lines (`#`/`!`
    separators, `end`/`return`) that map to no source line. Excluded from all
    metrics.

---

## 3. Scope — locked

### In scope
System identity, comments, VLAN create/name, interface description /
IP / admin state / type naming, switchport access and trunk, static routes,
single-process OSPFv2 IPv4.

### Modules
| # | Module | Owner |
|---|---|---|
| 1 | Single file conversion + diff view + per-line provenance | วัชรากร |
| 2 | Batch conversion + ZIP | วรานนท์ |
| 3 | Device inventory (records only, no connectivity test) | วรานนท์ |
| 4 | Simulated deployment (SSE log stream) | วรานนท์ |
| 5 | Dashboard + audit history | วรานนท์ |
| 6 | Settings: `/api/health`, light/dark theme | วรานนท์ |

### Explicitly OUT of scope — do not implement
- SSH / Netmiko / Paramiko / any real device connectivity
- Bilingual Thai/English UI (cut: high cost, no academic value)
- Simulated ping / SSH connectivity testing
- ACL, QoS, BGP, IS-IS, VRF, OSPFv3, multi-process OSPF, IPv6
- Multi-user auth / roles

If asked to add any of these, refuse and point at this section. They belong
in Chapter 5 Future Work.

---

## 4. Deliberate rejections — not bugs

These constructs go to `unmapped` **on purpose**. Do not "fix" them.

| Construct | Why |
|---|---|
| `port trunk allow-pass vlan all` | not expressible as an explicit Cisco list in scope |
| `port link-type hybrid` | no Cisco equivalent in scope |
| `ip route-static ... 150` (no `preference` keyword) | invalid VRP syntax; keyword required |
| `ip route ... name BACKUP` | would silently discard the name |
| `vlan 10,20` + `name X` | a name cannot apply to several VLANs |
| unknown interface types (Serial, Tunnel, ATM) | out of scope |

## 5. Documented normalisations — semantically lossless

Round-trip output differs textually from the input in these two cases. Both
are correct. Each has a named test.

1. `vlan batch 10 20 30` expands into individual `vlan` blocks and does not
   reconstitute as `batch`.
2. `ip address 10.0.0.1 24` normalises to `255.255.255.0` and stays dotted.

This is why **round-trip fidelity is measured on the IR, not the text.**
Comment markers change, separators regenerate, block order is a renderer
choice — none of that is data loss. `_comparable()` in `validation.py`
excludes `source_line` (line numbers necessarily shift) and `unmapped`
(unconvertible lines survive as comments, which do not parse back; that loss
is already counted by the unmapped metric and must not be double-penalised).

---

## 6. Evaluation — hypotheses being tested

| # | Hypothesis | Target |
|---|---|---|
| H1 | rule coverage on in-scope corpus | ≥ 85% of significant lines |
| H2 | round-trip fidelity (class D and T) | ≥ 95% |
| H3 | output loads in eNSP / Packet Tracer without syntax error | ≥ 90% of sampled files |
| H4 | conversion time vs timed manual baseline | ≥ 80% reduction |
| H5 | AI suggestion correctness on expert review | **no target — reported as found** |

H5 deliberately has no target. A low figure is a valid result and supports
the decision to flag rather than apply.

Never claim "0% error rate." That was in an earlier draft and is circular
reasoning: the engine is correct by definition for cases we wrote rules for.

`python tools/evaluate.py --csv results.csv` generates the Chapter 4 table.
The `simulator_load` column is filled in by hand.

---

## 7. Testing discipline

- **pytest.** Every rule gets a unit test.
- **Write the test before the rule.** The suite is the evidence base for
  Chapter 4.
- **Never weaken a test to make code pass.** If a test fails, either the code
  is wrong or the test encodes a wrong belief — decide which and say so.
- A passing suite proves the code matches *our beliefs*, not that the beliefs
  are right. Mapping correctness is validated in eNSP / Packet Tracer and
  against vendor documentation, not by tests.

Current state: **121 tests passing.** Do not let this number go down.

```bash
pytest -v
python tools/evaluate.py
```

---

## 8. File map

```
netmigrate/
  ir.py            IR dataclasses + ConversionResult (the API contract)
  blocks.py        block-aware parser (structure only, no command meaning)
  transforms.py    pure class-T functions: VLAN lists, area IDs, masks, if names
  engine.py        registry + convert() entry point
  validation.py    ir_diff, round_trip, check_golden
  rules_cisco.py   Cisco text → IR
  rules_huawei.py  Huawei text → IR
  render_cisco.py  IR → Cisco text
  render_huawei.py IR → Huawei text
tests/             test_core, test_rules_cisco, test_roundtrip, test_validation
tools/evaluate.py  corpus runner → Chapter 4 CSV
corpus/            cisco/, huawei/, expected/
docs/              netmigrate-mapping-spec.md, TK01-revised.md
```

**`ConversionResult.to_dict()` in `ir.py` is the contract between the engine
and the web layer.** The web layer must not touch the dataclasses directly,
so the internal model stays free to change. Changing that dict's shape breaks
วรานนท์'s frontend — flag it before doing so.

---

## 9. Status and next steps

**Done:** IR, block parser, transforms, both parsers, both renderers,
validation harness, evaluation runner, 3 corpus files. Both directions
convert; round trip passes.

**Next, in order:**
1. Golden files — save current output to `corpus/expected/`, add a test
2. AI fallback (`netmigrate/ai_fallback.py`) — suggest-and-flag only
3. Hand the engine to วรานนท์; he builds against `to_dict()`
4. Grow the corpus to 15–30 files, including configs **not** designed around
   our rules — current coverage numbers are not yet evidence
5. eNSP / Packet Tracer validation for H3

**Freeze dates — these control the outcome:**
- **20 Sep: rule freeze.** No new rules after this. Anything discovered later
  goes to Future Work.
- **24 Sep: feature freeze.** All remaining effort moves to evaluation and
  writing, regardless of feature completeness. Missing this date is the one
  unrecoverable failure: a system with fewer features and a real Chapter 4
  passes; a feature-complete system with no evaluation data does not.

---

## 10. Working preferences

- Explain *why*, in comments, where a decision is non-obvious. Several
  comments in this codebase exist to be quoted in Chapter 3.
- Do not add dependencies. Almost everything needed is in the standard
  library (`sqlite3`, `difflib`, `zipfile`, `ipaddress`). Current external
  deps: fastapi, uvicorn, jinja2, python-multipart, google-genai, pytest.
- Do not pin a Gemini model version in documentation or prose — model
  versions deprecate faster than the thesis lifecycle. Keep it in config.
- The student must be able to explain every line on 30 Sep. After writing a
  non-trivial function, explain the reasoning back rather than just reporting
  that tests pass.