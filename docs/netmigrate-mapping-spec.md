# NetMigrate — Command Mapping Specification

**Scope:** Cisco IOS-XE ↔ Huawei VRP, bi-directional
**Status:** v1 — freeze by Sep 20, 2026
**Purpose:** Authoritative rule set for the Rule Engine. Also the source table for Chapter 3 (System Design).

---

## 0. How to read this document

Each rule has a **class** that determines implementation difficulty:

| Class | Meaning | Implementation |
|---|---|---|
| **D** | Direct | 1:1 token or line substitution |
| **T** | Transform | 1:1 line, but a value needs reformatting |
| **S** | Structural | Block nesting or line ordering changes; requires the intermediate model |

Rules marked **S** cannot be done with line-by-line regex. Build the intermediate
representation (IR) first or these will fail.

---

## 1. Global / system-level

| Class | Cisco IOS-XE | Huawei VRP | Notes |
|---|---|---|---|
| D | `hostname SW1` | `sysname SW1` | |
| D | `configure terminal` | `system-view` | Config mode entry |
| D | `exit` | `quit` | Leave one level |
| D | `end` | `return` | Return to user view |
| D | `write memory` / `copy running-config startup-config` | `save` | |
| D | `!` (comment / separator) | `#` | Preserve the text after the marker |
| D | `no <command>` | `undo <command>` | Generic negation prefix — apply before other rules |

**Empty lines:** preserve verbatim in both directions. They carry readability, not semantics.

---

## 2. Interface naming

Two separate problems that the spec currently conflates.

### 2a. Type abbreviation (Class D)

| Cisco long | Cisco short | Huawei long | Huawei short |
|---|---|---|---|
| `GigabitEthernet` | `Gi` | `GigabitEthernet` | `GE` |
| `TenGigabitEthernet` | `Te` | `XGigabitEthernet` | `XGE` |
| `FastEthernet` | `Fa` | `Ethernet` | `Ethernet` |
| `Loopback` | `Lo` | `LoopBack` | `LoopBack` |
| `Vlan` | `Vl` | `Vlanif` | `Vlanif` |
| `Port-channel` | `Po` | `Eth-Trunk` | `Eth-Trunk` |

Note `Vlan10` → `Vlanif10` and `Port-channel1` → `Eth-Trunk1`. These are commonly
missed and will appear in any real switch config.

**As implemented** (`netmigrate/rule_catalog.py` `INTERFACE_TYPES`, authoritative):
renderers always emit the short/single Huawei form shown above, never a distinct
"long" Huawei spelling — matches this table except the `FastEthernet` row, corrected
above from `Eth` to `Ethernet` to match the code. `fast` and `loopback` remain UNVER
(no primary Huawei citation found yet) per `rule-verification-register.md` §ก.5.

### 2b. Port numbering (Class T — **known limitation**)

Cisco IOS-XE uses `slot/port` or `slot/subslot/port` depending on platform.
Huawei VRP conventionally uses `slot/subcard/port`.

```
Cisco switch:  GigabitEthernet1/0/1
Cisco router:  GigabitEthernet0/0/1
Huawei:        GE0/0/1
```

There is **no lossless algorithmic mapping** between these — it depends on physical
hardware layout. Decide one policy and document it:

- **Policy adopted:** preserve the numeric portion verbatim; convert only the type token.
- **Consequence:** `GigabitEthernet1/0/1` → `GE1/0/1`, which may not exist on the target device.
- **Mitigation:** emit a review warning on every interface line where the slot number is non-zero.

State this in Chapter 5 Limitations. It is an honest limitation, not a bug — but if a
reviewer finds it and you have not named it, it reads as an oversight.

---

## 3. VLAN

| Class | Cisco IOS-XE | Huawei VRP |
|---|---|---|
| D | `vlan 10` | `vlan 10` |
| D | `  name SALES` | `  name SALES` |

Huawei also supports bulk creation: `vlan batch 10 20 30`.
**Direction Huawei → Cisco:** expand `vlan batch` into one `vlan N` block per ID (Class S).
**Direction Cisco → Huawei:** do not generate `vlan batch`; emit individual blocks.

---

## 4. Interface configuration

| Class | Cisco IOS-XE | Huawei VRP | Notes |
|---|---|---|---|
| D | `interface GigabitEthernet0/0/1` | `interface GE0/0/1` | Apply §2 rules |
| D | `description UPLINK` | `description UPLINK` | Identical |
| D | `ip address 10.0.0.1 255.255.255.0` | `ip address 10.0.0.1 255.255.255.0` | Huawei also accepts `ip address 10.0.0.1 24` |
| D | `shutdown` | `shutdown` | |
| D | `no shutdown` | `undo shutdown` | |

**Semantic trap — administrative default:**
Cisco switchports default to *no shutdown*; Cisco router interfaces default to
*shutdown*. Huawei interfaces default to *undo shutdown*. A config that omits the
command entirely does not mean the same thing on both platforms. Do not attempt to
infer or inject the missing command — document the assumption that absent means
"platform default" and leave it out.

---

## 5. Switchport / port link-type

| Class | Cisco IOS-XE | Huawei VRP |
|---|---|---|
| D | `switchport mode access` | `port link-type access` |
| D | `switchport access vlan 10` | `port default vlan 10` |
| D | `switchport mode trunk` | `port link-type trunk` |
| T | `switchport trunk allowed vlan 10,20,30-35` | `port trunk allow-pass vlan 10 20 30 to 35` |
| D | `switchport trunk native vlan 1` | `port trunk pvid vlan 1` |

