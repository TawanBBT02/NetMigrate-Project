# NetMigrate — Rule Verification Register

**Companion to** `netmigrate-mapping-spec.md`
**Purpose:** record, per rule, what evidence supports the mapping and what is
still unverified. This is the source table for Appendix A citations and for
the documentation-conformance measurement (H3b).

**Status as of 16 Sep 2026.**

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

### 1. VLAN list exceeds the documented 40-item limit — REAL BUG

H-VLAN gives the syntax as:

```
port trunk allow-pass vlan { { vlan-id1 [ to vlan-id2 ] } &<1-40> | all }
```

`&<1-40>` means **at most 40 repetitions** of the `vlan-id [to vlan-id]`
element in a single command. Our `render_vlan_list_huawei()` emits one line
regardless of length. A trunk allowing 50 discrete, non-contiguous VLANs
produces a command the device will reject.

**Severity:** low frequency, total failure when hit. A 50-VLAN trunk is
unusual but entirely realistic on a distribution switch.

**Fix:** split into multiple `port trunk allow-pass vlan` lines of ≤40
elements each. Our Huawei parser already accumulates repeated `allow-pass`
lines with `|=`, so the round trip is unaffected — the fix is renderer-only.

**Note:** a *range* counts as one element, so `10 to 200` is one item, not
191. Count collapsed runs, not VLAN IDs.

**Before 20 Sep.** This is a rule-level correctness fix, not a new feature.

### 2. Interface name abbreviation — cosmetic, decide deliberately

Our renderer emits `GE0/0/1`. Huawei's own saved configurations write
`GigabitEthernet0/0/1` in full — both official examples do. `GE` is a valid
input abbreviation, so output loads either way, but our output does not look
like what a device produces.

**Options:**
- **(a)** Emit full names. Output matches real VRP saved config, which makes
  the report screenshots more credible. Requires regenerating goldens.
- **(b)** Keep abbreviations and note it in Chapter 5.

I would take (a) — the whole point of the tool is output an engineer can drop
onto a device, and matching the device's own spelling removes a question a
reviewer might otherwise ask. Your call; it is a one-line change to
`INTERFACE_TYPES` plus `make_golden.py --force`.

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
2. **Three rows remain UNVER after 19 Sep:** `vlan.name`,
   `interface.description`, and `LoopBack`. All three are low-risk — they are
   ubiquitous in real configurations and none carries a semantic trap — but
   they must either be cited or named in Chapter 5. `vlan.name` first: the
   VLAN command reference URL is in the table above and has not been read.
3. Add a `verified` column to Appendix A in the thesis carrying the status and
   reference from this table.
4. Report **H3b documentation conformance** as: rules with DOC or EX status ÷
   total rules. Current state: **14 of 22 checked items** carry primary
   evidence ≈ 64%. That is an honest starting figure, and raising it is
   straightforward desk work.

Being able to say "64% of rules carried primary vendor citations at the time
of writing, rising to X% after verification" is a much stronger position than
an unqualified claim that the mapping is correct.