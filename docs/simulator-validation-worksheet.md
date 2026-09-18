# Simulator validation worksheet (H3)

**Hypothesis H3:** converted output loads in the vendor simulator without
syntax error, target ≥ 90% of sampled files.

**Date:** ____________  **Tester:** ____________
**eNSP version:** ____________  **Packet Tracer version:** ____________
**Device models used:** Huawei ____________  Cisco ____________

---

## Before you start

Generate the paste files:

```bash
python tools/make_paste.py --chunk 20
```

They land in `corpus/paste/`. Paste each part **in order**. Files with
`.part1`, `.part2` must be pasted sequentially into the same device without
resetting it.

### Two causes of failure — record which

| Code | Meaning | Counts against H3? |
|---|---|---|
| **M** | Mapping error — our translation is wrong | **Yes** |
| **P** | Platform limitation — valid VRP/IOS-XE, unsupported on this modelled device | **No** — note it as a threat to validity |

An `XGE` port failing on an S5700 with no 10G ports is **P**, not **M**.
Getting this wrong corrupts the H3 number.

---

## Priority test — do this one first

`interface GE0/1` is emitted when the Cisco source used two-part notation
(`GigabitEthernet0/1`). Huawei hardware conventionally uses three-part
notation (`GE0/0/1`). Our renderer preserves the numeric portion verbatim.

**Test:** on an S5700 in `system-view`, type:

```
interface GE0/1
```

**Note:** the review warning for this case already exists —
`slot_needs_review()` in `transforms.py` flags any non-zero slot in
slash notation regardless of what this test finds, and it is past rule
freeze so it cannot be made stricter or looser based on the result. What
this test settles is only whether the warning's premise is correct, for
Chapter 5's threats-to-validity discussion, not whether code changes.

| Result | Meaning | Action |
|---|---|---|
| Accepted | VRP normalises or accepts two-part | note in Chapter 5 that the existing warning is conservative (fires even when the device would accept it) |
| Rejected | confirms the warning is catching a real failure, not a false positive | cite this result as evidence the warning is well-founded |

Outcome: ☐ accepted  ☐ rejected
Exact error text if rejected: ______________________________________

---

## Command-level checks (Huawei / eNSP)

Type each individually in `system-view` before pasting whole files. This
isolates which command fails rather than which file fails.

| # | Command | Result | Code | Error text |
|---|---|---|---|---|
| 1 | `sysname SW01` | ☐ ok ☐ fail | | |
| 2 | `vlan 10` then `name SALES` | ☐ ok ☐ fail | | |
| 3 | `interface GE0/0/1` | ☐ ok ☐ fail | | |
| 4 | `port link-type access` | ☐ ok ☐ fail | | |
| 5 | `port default vlan 10` | ☐ ok ☐ fail | | |
| 6 | `port link-type trunk` | ☐ ok ☐ fail | | |
| 7 | `port trunk allow-pass vlan 10 20 30 to 35` | ☐ ok ☐ fail | | |
| 8 | `port trunk pvid vlan 99` | ☐ ok ☐ fail | | |
| 9 | `undo shutdown` | ☐ ok ☐ fail | | |
| 10 | `interface Vlanif10` (VLAN 10 must exist first) | ☐ ok ☐ fail | | |
| 11 | `ip address 192.168.10.1 255.255.255.0` | ☐ ok ☐ fail | | |
| 12 | `interface LoopBack0` | ☐ ok ☐ fail | | |
| 13 | `ip route-static 0.0.0.0 0.0.0.0 192.168.10.254` | ☐ ok ☐ fail | | |
| 14 | `ip route-static 172.16.0.0 255.255.0.0 10.0.0.1 preference 150` | ☐ ok ☐ fail | | |
| 15 | `ospf 1 router-id 2.2.2.2` | ☐ ok ☐ fail | | |
| 16 | then `area 0.0.0.0` | ☐ ok ☐ fail | | |
| 17 | then `network 192.168.20.0 0.0.0.255` | ☐ ok ☐ fail | | |
| 18 | `interface XGE0/0/25` | ☐ ok ☐ fail | | |

Rows 7, 14, 16–17 are the ones I would bet on failing. Row 7 uses the `to`
range keyword, row 14 the `preference` keyword, rows 16–17 the nested area
block — all three are places where our mapping asserts something the
documentation implies but we have not verified on a device.

