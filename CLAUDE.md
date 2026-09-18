# NetMigrate — project context

Bi-directional network configuration translator: **Cisco IOS-XE ↔ Huawei VRP**.
Senior special project (ปริญญานิพนธ์), two students. **Hard deadline 30 Sep 2026.**

Read this file before changing anything. The decisions below were made
deliberately, several after finding that the obvious approach fails. If a
change would contradict something here, say so and ask rather than proceeding.

**Current phase: the ENGINE is frozen; the WEB LAYER is not.**

Frozen — do not modify: `ir.py`, `blocks.py`, `transforms.py`, `engine.py`,
`validation.py`, `rules_cisco.py`, `rules_huawei.py`, `render_cisco.py`,
`render_huawei.py`, `ai_fallback.py`, `rule_catalog.py`

Open to change within section 5's scope: `persistence.py`, `api.py`,
`deploy_sim.py`, `templates/`, `static/`

---

## 1. Status — 20 Sep 2026

**Engine — complete and frozen:**

```
netmigrate/
  ir.py             IR dataclasses + ConversionResult (THE API CONTRACT)
  blocks.py         block-aware parser (structure only)
  transforms.py     class-T functions: VLAN lists, area IDs, masks, if names
  engine.py         registry + convert() entry point
  validation.py     ir_diff, round_trip, check_golden, benchmark_convert
  rules_cisco.py    Cisco text -> IR
  rules_huawei.py   Huawei text -> IR
  render_cisco.py   IR -> Cisco text
  render_huawei.py  IR -> Huawei text
  ai_fallback.py    bounded LLM suggestions, credential-excluded
  rule_catalog.py   rule metadata; source of Appendix A
```

**Web layer — built against the frozen contract, still open to change within
section 5's scope:**

```
netmigrate/
  persistence.py    SQLite schema + data access (no FastAPI imports)
  api.py            FastAPI app; every /api/* endpoint in section 3 below
  deploy_sim.py      simulated deployment log generator (SSE payloads)
templates/          base.html, index.html, batch.html, devices.html,
                    deploy.html, dashboard.html, history.html, settings.html
static/             app.js (fetch helpers, theme toggle), diff.js (diff view)
```

**Page routes are wired.** `api.py` mounts `/static` via `StaticFiles` and
serves every page in section 5's table (`/`, `/batch`, `/devices`,
`/deploy`, `/dashboard`, `/history`, `/settings`) as a bare `Jinja2Templates`
render — no server-side context beyond `request` (`base.html` uses it only
to highlight the active nav item); all data is fetched client-side against
`/api/*`. Confirmed by `test_every_page_route_renders_html` and
`test_static_files_are_served` in `test_api.py`.

**254 tests passing across 11 suites, 0 failing (207 engine + 47 web layer:
`test_persistence` 12, `test_api` 22, `test_deploy_sim` 13). Do not let this
number go down.**

```bash
python tools/run_tests.py          # or: pytest -v
python tools/evaluate.py           # corpus evaluation -> Chapter 4 data
```

