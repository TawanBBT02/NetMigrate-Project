# Analysis: unmapped lines in Core-Switch-01 conversion

Source: hand-written Cisco config, 10 unmapped lines out of the conversion.
Written 20 Sep 2026. Material for Chapter 5.

---

## 1. The finding: "no translation rule" conflates four different situations

The current output labels all 10 lines identically:

```
# [NETMIGRATE-REVIEW] source line N: <command>
```

But those 10 lines are unmapped for four genuinely different reasons, and the
right action differs for each. A reviewer who knows networking will notice
this, so it is better named than discovered.

| Category | Meaning | Lines | Right action |
|---|---|---|---|
| **A — Out of scope but mappable** | a clean equivalent exists; the feature family is simply outside our declared scope | 6 | Future Work; highest-value extension |
| **B — Semantic no-op on target** | no command needed because the target does it by default | 1 | emit "not required on target", not "no rule" |
| **C — Operational, not configuration** | the command does not belong in a saved config at all | 1 | note that it is an operational step |
| **D — Credential material** | see section 3 — current message is partly wrong | 2 | correct the wording |

---

## 2. Line-by-line

### Category A — mappable, out of declared scope (6 lines)

| # | Cisco (source) | Huawei VRP equivalent | Family | Confidence |
|---|---|---|---|---|
| 26 | `spanning-tree portfast` | `stp edged-port enable` | STP | high |
| 35 | `ip default-gateway 192.168.20.1` | `ip route-static 0.0.0.0 0.0.0.0 192.168.20.1` | routing | high (functional equivalent) |
| 38 | `ip domain-name mynetwork.local` | `dns domain mynetwork.local` | DNS | medium — **verify** |
| 41 | `line vty 0 4` | `user-interface vty 0 4` | AAA/access | high |
| 42 | `login local` | `authentication-mode aaa` | AAA/access | high |
| 43 | `transport input ssh` | `protocol inbound ssh` | AAA/access | high |

These six are the strongest Future Work candidates. Each is a clean
substitution, most are class D, and together they are the difference between
a config an engineer can load and one they must finish by hand. They were
excluded by the scope declaration in ทก.01 §2.3.2.3, not by technical
difficulty.

**Note the `ip default-gateway` case is more subtle than it looks.** On Cisco
it is used specifically when IP routing is disabled on a layer-2 switch. The
VRP equivalent is a default static route, which is the same *behaviour* by a
different *mechanism*. Translating it would require knowing whether IP routing
is enabled — so it is mappable, but not by a simple substitution rule. Worth
saying so; it is a better example than the trivial ones.

### Category B — semantic no-op (1 line)

| # | Cisco (source) | Huawei VRP |
|---|---|---|
| 17 | `switchport trunk encapsulation dot1q` | *no command required* |

802.1Q is the only trunk encapsulation VRP supports, so it needs no
configuration. Cisco needs the command because older platforms also supported
ISL.

**This line is not untranslatable — it is already satisfied.** Reporting it as
"no translation rule" is misleading: it implies something is missing from the
output when the output is complete. The correct message is that the target
requires no equivalent.

### Category C — operational, not configuration (1 line)

| # | Cisco (source) | Huawei VRP |
|---|---|---|
| 39 | `crypto key generate rsa modulus 2048` | `rsa local-key-pair create` (interactive) |

This is an *action*, not a stored setting. It does not appear in
`show running-config` output on a real device — it appears here only because
the source was hand-written rather than exported from hardware. The VRP
equivalent is likewise interactive and prompts for a key length.

Correct handling: note that this is a one-time operational step to perform on
the target device, not a line to place in a configuration file.

### Category D — credentials (2 lines) — see section 3

| # | Cisco (source) |
|---|---|
| 3 | `enable secret Cisco@1234` |
| 6 | `username admin privilege 15 secret Admin@5678` |

---

## 3. The credential message is factually wrong for this input

Current output says:

> Password hashes cannot be converted between vendors (one-way,
> vendor-specific algorithms).

**But these are not hashes.** `Cisco@1234` and `Admin@5678` are plaintext.
The source config was hand-written, so the passwords appear in clear text
rather than as `$1$...` or `$9$...` digests.

When the plaintext is present, conversion **is** possible:

