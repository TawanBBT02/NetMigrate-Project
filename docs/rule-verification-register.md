# NetMigrate — Rule Verification Register

**Companion to** `netmigrate-mapping-spec.md`
**Purpose:** record, per rule, what evidence supports the mapping and what is
still unverified. This is the source table for Appendix A citations and for
the documentation-conformance measurement (H3b).

**Status as of 20 Sep 2026.** Updated from the original 16 Sep draft: the
VLAN 40-element bug (finding 1) is fixed and tested, the interface-name
abbreviation question (finding 2) has been decided, and a fourth UNVER row
(`fast`/`Ethernet`) was added below — it was missing from the original
table even though it was always in `rule_catalog.py`.

---

## How to read the status column

| Status | Meaning |
|---|---|
| **DOC** | Confirmed against official vendor documentation. Reference given. |
| **EX** | Confirmed by an official vendor *configuration example* (weaker than a command reference, but still citable and primary). |
| **SIM** | Loaded successfully in a device simulator. Record which. |
| **UNVER** | Not yet verified against any primary source. **Must be resolved or declared.** |

**An UNVER row is not a claim.** Any rule still marked UNVER at submission
must either be verified, or named in Chapter 5 as an unverified mapping. Do
not present UNVER rules as validated.

I have verified the rows marked DOC/EX below against the references listed.
Every remaining row is UNVER and needs your attention — I have not checked
them, and you should not assume they are correct because the code passes
tests. Tests only prove the code matches our belief.

---

## Primary references used

| Ref | Document | URL |
|---|---|---|
| **H-VLAN** | Configuring Interface-based VLAN Assignment — CloudEngine S5700/S6700 V600R022C00 Configuration Guide, Ethernet Switching | support.huawei.com/enterprise/en/doc/EDOC1100278261/c213d155 |
| **H-EX-VLAN** | Typical VLAN Configuration — S300/S500/S2700/S3700/S5700/S6700/S7700/S9700 Typical Configuration Examples (V200) | support.huawei.com/enterprise/en/doc/EDOC1000069520/b699322c |
| **H-ROUTE** | ip route-static — S1700/S2720/S5700/S6700 V200R020C00 Command Reference (also V200R019C10, AR V300R019) | support.huawei.com/enterprise/en/doc/EDOC1100176877/ac7caed7 |
| **H-ETH** | Eth-Trunk Interface Configuration — NE5000E V800R022C00SPC500 Configuration Guide (carrier platform; same command form) | support.huawei.com/enterprise/en/doc/EDOC1100278760/20c76fcd |
| **H-IFBASE** | Basic Interface Configuration Commands — S1700/S2720/S5700/S6700 V200R019C10 Command Reference | support.huawei.com/enterprise/en/doc/EDOC1100127035/cdd85713 |
| **H-VLANCMD** | VLAN Configuration Commands — S5700/S6700 V200R025C00 Command Reference (**not yet read — see open items**) | support.huawei.com/enterprise/en/doc/EDOC1100514211/834147df |
| **H-EX-OSPF** | Typical OSPF Configuration — same series, Typical Configuration Examples | support.huawei.com/enterprise/en/doc/EDOC1000069520/a25a2d1a |

Fill in the exact document version and access date before submission. Cisco
references are still to be added — Packet Tracer validation will cover most
of them, but cite the IOS-XE command reference for anything the simulator
cannot confirm.

---

## Verification register

### System level

| Rule | Huawei form | Status | Evidence |
|---|---|---|---|
| `sysname` | `sysname SW1` | **EX** | H-EX-VLAN shows `# sysname SwitchA` in saved config |
| comment marker | `#` | **EX** | H-EX-VLAN, H-EX-OSPF both use `#` as block separator |
| terminator | `return` | **EX** | H-EX-VLAN, H-EX-OSPF both end with `# return` |
| `system-view` | config mode entry | **DOC** | H-VLAN: "Enter the system view" |
| `undo` negation | `undo shutdown` | **EX** | H-ETH shows `undo shutdown` in interface view in an official configuration guide |

### VLAN

| Rule | Huawei form | Status | Evidence |
|---|---|---|---|
| `vlan.create` | `vlan 10` | **DOC** | H-VLAN prerequisite: "Create a VLAN" |
| `vlan batch` | `vlan batch 2 to 3` | **EX** | H-EX-VLAN, H-EX-OSPF both show `vlan batch` |
| `vlan.name` | `name SALES` | UNVER | **still open** — attested in community references (`vlan 101` / `name Hotcakes`) but not confirmed in a Huawei command reference |