**Golden fixtures regenerated 20 Sep** (`python tools/make_golden.py
--force`, workflow per that script's own docstring). Three of eleven
corpus goldens were stale against current `render_cisco.py` /
`render_huawei.py` credential-guidance text — `transforms.py` had been
partially updated to emit per-construct guidance ("privilege-escalation
password (from ...)" / "user account (from ...)") instead of one generic
block, and to stop attaching a credential block to `no aaa new-model`
(`c-sw-distribution.cfg`, which has no `secret`/`password`/`local-user`
line at all — the old golden's block there was a bug, not a spec). Confirmed
via `--diff` before forcing: every changed line was guidance-comment text,
nothing structural. If `test_output_matches_golden` goes red again, run
`--diff` first and read every line before `--force` — don't rubber-stamp it.

**Not built yet — this is the remaining work:**

- None against section 5's scope. All 6 web-layer modules and their page
  routes are implemented and tested. Remaining effort is evaluation
  (H3a, H4, H5) and writing per section 10.

---

## 2. Architecture — do not change

```
source text -> block-aware parser -> vendor-neutral IR -> renderer -> target text
```

**NOT line-by-line regex.** That was considered and rejected: OSPF cannot be
expressed with it. `router-id` promotes onto the process line, areas become
parent blocks requiring networks to be regrouped, and area IDs convert
integer <-> dotted-decimal. Output cannot begin until the whole block is read.
Structural rules are **25% of the rule set** — higher than first estimated.

Adding a vendor = one parser + one renderer (n + n, not n squared).

Rules are classified **D** (direct, 56%), **T** (transform, 19%),
**S** (structural, 25%). `docs/netmigrate-mapping-spec.md` and
`netmigrate/rule_catalog.py` are authoritative.

---

## 3. Hard rules — violations are bugs

1. **Single Python runtime.** No Node. Python 3.11+.
2. **SQLite for persistence**, never in-memory.
3. **AI fallback fires ONLY when the parser emits an `UnmappedBlock`** — never
   merely because an API key exists. Otherwise the coverage metric measures
   nothing.
4. **AI output is NEVER written into the uncommented config body.** Always a
   commented suggestion tagged `[NETMIGRATE-AI-REVIEW]`.
5. **Credential lines are never sent to the AI API** and never converted.
   Password hashes are one-way and vendor-specific. They get deterministic
   manual-entry guidance instead.
6. **Model self-reported confidence is displayed but excluded from all
   metrics.** It is not a validated reliability measure.
7. **Never drop an unrecognised line silently.** It goes to `cfg.unmapped`
   and is emitted as a commented review tag using the *target* vendor's
   comment marker.
8. **`admin_down` is tri-state.** `None` = source was silent; emit nothing.
   Vendor defaults differ, so inferring is wrong.
9. **Interface type is translated; the numeric portion is preserved
   verbatim.** Non-zero slot in slash notation -> review warning. Logical
   interfaces (LoopBack, Vlanif, Eth-Trunk) exempt: `Vlanif10` is VLAN 10.
10. **Coverage is measured SOURCE-side:**
    `rule_lines = significant_lines - len(cfg.unmapped)`.
    Output-side counting can exceed 100% because OSPF turns 3 lines into 4.
11. **`Provenance.GENERATED`** is for renderer-created lines (`#`/`!`
    separators, `end`/`return`). Excluded from all metrics.
12. **VLAN lists split at 40 elements** per `allow-pass` command (VRP
    `&<1-40>`); a range counts as one element.

### Tests that enforce safety invariants — never weaken these

| Invariant | Test |
|---|---|
| AI output never uncommented | `test_ai_output_never_uncommented` |
| Credentials never uncommented | `test_credential_never_appears_uncommented` |
| Credentials never sent to API | `test_credentials_are_never_sent` |
| AI never inflates coverage | `test_coverage_unchanged_by_fallback` |
| Catalog matches code | `test_every_code_rule_is_catalogued` |

---

## 4. THE API CONTRACT — read before writing any web code

`ConversionResult.to_dict()` in `netmigrate/ir.py` is the only interface
between the engine and the web layer. **The web layer must not import or
touch the IR dataclasses directly.**

```json
{
  "source_vendor": "cisco_iosxe",
  "target_vendor": "huawei_vrp",
  "source_text": "...",
  "output_text": "...",
  "lines": [
    {
      "text": " port link-type access",
      "provenance": "RULE",
      "source_line": 7,
      "rule_id": "port.link-type",
      "needs_review": false
    }
  ],
  "metrics": {
    "total_lines": 33,
    "significant_lines": 22,
    "rule_lines": 21,
    "ai_lines": 0,
    "unmapped_lines": 1,
    "rule_coverage": 0.9545,
    "duration_ms": 0.1312
  }
}
```

`provenance` is one of `RULE`, `AI`, `UNMAPPED`, `GENERATED`.
`source_line` and `rule_id` may be null.

Engine entry point:

```python
from netmigrate.engine import convert
from netmigrate.ir import Vendor
from netmigrate.ai_fallback import make_fallback

result = convert(text, Vendor.CISCO, Vendor.HUAWEI,
                 ai_fallback=make_fallback(Vendor.HUAWEI))
payload = result.to_dict()
```

`make_fallback()` returns `None` when no API key is set, and `convert()`
accepts `None` — so the system works with no key configured.

**Changing the shape of this dict breaks the frontend. Flag it, never do it
silently.**

---

## 5. Web layer scope — 6 modules

| # | Module | Endpoints | Page |
|---|---|---|---|
| 1 | Single conversion + diff view | `POST /api/convert` | `/` |
| 2 | Batch conversion + ZIP | `POST /api/convert/batch`, `GET /api/batch/{id}/zip` | `/batch` |
| 3 | Device inventory (records only) | `GET/POST/PUT/DELETE /api/devices` | `/devices` |
| 4 | Simulated deployment (SSE) | `GET /api/deploy/stream` | `/deploy` |
| 5 | Dashboard + audit history | `GET /api/stats`, `GET /api/conversions`, `GET /api/conversions/{id}` | `/dashboard`, `/history` |
| 6 | Settings | `GET /api/health` | `/settings` |

Full specification: **`docs/web-layer-spec.md`**. Follow it.

### Explicitly OUT of scope — do not implement
- SSH / Netmiko / Paramiko / any real device connectivity. Module 4 is
  simulated with timers only.
- Simulated ping / SSH connectivity testing in the inventory
- Bilingual Thai/English UI (cut: high cost, no academic value).
  Light/dark theme is kept — it is cheap.
- ACL, QoS, BGP, IS-IS, VRF, OSPFv3, multi-process OSPF, IPv6
- Multi-user auth / roles

If asked to add any of these, refuse and point here. They belong in
Chapter 5 Future Work.

---

## 6. Deliberate rejections — not bugs, do not "fix"

| Construct | Why |
|---|---|
| `port trunk allow-pass vlan all` | not expressible as an explicit Cisco list in scope |
| `port link-type hybrid` | no Cisco equivalent in scope |
| `ip route-static ... 150` (no `preference`) | invalid VRP syntax; keyword required |
| `ip route ... name BACKUP` | would silently discard the name |
| `vlan 10,20` + `name X` | a name cannot apply to several VLANs |
| credential lines | one-way hashes; no conversion exists |
| Serial / Tunnel / ATM interfaces | out of scope |

## 7. Documented normalisations — semantically lossless

1. `vlan batch 10 20 30` expands to individual `vlan` blocks; does not
   reconstitute as `batch`.
2. `ip address 10.0.0.1 24` normalises to `255.255.255.0` and stays dotted.

**Round-trip fidelity is measured on the IR, not the text.** Comment markers
change, separators regenerate, block order is a renderer choice — none of
that is data loss. `_comparable()` in `validation.py` excludes `source_line`
and `unmapped` (the latter is already counted by the unmapped metric;
counting it twice would double-penalise one limitation).

## 8. Semantic findings for Chapter 5

- **Static route defaults diverge:** Cisco AD 1, VRP preference 60. An
  unqualified static route translates perfectly but lands with different
  precedence. Both renderers emit one warning per config.
- **Credentials are fundamentally non-translatable** (one-way,
  vendor-specific hash algorithms).

---

## 9. Evaluation

| # | Hypothesis | Target | Current |
|---|---|---|---|
| H1a | in-scope coverage | >= 95% | **100.0%** |
| H1b | corpus coverage | reported | **83.7%** |
| H2 | round-trip fidelity | >= 95% | **100.0%** |
| H3a | Packet Tracer load | >= 90% | pending |
| H3b | documentation conformance | reported | **83%** (19/23) |
| H4 | time vs manual baseline | >= 80% | pending baseline |
| H5 | AI suggestion accuracy | no target | pending |

**Never claim "0% error rate."** It is circular: the engine is correct by
definition for cases we wrote rules for.

---

## 10. Freeze dates

- **20 Sep — RULE FREEZE (passed).** No new translation rules. Discoveries
  go to Chapter 5 Future Work.
- **24 Sep — FEATURE FREEZE.** All effort moves to evaluation and writing,
  regardless of completeness. Missing this is the one unrecoverable failure:
  a thinner system with a real Chapter 4 passes; a complete system with no
  evaluation data does not.

## 11. Division of labour

- วัชรากร: engine (complete), AI fallback, unit tests
- วรานนท์: web layer, UI, persistence
- Contract: `ConversionResult.to_dict()`

## 12. Working preferences

- Explain *why* in comments where a decision is non-obvious. Several comments
  in this codebase exist to be quoted in Chapter 3.
- **Do not add dependencies.** `sqlite3`, `difflib`, `zipfile`, `ipaddress`
  are standard library. Current external deps (`requirements.txt`): fastapi,
  uvicorn, jinja2, python-multipart, google-genai, pytest, httpx (required
  by FastAPI's `TestClient`, used throughout `test_api.py`).
- No `localStorage` except for the theme toggle.
- Do not pin a Gemini model version in code or prose; it lives in config
  (`NETMIGRATE_GEMINI_MODEL`).
- Every new module gets tests. Run `python tools/run_tests.py` before
  reporting done.
- The students must be able to explain every line on 30 Sep. After writing a
  non-trivial function, explain the reasoning back rather than just reporting
  that tests pass.