Row 18 is almost certainly **P**, not **M**.

---

## Command-level checks (Cisco / Packet Tracer)

`enable`, then `configure terminal`.

| # | Command | Result | Code | Error text |
|---|---|---|---|---|
| 1 | `hostname SW01` | ☐ ok ☐ fail | | |
| 2 | `vlan 10` then `name SALES` | ☐ ok ☐ fail | | |
| 3 | `interface GigabitEthernet0/1` | ☐ ok ☐ fail | | |
| 4 | `switchport mode access` | ☐ ok ☐ fail | | |
| 5 | `switchport access vlan 10` | ☐ ok ☐ fail | | |
| 6 | `switchport mode trunk` | ☐ ok ☐ fail | | |
| 7 | `switchport trunk allowed vlan 10,20,30-35` | ☐ ok ☐ fail | | |
| 8 | `switchport trunk native vlan 99` | ☐ ok ☐ fail | | |
| 9 | `interface Vlan20` | ☐ ok ☐ fail | | |
| 10 | `interface Loopback0` | ☐ ok ☐ fail | | |
| 11 | `ip route 10.0.0.0 255.0.0.0 10.0.0.1 200` | ☐ ok ☐ fail | | |
| 12 | `router ospf 1` then `router-id 2.2.2.2` | ☐ ok ☐ fail | | |
| 13 | then `network 10.5.0.0 0.0.0.255 area 5` | ☐ ok ☐ fail | | |
| 14 | `interface TenGigabitEthernet0/0/25` | ☐ ok ☐ fail | | |

Note: Packet Tracer's 2960 uses `FastEthernet0/1` and `GigabitEthernet0/1`.
A 3750 or 3560 gives you more. `TenGigabitEthernet` on a 2960 is **P**.

---

## File-level results — this table is H3

One row per paste file. "Loaded" means every line accepted with no `^`
marker (VRP) or `%` error (IOS).

| File | Target | Device | Loaded? | Failing line | Code | Notes |
|---|---|---|---|---|---|---|
| sw01-access.huawei.txt | VRP | | ☐ yes ☐ no | | | |
| rtr01-ospf.huawei.txt | VRP | | ☐ yes ☐ no | | | |
| sw02-trunk.cisco.part1.txt | IOS | | ☐ yes ☐ no | | | |
| sw02-trunk.cisco.part2.txt | IOS | | ☐ yes ☐ no | | | |

**H3 result:** ______ of ______ files loaded = ______ %
Counting **M** failures only; **P** failures excluded and listed separately.

**P failures excluded:** ______________________________________________

---

## Verification after loading

Loading without error proves the syntax was *accepted*. It does not prove
the configuration *behaves* the same — that distinction is already recorded
as a threat to validity in ทก.01 §2.6.3(จ). Still, two cheap checks are worth
running because they catch semantic errors syntax checking cannot:

**On VRP:**
```
display current-configuration
display vlan
display interface brief
display ip routing-table
display ospf brief
```

**On IOS:**
```
show running-config
show vlan brief
show ip interface brief
show ip route
show ip ospf
```

Compare `display vlan` / `show vlan brief` against the VLAN list in the
source file. If VLAN 35 is missing from a trunk after you loaded
`allow-pass vlan 10 20 30 to 35`, the range transform is wrong even though
the command was accepted — and that is the single most operationally
dangerous error class in this project.

Trunk VLAN membership verified correct: ☐ yes ☐ no
OSPF areas match source: ☐ yes ☐ no

---

## Screenshots to capture for the report

1. Successful paste of a full file, showing no errors — Chapter 4 evidence
2. `display current-configuration` output after loading
3. `display vlan` showing correct trunk membership
4. Any genuine **M** failure, with the error marker visible — these belong in
   Chapter 5 Limitations and make the evaluation more credible, not less

A report that shows one honest failure and explains it reads as more
trustworthy than one claiming everything worked.

---

## After the session

1. Enter the file-level results into the `simulator_load` column of
   `results.csv`.
2. Rule freeze (20 Sep) has passed. Any **M** failure found now goes to
   Chapter 5 Future Work, not into the code — this worksheet no longer
   feeds back into `rules_cisco.py` / `rules_huawei.py` / `render_*.py`.
3. The `interface GE0/1` slot-number warning (priority test above) is
   already implemented regardless of what this session finds — use the
   result to describe the warning's precision in Chapter 5, not to change
   code.