| Cisco | Huawei VRP | Confidence |
|---|---|---|
| `enable secret Cisco@1234` | `super password level 15 cipher Cisco@1234` | medium — **verify** |
| `username admin privilege 15 secret Admin@5678` | `aaa` → `local-user admin password irreversible-cipher Admin@5678` → `local-user admin privilege level 15` | high |

So the system's reasoning is right for the common case (a config exported from
a device, where credentials are hashed) and wrong for this case (a
hand-written config with plaintext).

### Recommended fix — wording only, not a new rule

The detector already identifies credential lines. It should distinguish
whether the value looks hashed:

- Cisco hash markers: `secret 5 $1$`, `secret 8 $8$`, `secret 9 $9$`,
  `password 7 <hex>`
- Huawei: `irreversible-cipher`, `cipher %^%#`

**If hashed** — keep the current message. It is correct.

**If plaintext** — say so instead:

```
# [NETMIGRATE-REVIEW] source line 3: enable secret Cisco@1234
#   Credential value appears to be plaintext, so an equivalent exists.
#   NOT applied automatically: credentials must be set deliberately by an
#   operator, and this file may be shared or stored. Suggested target form:
#     super password level 15 cipher <PASSWORD>
```

**Still do not auto-apply it.** The reason changes from "impossible" to
"deliberately withheld", which is a defensible policy: writing a live
credential into a generated file that gets emailed or committed is a security
problem regardless of whether it is technically convertible.

This is a **message change, not a translation rule**, so it does not violate
the 20 Sep rule freeze. It corrects a factually inaccurate statement in
system output, which is worth fixing before submission.

---

## 4. Answering "these are essential for the actual device"

Correct — the converted file alone will not produce a working switch. Here is
the completion an engineer would apply by hand, in order:

```
# --- items NetMigrate flagged, completed manually ---
#
dns domain mynetwork.local
#
ip route-static 0.0.0.0 0.0.0.0 192.168.20.1
#
aaa
 local-user admin password irreversible-cipher <PASSWORD>
 local-user admin privilege level 15
 local-user admin service-type ssh
#
super password level 15 cipher <PASSWORD>
#
interface GE0/2
 stp edged-port enable
#
user-interface vty 0 4
 authentication-mode aaa
 protocol inbound ssh
#
# operational step, run interactively on the device (not a config line):
#   rsa local-key-pair create
#
# no equivalent required: switchport trunk encapsulation dot1q
#   (802.1Q is the only trunk encapsulation VRP supports)
```

**Verify `dns domain` and `super password` against the VRP command reference
before using or citing them.** They are the two entries above I am least
certain of.

---

## 5. Why this strengthens the thesis rather than weakening it

The instinct is to read 10 unmapped lines as a shortfall. The more useful
reading is that this single 43-line configuration produced a **taxonomy of
untranslatability** that the proposal did not anticipate:

1. **Out of scope but mappable** — a scope decision, reversible, quantifiable
2. **Semantic no-op** — the target needs nothing; output is already complete
3. **Operational, not configuration** — belongs to a procedure, not a file
4. **Credential material** — technically convertible when plaintext,
   deliberately withheld for security

Only category 1 represents work not done. Categories 2 and 3 are cases where
"unmapped" *overstates* the problem, and category 4 is a policy choice rather
than a limitation.

This directly qualifies the H1b corpus-coverage figure of 83.7%: that number
counts categories 1–4 together, so it **understates** how complete the output
actually is. Stating this is more honest than either ignoring it or claiming a
higher coverage number.

### Proposed Chapter 5 structure

- 5.x.1 Taxonomy of unmapped constructs (the four categories above)
- 5.x.2 Mappable out-of-scope families as prioritised future work
  (STP, AAA/vty, DNS, default gateway — six rules, all class D)
- 5.x.3 Credential handling: technical possibility versus security policy
- 5.x.4 Consequence for interpreting H1b

### Recommended code change before 24 Sep — one item only

Split the credential message into hashed and plaintext variants (§3). Roughly
20 lines in `transforms.py` plus two tests. It corrects a false statement in
system output.

**Do not add the six category-A rules.** Rule freeze passed on 20 Sep, they
are out of declared scope, and they are worth far more as a quantified
Future Work section than as six rules rushed in four days before submission.
