# NetMigrate — project context

Cisco IOS-XE ↔ Huawei VRP configuration translator.
Senior project (ปริญญานิพนธ์). Hard deadline 30 Sep 2026.

## Architecture — do not change without discussion
Parser → vendor-neutral IR → renderer. NOT line-by-line regex.
Reason: OSPF is a structural (class S) transformation — router-id promotes
onto the process line, networks regroup under area parents, area IDs convert
integer ↔ dotted-decimal. Line-by-line substitution cannot express this.

Rules are classified D (direct), T (transform), S (structural).
See docs/netmigrate-mapping-spec.md — it is authoritative.

## Hard rules
- Single Python runtime. No Node.
- SQLite for persistence, never in-memory.
- AI fallback fires ONLY when the parser emits an UnmappedBlock.
  Never when an API key merely exists.
- AI output is NEVER written into the uncommented config body. Commented
  suggestion with a review tag, always.
- Model self-reported confidence is displayed but excluded from metrics.
- Interface type is translated; the numeric portion is preserved verbatim.
  Non-zero slot number → emit a review warning.
- admin_down is tri-state. None means the source was silent — stay silent.

## Freeze dates
- 20 Sep: rule freeze. No new rules after this; they go to Future Work.
- 24 Sep: feature freeze. All effort moves to evaluation and writing.

## Division of labour
- วัชรากร: engine — parser, IR, rule engine, AI fallback, unit tests
- วรานนท์: web + data — UI, batch, inventory, deployment sim, dashboard, SQLite
- Contract between them: ConversionResult.to_dict() in netmigrate/ir.py

## Testing
pytest. Every rule gets a unit test before implementation.
The test suite is the evidence base for Chapter 4 — do not weaken tests
to make code pass.