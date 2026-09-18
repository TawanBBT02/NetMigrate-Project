# Web Layer Specification (Phase 4)

Authoritative specification for the FastAPI backend and web UI. Referenced by
`CLAUDE.md` section 5. Build against this, not against improvisation.

**Constraints:** single Python runtime. FastAPI + Jinja2 + vanilla JS +
Tailwind via CDN. SQLite via the standard-library `sqlite3`. No bundler, no
npm, no new dependencies beyond those already in `requirements.txt`.

---

## 1. File layout to create

```
netmigrate/
  persistence.py        SQLite schema + data access (no web imports)
  api.py                FastAPI app, routes, SSE
  deploy_sim.py         simulated deployment log generator
templates/
  base.html             layout, nav, theme toggle
  index.html            module 1 — single conversion
  batch.html            module 2
  devices.html          module 3
  deploy.html           module 4
  dashboard.html        module 5a
  history.html          module 5b
  settings.html         module 6
static/
  app.js                shared fetch helpers, theme
  diff.js               diff view rendering
tests/
  test_persistence.py
  test_api.py
```

`persistence.py` must not import FastAPI. `api.py` must not touch IR
dataclasses — only `ConversionResult.to_dict()`.

---

## 2. Database schema

Exactly as specified in ทก.01 section 3.9. Create tables if absent on startup.

```sql
CREATE TABLE IF NOT EXISTS conversions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT    NOT NULL,          -- ISO 8601 UTC
    source_vendor      TEXT    NOT NULL,
    target_vendor      TEXT    NOT NULL,
    filename           TEXT,
    total_lines        INTEGER NOT NULL,
    significant_lines  INTEGER NOT NULL,
    rule_lines         INTEGER NOT NULL,
    ai_lines           INTEGER NOT NULL,
    unmapped_lines     INTEGER NOT NULL,
    duration_ms        REAL    NOT NULL,
    source_text        TEXT    NOT NULL,
    output_text        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS conversion_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversion_id   INTEGER NOT NULL REFERENCES conversions(id) ON DELETE CASCADE,
    source_line_no  INTEGER,
    output_line_no  INTEGER NOT NULL,
    provenance      TEXT    NOT NULL,             -- RULE | AI | UNMAPPED | GENERATED
    rule_id         TEXT,
    needs_review    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname    TEXT    NOT NULL,
    ip_address  TEXT,
    vendor      TEXT,
    os_version  TEXT,
    ssh_port    INTEGER DEFAULT 22,
    location    TEXT,
    status      TEXT    DEFAULT 'unknown',
    notes       TEXT,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lines_conversion ON conversion_lines(conversion_id);
CREATE INDEX IF NOT EXISTS idx_conversions_created ON conversions(created_at DESC);
```

**Why `conversion_lines` exists:** so Chapter 4 metrics are queryable rather
than recomputed, and so audit history can reconstruct a past diff. Do not
"optimise" it away.

Database path from `NETMIGRATE_DB` env var, default `netmigrate.db` in the
repo root. Tests must use a temporary path — never the real database.

---

## 3. API endpoints

All responses JSON unless stated. Errors return
`{"error": "<message>"}` with an appropriate status code.

### 3.1 `POST /api/convert` — module 1

Request:
```json
{
  "text": "hostname SW1\n...",
  "source_vendor": "cisco",
  "target_vendor": "huawei",
  "filename": "sw01.cfg",
  "use_ai": true
}
```
`source_vendor` may be `"auto"`, in which case detect it (see section 6).
`use_ai` defaults to true; the fallback is a no-op without an API key.

Response: the `ConversionResult.to_dict()` payload, plus:
```json
{ "conversion_id": 42, "detected_source": "cisco" }
```

Persist the conversion and all its lines before responding.

### 3.2 `POST /api/convert/batch` — module 2

`multipart/form-data`. Fields: `files` (repeated), and a JSON string field
`options` mapping filename to `{source_vendor, target_vendor}`.

Accept `.cfg`, `.txt`, `.conf` only. Reject anything above 1 MB per file or
20 files per request with a 400.

Response:
```json
{
  "batch_id": "b3f1...",
  "results": [
    {"filename": "sw01.cfg", "conversion_id": 43, "ok": true,
     "metrics": {...}},
    {"filename": "bad.cfg", "ok": false, "error": "..."}
  ]
}
```

Process sequentially. One file failing must not abort the batch.

### 3.3 `GET /api/batch/{batch_id}/zip` — module 2

Returns `application/zip` built with `zipfile` in memory. One `.cfg` per
successfully converted file, named `<stem>_<target_vendor>.cfg`. 404 if the
batch id is unknown. Keep batches in a process-level dict with a cap of 50;
they need not survive restart.

### 3.4 Devices — module 3

- `GET /api/devices` — optional query params `q` (matches hostname or IP),
  `vendor`, `location`
- `POST /api/devices` — body is the device object without `id`; `hostname`
  required
- `PUT /api/devices/{id}`
- `DELETE /api/devices/{id}`

Records only. **No connectivity testing** — out of scope per `CLAUDE.md`.

### 3.5 `GET /api/deploy/stream` — module 4

`text/event-stream`. Query params: `conversion_id`, `device_id`.