> **Action — highest remaining priority.** `vlan.name` is the weakest rule in
> the set. Open **H-VLANCMD** (URL in the reference table above) and look for
> the `name` command in VLAN view. It is almost certainly there; we simply
> have not read the page. Ten minutes of desk work closes this.

### Interface and port

| Rule | Huawei form | Status | Evidence |
|---|---|---|---|
| interface view | `interface GigabitEthernet0/0/1` | **EX** | H-EX-VLAN, H-EX-OSPF |
| `Vlanif` | `interface Vlanif30` | **EX** | H-EX-OSPF shows `interface Vlanif30` |
| `port.link-type` access | `port link-type access` | **DOC** | H-VLAN + H-EX-VLAN |
| `port.access-vlan` | `port default vlan 2` | **DOC** | H-VLAN + H-EX-VLAN |
| `port.link-type` trunk | `port link-type trunk` | **DOC** | H-VLAN + H-EX-VLAN |
| `port.trunk-allowed` | `port trunk allow-pass vlan { { vlan-id1 [ to vlan-id2 ] } &<1-40> \| all }` | **DOC** | H-VLAN gives the full syntax spec |
| `port.trunk-native` | `port trunk pvid vlan vlan-id` | **DOC** | H-VLAN: "To change the default VLAN of a trunk interface, run `port trunk pvid vlan vlan-id`" |
| `interface.description` | `description X` | UNVER | not shown in either example |
| `interface.ip` | `ip address 192.168.3.2 255.255.255.0` | **EX** | H-EX-OSPF |
| `interface.shutdown` | `shutdown` / `undo shutdown` | **EX** | H-ETH — official config guide, interface view |
| `XGE` | `interface XGE0/0/1` | **DOC** | H-IFBASE lists "XGE interface view" among valid command views |
| `Eth-Trunk` | `interface Eth-Trunk1` | **EX** | H-ETH shows `interface Eth-Trunk1` |
| `LoopBack` | `interface LoopBack0` | UNVER | **still open** — our own corpus uses it but no primary citation found |
| `fast` (`FastEthernet` ↔ `Ethernet`) | `interface Ethernet0/0/1` | UNVER | **missing from this register originally** — `rule_catalog.py` has carried this as UNVER with reference `-` since it was written; added here so the register matches the code it is supposed to track |

### Static routing

| Rule | Huawei form | Status | Evidence |
|---|---|---|---|
| `route.static` | `ip route-static 172.16.0.0 255.255.0.0 NULL0` | **EX** | H-EX-OSPF |
| `route.static` + preference | `ip route-static ip-address { mask \| mask-length } [ nexthop-address \| interface-type interface-number [ nexthop-address ] ] [ preference preference \| tag tag ] *` | **DOC** | H-ROUTE — **RESOLVED 18 Sep** |

> **RESOLVED.** The command reference confirms `preference` is a keyword
> parameter, not a bare positional integer. Our renderer emits it correctly
> and our parser is right to reject a bare trailing integer as invalid VRP.

> **NEW FINDING — semantic non-equivalence, not a syntax issue.**
> The same pages state: *"If no preference is configured for a static route,
> the static route uses the default preference 60."* Cisco's default
> administrative distance for a static route is 1.
>
> So an unqualified static route has **different precedence relative to
> dynamic routing protocols on each platform**. The syntax translates
> perfectly; the behaviour does not. This is the clearest concrete example in
> the project of the syntax-acceptance vs behavioural-equivalence gap already
> named as a threat to validity in ทก.01 §2.6.3(จ) — use it there.
>
> Handled in code as of 18 Sep: both renderers emit a single review comment
> per configuration when any static route relies on the vendor default.
> Once per config, not per route, to stay readable. Six tests cover it.
>
> **Still to verify:** the corresponding default preferences for OSPF. If
> VRP's OSPF preference is lower than its static-route preference of 60
> while Cisco's OSPF distance of 110 is higher than its static distance of 1,
> then the relative ordering of static and OSPF routes is *inverted* between
> vendors. Confirm both numbers in the command references before asserting
> this in Chapter 5 — it would be a strong finding, and a wrong one would be
> embarrassing.

### OSPF — structural (class S)

Confirmed by H-EX-OSPF, which shows exactly the structure our renderer
produces:

```
#
ospf 1 router-id 10.4.4.4
 import-route static
 area 0.0.0.1
  network 192.168.3.0 0.0.0.255
  network 192.168.4.0 0.0.0.255
  nssa
#
```