### VLAN list format conversion (Class T)

This needs a dedicated function, used by several rules.

```
Cisco:  comma-separated, hyphen ranges     "10,20,30-35,40"
Huawei: space-separated, "to" ranges       "10 20 30 to 35 40"
```

Implement as `parse_vlan_list(str) -> Set[int]` plus two renderers. Test it
independently — it is the single most likely place to introduce a silent data error,
and a wrong VLAN list is exactly the kind of mistake that causes an outage.

Edge cases to cover in unit tests: single ID, two adjacent IDs (`10,11` — render as
`10 11`, not `10 to 11`), a range of exactly two, unsorted input, duplicate IDs,
`switchport trunk allowed vlan add ...` (Cisco continuation syntax).

---

## 6. Static routing

| Class | Cisco IOS-XE | Huawei VRP |
|---|---|---|
| D | `ip route 10.0.0.0 255.0.0.0 192.168.1.254` | `ip route-static 10.0.0.0 255.0.0.0 192.168.1.254` |
| T | `ip route 10.0.0.0 255.0.0.0 192.168.1.254 200` | `ip route-static 10.0.0.0 255.0.0.0 192.168.1.254 preference 200` |

Cisco takes a bare trailing integer as administrative distance; Huawei requires the
explicit `preference` keyword. Huawei also accepts prefix-length form
(`ip route-static 10.0.0.0 8 192.168.1.254`) — accept it on input, emit mask form on output
for consistency.

Interface-based next hops (`ip route 10.0.0.0 255.0.0.0 GigabitEthernet0/0/1`) are in
scope and use §2 naming rules.

---

## 7. OSPF — Class S (structural)

This is the rule that justifies the intermediate model.

```
! Cisco IOS-XE
router ospf 1
 router-id 1.1.1.1
 network 10.0.0.0 0.0.0.255 area 0
 network 10.1.0.0 0.0.0.255 area 0
 network 172.16.0.0 0.0.0.255 area 1
```

```
# Huawei VRP
ospf 1 router-id 1.1.1.1
 area 0.0.0.0
  network 10.0.0.0 0.0.0.255
  network 10.1.0.0 0.0.0.255
 area 0.0.0.1
  network 172.16.0.0 0.0.0.255
```

Three transformations happen at once:

1. **router-id promotes** from a child line onto the process line.
2. **Areas become parent blocks.** Networks must be grouped by area, which means you
   cannot emit output until the whole `router ospf` block has been read.
3. **Area IDs convert to dotted-decimal.** Cisco `area 0` → Huawei `area 0.0.0.0`;
   Cisco `area 1` → `area 0.0.0.1`. Cisco also accepts dotted form, so handle both on input.

Area ID conversion is integer ↔ IPv4 notation: `0.0.0.1` is area 1, not area 1.0.0.0.

### Suggested intermediate model

```
OspfProcess {
  process_id: int
  router_id:  str | None
  areas: { area_id: int -> [ Network { address, wildcard } ] }
}
```

Parse the whole block into this, then render per vendor. Roughly 30 lines of code and
it removes an entire class of bug.

---

## 8. Unconvertible constructs

When no rule matches and the AI fallback is unavailable or declines, emit the original
line commented out with a warning tag, using the **target** vendor's comment marker:

```
# [NETMIGRATE-REVIEW] no mapping available for source line 47:
# ip nbar protocol-discovery
```

Count these. `unmapped_lines / total_lines` is your coverage metric for Chapter 4.

Known-unmappable categories to name explicitly in Chapter 5 (proprietary, no
equivalent): Cisco EEM, NBAR, IP SLA, Smart Install; Huawei NQA, traffic-policy
hierarchies, service-scheme.

---

## 9. Test corpus checklist

Target 15–30 files. Structure the corpus so each file exercises a known set of rules —
this is what makes Chapter 4 measurable rather than anecdotal.

| # | Type | Exercises |
|---|---|---|
| 1–4 | Minimal access switch | §1, §3, §4, §5 access |
| 5–8 | Trunk / multi-VLAN switch | §5 trunk, VLAN list edge cases |
| 9–12 | Router with static routes | §6, Loopback naming |
| 13–16 | Router with OSPF | §7 structural |
| 17–20 | Mixed realistic config, 100+ lines | all rules combined |
| 21–24 | Config containing proprietary features | §8 warning path, AI fallback |
| 25–30 | Reverse direction (Huawei source) | all rules, opposite direction |

For each file record: total lines, lines converted by rule engine, lines sent to AI,
lines flagged for review, and whether the output loaded successfully in a simulator.
That table is Chapter 4.

---

## 10. Round-trip test (free accuracy evidence)

Convert Cisco → Huawei → Cisco and diff against the original. Semantically equivalent
output should return to the input for all Class D and T rules. Any divergence is either
a real bug or a documented lossy transformation.

This costs almost nothing to implement, runs across your whole corpus automatically,
and gives you a quantitative accuracy figure that does not depend on manual inspection.
It is the strongest single piece of evidence you can put in Chapter 4 for the effort
involved.

---

## Rule freeze

No new rules after **Sep 20, 2026**. Anything discovered after that date goes into
Chapter 5 Future Work, not into the code.