Emits simulated stages with realistic delays (`asyncio.sleep`, total under
10 s): connecting, authenticating, entering config mode, sending each command,
committing, closing. Each event:

```
data: {"ts":"2026-09-20T18:00:01Z","level":"INFO","message":"Connecting to 10.0.0.1:22"}
```

`level` is one of `INFO`, `SUCCESS`, `WARNING`, `ERROR`, `COMMAND`.
Emit `COMMAND` per configuration line, and `WARNING` for any line whose
`needs_review` is true. Final event has `level` `SUCCESS` and
`"done": true`.

**This is a simulation.** No SSH, no sockets, no network. The log generator
lives in `deploy_sim.py` and is unit-testable without the web layer.

### 3.6 History — module 5b

- `GET /api/conversions?limit=50&offset=0` — newest first, summary fields
  only (no `source_text`/`output_text`)
- `GET /api/conversions/{id}` — full record including lines, for diff
  reconstruction
- `GET /api/conversions/{id}/export` — `Content-Disposition: attachment`,
  JSON of the full record
- `DELETE /api/conversions/{id}`

### 3.7 `GET /api/stats` — module 5a

```json
{
  "total_conversions": 128,
  "total_significant_lines": 3214,
  "rule_lines": 2951,
  "ai_lines": 42,
  "unmapped_lines": 221,
  "rule_coverage": 0.918,
  "flagged_for_review": 64,
  "by_direction": [{"direction": "cisco->huawei", "count": 90}],
  "recent": [{"date": "2026-09-20", "count": 12}]
}
```

`recent` covers the last 14 days. Compute with SQL aggregates over
`conversions` and `conversion_lines`, not by loading rows into Python.

### 3.8 `GET /api/health` — module 6

```json
{
  "status": "ok",
  "database": true,
  "ai_fallback": {"enabled": false, "reason": "no API key configured"},
  "rules": 16,
  "vendors": ["cisco_iosxe", "huawei_vrp"]
}
```

Never include the API key or any part of it.

---

## 4. Pages

Server-rendered Jinja2 shells; data fetched by `fetch()`. `base.html` carries
the nav and the theme toggle.

| Route | Contents |
|---|---|
| `/` | textarea or file picker, vendor selectors, Convert button, diff view, copy + download |
| `/batch` | drag-and-drop zone, per-file vendor selects, progress, ZIP download |
| `/devices` | table with search/filter, add + edit + delete |
| `/deploy` | device select, conversion select, editable CLI box, live log with level filter, download log |
| `/dashboard` | four metric cards, direction chart, 14-day activity chart |
| `/history` | paginated list, click to open stored diff, export JSON |
| `/settings` | health status, theme toggle |

### 4.1 Diff view requirements

The central UI element. Two columns, source left, output right, aligned by
line. Each output line coloured by provenance:

| Provenance | Treatment |
|---|---|
| `RULE` | normal |
| `AI` | distinct colour + review badge |
| `UNMAPPED` | distinct colour + review badge |
| `GENERATED` | muted |

Hovering an output line shows its `rule_id` and `source_line`. Any line with
`needs_review` true gets a visible marker. A legend is required — colour must
not be the only signal, since the report may be printed in greyscale.

### 4.2 Charts

Plain inline SVG or `<canvas>` drawn by hand. **Do not add a charting
library.** Two small charts do not justify a dependency.

---

## 5. Non-functional requirements

- Reject request bodies above 2 MB.
- Accept only `.cfg`, `.txt`, `.conf` by extension **and** verify the content
  decodes as UTF-8 text; reject binary.
- Never render user-supplied configuration text as HTML — escape it.
  A configuration file containing `<script>` must not execute.
- No secrets in any response, log line, or error message.
- Every endpoint returns within 2 s except the SSE stream.
- All timestamps ISO 8601 UTC.

---

## 6. Vendor auto-detection

Used when `source_vendor` is `"auto"`. Count marker occurrences:

- Huawei: `sysname`, `port link-type`, `undo shutdown`, `ip route-static`,
  `vlan batch`, `allow-pass`, `#` separators
- Cisco: `hostname`, `switchport`, `no shutdown`, `ip route `, `!` separators

Higher count wins; tie goes to Cisco. Return the decision in
`detected_source` so the UI can display it. A reference implementation
already exists in `tools/demo.py` — reuse that logic rather than inventing a
second one.

---

## 7. Testing requirements

`tests/test_persistence.py`
- schema creates cleanly on an empty temp database
- insert and read back a conversion with its lines
- metrics aggregate correctly across several conversions
- cascade delete removes a conversion's lines
- device CRUD round-trips

`tests/test_api.py` — FastAPI `TestClient`, temp database
- `POST /api/convert` returns the contract shape with all documented keys
- conversion is persisted and retrievable via `/api/conversions/{id}`
- auto-detection picks the right vendor both ways
- batch with one bad file still returns results for the good ones
- ZIP contains one entry per successful file
- device CRUD through the API
- `/api/health` responds and **contains no API key**
- config text containing `<script>alert(1)</script>` is escaped, not executed
- an oversized upload is rejected with 400
- SSE stream yields events and terminates with `done: true`

**Do not weaken an engine test to make a web test pass.** The engine is
frozen; if a web test needs the engine to behave differently, the web code is
wrong.