| Rule | Huawei form | Status | Evidence |
|---|---|---|---|
| `ospf.process` + router-id on process line | `ospf 1 router-id 10.4.4.4` | **EX** | H-EX-OSPF |
| `ospf.area` as nested block, dotted-decimal | `area 0.0.0.1` | **EX** | H-EX-OSPF |
| `ospf.network` nested under area, no area argument | `network 192.168.3.0 0.0.0.255` | **EX** | H-EX-OSPF |
| area ID integer ↔ dotted conversion | `area 1` → `0.0.0.1` | **EX** | H-EX-OSPF uses `0.0.0.1`; VRP area view prompt is `[...-ospf-1-area-0.0.0.1]` |

This is the strongest-evidenced part of the rule set, which is fortunate
since it is the part the thesis argument rests on.

---

## Findings requiring code changes

### 1. VLAN list exceeds the documented 40-item limit — RESOLVED

H-VLAN gives the syntax as:

```
port trunk allow-pass vlan { { vlan-id1 [ to vlan-id2 ] } &<1-40> | all }
```

`&<1-40>` means **at most 40 repetitions** of the `vlan-id [to vlan-id]`
element in a single command. The original `render_vlan_list_huawei()`
emitted one line regardless of length, which would produce a command a real
device rejects for a trunk allowing 50+ discrete, non-contiguous VLANs.

**Fixed.** `transforms.py` now defines `HUAWEI_VLAN_ELEMENTS_PER_COMMAND =
40` and `split_vlan_list_huawei()`, which splits into multiple
`port trunk allow-pass vlan` lines of ≤40 elements each — a *range* still
counts as one element, matching `&<1-40>` exactly (`10 to 200` is one item,
not 191). The Huawei parser's existing `|=` accumulation across repeated
`allow-pass` lines means the round trip is unaffected. Covered by
`test_forty_one_elements_splits`, `test_split_preserves_every_vlan`, and
`test_long_list_round_trips_through_split` in `test_scope_additions.py`.

### 2. Interface name abbreviation — decided: keep abbreviations

The open question was whether the renderer should emit `GE0/0/1` (matches
the input abbreviation, but not what a Huawei device's own saved config
shows) or `GigabitEthernet0/0/1` in full (matches real VRP saved config,
per H-EX-VLAN/H-EX-OSPF, at the cost of regenerating goldens).

**Decided: option (b), keep abbreviations.** `INTERFACE_TYPES` in
`rule_catalog.py` and Appendix ก §ก.3 both emit the short forms (`GE`,
`XGE`, `Ethernet`, `LoopBack`, `Vlanif`, `Eth-Trunk`, `NULL`) — this was the
opposite of what this register originally recommended. Since the goldens
and all currently-passing tests are built against the abbreviated form,
re-opening this now would mean re-verifying every golden fixture against
device output during feature freeze for a cosmetic change with no coverage
or correctness benefit. Noted as a documented choice for Chapter 5 rather
than revisited.

### 3. Port numbering — evidence is better than feared

Earlier I flagged `GE0/1` (two-part) as likely invalid on Huawei hardware.
The official examples show **both** `GigabitEthernet0/0/1` and
`GigabitEthernet1/0/1`, so three-part notation with a non-zero slot is normal
on S-series. That does not confirm two-part notation is accepted, but it does
mean the slot-number warning we emit is well founded.

Still UNVER. The single command `interface GE0/1` on a device settles it.

---

## What to do with this register

1. Work down the UNVER rows. Each one needs either a command-reference URL or
   an explicit entry in Chapter 5.
2. **Four rows remain UNVER as of 20 Sep (rule freeze):** `vlan.name`,
   `interface.description`, `fast`/`Ethernet`, and `loopback`/`LoopBack`. All
   four are low-risk — they are ubiquitous in real configurations and none
   carries a semantic trap — but each must either be cited or named in
   Chapter 5. Past the rule freeze, closing these is a citation lookup only
   (updating `status`/`reference` in `rule_catalog.py`), never a behaviour
   change, so it remains safe to do until submission if time allows.
3. Appendix A is auto-generated from `rule_catalog.py` via
   `tools/make_appendix.py` — it already carries a status and reference
   column per rule, sourced from this register. `test_catalog.py` enforces
   that every code rule has a catalog entry and vice versa, so the appendix
   cannot silently drift from the code.
4. Report **H3b documentation conformance** as: rules with DOC or EX status ÷
   total rules. Current state (Appendix ก §ก.1): **19 of 23 checked items**
   carry primary evidence ≈ 83%, up from 14/22 (64%) at the 16 Sep draft of
   this register — five items were verified against DOC/EX sources since
   then, entirely as a citation exercise; no rule logic changed to produce
   this.

Being able to say "83% of rules carried primary vendor citations by rule
freeze, with the remaining four named explicitly rather than presented as
validated" is a much stronger position than an unqualified claim that the
mapping is correct.