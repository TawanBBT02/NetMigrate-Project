# NetMigrate — Command Coverage: Future Work

Source: external review of Appendix ก against enterprise campus/branch,
pilot-deployment, and service-provider/data-center configurations.
Written 18 Sep 2026. Material for Chapter 5.

**No code changes accompany this document.** Every item below requires
editing `rules_cisco.py`, `rules_huawei.py`, `render_cisco.py`,
`render_huawei.py`, or `rule_catalog.py` — all frozen per `CLAUDE.md`
§10 ("20 Sep — RULE FREEZE... No new translation rules. Discoveries go to
Chapter 5 Future Work"). Several items (BGP, IS-IS, VRF, QoS, ACL, IPv6)
are additionally named in `CLAUDE.md` §5 as explicitly out of declared
scope. This document is how those discoveries are routed, per that rule —
the same handling already used for the trunk-encapsulation and credential
findings in `unmapped-analysis.md`.

> **Verification note carried over from the source review:** the Huawei
> VRP syntax below has not been checked against DOC/EX sources. Anything
> promoted out of this document into real rules must first go through the
> same verification process as `rule-verification-register.md`, and citing
> a mix of S-series/CloudEngine/NE product lines (as §4 below flags) needs
> to be resolved or declared, the same way UNVER rows are handled there.

---

## 1. In-scope findings — silent-error risk, not missing features

These differ from Tiers 1–3 below: they are not new command families, they
are places where an **existing, already-shipped rule** produces output
that looks converted but behaves differently or drops data. That makes
them closer in kind to the static-route AD/preference finding already in
`CLAUDE.md` §8 than to ordinary coverage gaps — worth a dedicated
Chapter 5 subsection rather than a line in a coverage table.

### 1.1 Trunk default VLANs don't match

`port.link-type` (Appendix ก §ก.2.4) converts `switchport mode trunk`
directly to `port link-type trunk`. On Cisco, a trunk with no `allowed
vlan` statement carries **all** VLANs. On a Huawei S-series trunk with no
`allow-pass` statement, only VLAN 1 crosses. A source config that relies
on the Cisco default therefore converts to something that *parses* and
*looks* equivalent, but silently drops every VLAN except 1 on the target.

Same shape as the static-route default divergence already documented: two
vendors disagree on a default, and a literal per-line translation cannot
see that disagreement. Candidate fix (not applied — future work): emit
`port trunk allow-pass vlan 2 to 4094` when no explicit allowed-VLAN line
is present, or emit a review warning the way `route.static` does for the
AD/preference case.

### 1.2 Port-channel membership isn't converted

`Port-channel` ↔ `Eth-Trunk` naming is in Appendix ก §ก.3, but nothing
converts the **member port** lines that bind an interface into the
channel:

| Cisco IOS-XE | Huawei VRP | Type |
|---|---|---|
| `channel-group 1 mode active` (member port) | `eth-trunk 1` (member) + `mode lacp` (on Eth-Trunk 1; `lacp-static` on older S-series) | S |
| `channel-group 1 mode on` | `eth-trunk 1` + manual load-balance mode (default) | S |

Without this, the rendered Eth-Trunk interface exists but is empty, and
the member-port lines fall to `cfg.unmapped` (safe — correctly counted —
but a coverage cost worth naming explicitly rather than leaving as an
anonymous unmapped line).

### 1.3 Rule variants not covered by the current matchers

Whether these currently fall to `cfg.unmapped` (safe, costs coverage) or
are partially matched by an existing rule (silent-error risk) should be
checked against the corpus before writing this up — that check itself is
in scope now, the rule fix is not:

- `switchport trunk allowed vlan add|remove|except|none` — distinct from
  the plain `allowed vlan <list>` form `port.trunk-allowed` already
  handles.
- `switchport trunk encapsulation dot1q` — already resolved; see
  `unmapped-analysis.md` §2 category B (semantic no-op, not a missing
  rule).
- `ip address ... secondary` — would be a `T` extension of
  `interface.ip`.
- `ip route ... Null0` and next-hop-plus-exit-interface forms — worth
  running against `route.static` specifically to confirm whether it
  already handles them or silently mis-renders them.

### 1.4 Cited references span different Huawei product lines

`rule-verification-register.md` cites `H-ETH` (an NE5000E — carrier
router — guide) alongside `H-VLAN`/`H-IFBASE`/`H-EX-VLAN` (S-series and
CloudEngine switch guides). Interface naming and defaults can differ
between those lines. This isn't a new rule — it's a citation-scope
caveat. Recommended action (documentation only, low risk, not done here
since it wasn't asked for): add a one-line note to
`rule-verification-register.md` stating which target platform each rule
is verified against, the same way UNVER rows are already flagged there.

---

## 2. Tier 1 — Enterprise campus and branch baseline

Appears in nearly every real campus configuration. Mostly D/T rules —
cheapest coverage gain per rule, if this becomes follow-on work.

| Area | Cisco IOS-XE | Huawei VRP | Type |
|---|---|---|---|
| NTP | `ntp server 1.2.3.4` | `ntp-service unicast-server 1.2.3.4` | D |
| Syslog | `logging host 1.2.3.4` | `info-center loghost 1.2.3.4` | D |
| Time zone | `clock timezone ICT 7 0` | `clock timezone ICT add 07:00:00` | T |
| DNS | `ip name-server 8.8.8.8` | `dns resolve` + `dns server 8.8.8.8` | S |
| SNMP | `snmp-server community X RO` | `snmp-agent community read X` | T — community string handling differs |
| SNMP info | `snmp-server location` / `contact` | `snmp-agent sys-info location` / `contact` | D |
| Banner | `banner motd ^C...^C` | `header login information "..."` | T — delimiters differ |
| VTY access | `line vty 0 4` / `login local` / `transport input ssh` | `user-interface vty 0 4` / `authentication-mode aaa` / `protocol inbound ssh` | S |
| SSH | `ip ssh version 2` | `stelnet server enable` | T |
| Local users | `username admin privilege 15 secret ...` | `aaa` / `local-user admin privilege level 15` / `local-user admin service-type ssh` | S — keep password rejection; emit user structure with placeholder only |
| DHCP relay | `ip helper-address 10.1.1.1` (on SVI) | `dhcp select relay` + `dhcp relay server-ip 10.1.1.1` | S |
| L2 default gateway | `ip default-gateway 10.0.0.1` | `ip route-static 0.0.0.0 0 10.0.0.1` | T — meaning differs; see `unmapped-analysis.md` §2 category A |
| STP mode | `spanning-tree mode rapid-pvst` | `stp mode rstp` or `mstp` | S — PVST+ has no equivalent; Huawei defaults to MSTP |
| Edge port | `spanning-tree portfast` | `stp edged-port enable` | D |
| BPDU guard | `spanning-tree bpduguard enable` (per port) | `stp bpdu-protection` (global) | S |
| OSPF passive | `passive-interface Gi0/0/1` | `silent-interface GE0/0/1` | D |
| OSPF default route | `default-information originate` | `default-route-advertise` | D |
| OSPF interface | `ip ospf cost 10` / `ip ospf network point-to-point` | `ospf cost 10` / `ospf network-type p2p` | D/T |
| OSPF per interface | `ip ospf 1 area 0` (on interface) | `ospf enable 1 area 0` (newer VRP) | S |
| Redistribution | `redistribute static subnets` | `import-route static` | T |

ACLs and DHCP relay's implicit-deny question are carried separately in §3
below since they need more care than a plain D/T addition.

---

## 3. ACLs — highest-value Tier 1 item, also the riskiest

| Area | Cisco IOS-XE | Huawei VRP | Type |
|---|---|---|---|
| Standard ACL | `access-list 10 permit 10.0.0.0 0.0.0.255` | `acl number 2000` / `rule 5 permit source 10.0.0.0 0.0.0.255` | S |
| Extended ACL | `ip access-list extended NAME` / `permit tcp ...` | `acl number 3000` or `acl name NAME advance` / `rule ... permit tcp ...` | S |
| ACL on interface | `ip access-group 101 in` | `traffic-filter inbound acl 3000` | T |
| ACL on VTY | `access-class 10 in` | `acl 2000 inbound` (under user-interface) | T |

**Why this is riskier than the rest of Tier 1, not just harder:** Cisco
ACLs have an implicit deny at the end; Huawei's behaviour for traffic
matching no rule under `traffic-filter` is generally permit and varies by
platform. A literal per-line translation would make the resulting ACL
**more permissive than the source** — a security regression disguised as
a successful conversion. Any future implementation must append an
explicit final deny rule and say so in the output, the same way
`route.static` currently emits one warning per file for the AD/preference
default. This is also why `CLAUDE.md` §5 lists ACL as explicitly out of
scope rather than merely undone — the gap is a scoping decision, not an
oversight.

---

## 4. Tier 2 — Pilot deployment

| Area | Cisco IOS-XE | Huawei VRP | Type |
|---|---|---|---|
| Gateway redundancy | `standby 1 ip 10.0.0.1` / `standby 1 priority 110` / `standby 1 preempt` | `vrrp vrid 1 virtual-ip 10.0.0.1` / `vrrp vrid 1 priority 110` | S — protocol change; virtual MAC changes; preemption defaults differ (HSRP off, VRRP on) |
| Subinterfaces | `interface Gi0/0/1.10` / `encapsulation dot1Q 10` | `interface GE0/0/1.10` / `dot1q termination vid 10` / `arp broadcast enable` | S |
| BGP neighbors | `router bgp 65001` / `neighbor x remote-as 65002` | `bgp 65001` / `peer x as-number 65002` | S |
| BGP options | `update-source Lo0` / `next-hop-self` / `ebgp-multihop 2` | `peer x connect-interface LoopBack0` / `peer x next-hop-local` / `peer x ebgp-max-hop 2` | T |
| BGP network | `network 10.0.0.0 mask 255.0.0.0` | `ipv4-family unicast` / `network 10.0.0.0 255.0.0.0` | S |
| Prefix lists | `ip prefix-list P seq 5 permit 10.0.0.0/8 le 24` | `ip ip-prefix P index 10 permit 10.0.0.0 8 less-equal 24` | T |
| Route policy | `route-map RM permit 10` / `match ip address prefix-list P` / `set local-preference 200` | `route-policy RM permit node 10` / `if-match ip-prefix P` / `apply local-preference 200` | S |
| NAT | `ip nat inside` / `ip nat outside` / `ip nat inside source list 1 interface Gi0/0/0 overload` | `nat outbound 2000` (on outside interface) | S — Cisco inside/outside model vs Huawei per-interface |
| DHCP server | `ip dhcp pool P` / `network` / `default-router` / `dns-server` | `ip pool P` / `network` / `gateway-list` / `dns-list` + `dhcp select global` | S |
| TACACS+ | `tacacs server X` / `aaa authentication login default group tacacs+ local` | `hwtacacs-server template X` + `aaa` scheme + domain | S |
| RADIUS | `radius server X` | `radius-server template X` + domain | S |
| DHCP snooping | `ip dhcp snooping` / `ip dhcp snooping trust` | `dhcp snooping enable` / `dhcp snooping trusted` | T |
| Port security | `switchport port-security maximum 2` | `port-security enable` / `port-security max-mac-num 2` | T |
| Voice VLAN | `switchport voice vlan 20` | `voice-vlan 20 enable` | T — varies by platform |
| IPv6 basics | `ipv6 address 2001:db8::1/64` / `ipv6 route` / `ipv6 unicast-routing` | `ipv6 enable` + `ipv6 address 2001:db8::1 64` / `ipv6 route-static` / `ipv6` | S |

---

## 5. Tier 3 — Service-provider and data-center grade

Each row here is, in the source review's own words, "close to a project
in its own right" — VRF, MPLS, MP-BGP, IS-IS, QoS, BFD, multicast,
VXLAN/EVPN, and IPsec tunnels. `CLAUDE.md` §5 names BGP, IS-IS, VRF, and
QoS explicitly as out of scope. Full table intentionally omitted here
(it adds no new decision beyond "not this project") — see the original
review for the complete Cisco/VRP/type mapping if this becomes a
follow-on project.

---

## 6. On prioritisation, and the one open question

The source review proposed four priority items for **implementation**.
None of the four can be implemented under the current freeze, so all four
become priority ordering for **future work** instead — i.e. if a
follow-on project or post-submission extension picks this up, this is the
suggested order:

1. Fix §1 first (trunk default, Eth-Trunk membership) — these are
   silent-error risks in already-shipped rules, not new features.
2. Tier 1 management-plane commands (§2) — cheapest coverage gain, D/T
   mostly.
3. ACLs and DHCP relay (§3) — highest value in Tier 1, but needs the
   implicit-deny handling designed deliberately, not bolted on.
4. ~~Keep Tiers 2/3 as documented future work~~ — **this was discussed
   and item 4 stands as originally written**, not implemented now and
   not scheduled for immediate addition. Reasoning, for the record:
   - `CLAUDE.md` §5 already names most of Tier 2/3 as explicitly out of
     scope, with the instruction to refuse and point to that section if
     asked to add them.
   - The rule freeze (20 Sep) and feature freeze (24 Sep) leave no room
     to safely add protocol families the source review itself describes
     as individually project-sized.
   - `CLAUDE.md` §10 calls out the actual failure mode to avoid: "a
     complete system with no evaluation data does not [pass]." Spending
     the last days before feature freeze on VRF/BGP/IS-IS/QoS/VXLAN
     trades a working, evaluated system for an unfinished, unevaluated
     one — the wrong side of that tradeoff this close to submission.
   - This document — a prioritised, cited roadmap — is itself the
     Chapter 5 artifact that boundary decision is supposed to produce,
     per §5 of the source review: "shows the committee the boundary was
     a deliberate engineering decision, not a gap."

---

## 7. Proposed Chapter 5 structure

- 5.y.1 In-scope findings: trunk default VLAN mismatch, Eth-Trunk
  membership (§1 above) — pair with the static-route AD/preference
  finding already in `CLAUDE.md` §8 as a second instance of the same
  class of problem (vendor default divergence invisible to per-line
  translation).
- 5.y.2 Tier 1 management-plane commands as prioritised future work
  (§2) — cheapest, highest-density extension.
- 5.y.3 ACLs: why coverage and correctness pull in different directions
  here (§3) — the implicit-deny asymmetry as a worked example of why
  "looks converted" and "is equivalent" are different claims.
- 5.y.4 Tiers 2–3 as a deliberate scope boundary (§4–§5), cross-referenced
  against `CLAUDE.md` §5's explicit out-of-scope list.

This sits alongside the existing `unmapped-analysis.md` (5.x — taxonomy of
unmapped constructs on a specific corpus file) as the second piece of
Chapter 5 future-work material: that document is bottom-up (what one real
config revealed), this one is top-down (what a systematic review of the
appendix against three deployment tiers revealed). Together they cover
both directions of evidence for the same argument — the scope boundary
was chosen deliberately and can be quantified, not discovered too late.
