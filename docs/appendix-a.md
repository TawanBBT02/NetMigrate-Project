# ภาคผนวก ก
# ตารางกฎการแปลงคำสั่งระหว่าง Cisco IOS-XE และ Huawei VRP

> เอกสารนี้สร้างขึ้นโดยอัตโนมัติจาก `netmigrate/rule_catalog.py`
> ด้วยคำสั่ง `python tools/make_appendix.py` — ห้ามแก้ไขด้วยมือ
> หากต้องการแก้ไขให้แก้ที่แคตาล็อกในโค้ดแล้วสร้างใหม่

## ก.1 สรุปภาพรวม

| รายการ | จำนวน |
|---|---|
| กฎการแปลงคำสั่ง | 16 |
| ประเภท Interface ที่รองรับ | 7 |
| รายการที่ยืนยันกับเอกสารผู้ผลิตแล้ว | 19 จาก 23 (83%) |
| รายการที่ยังไม่ยืนยัน | 4 |

**สัดส่วนตามประเภทของกฎ**

| ประเภท | จำนวน | สัดส่วน |
|---|---|---|
| D (แทนที่ตรง) | 9 | 56% |
| T (แปลงอาร์กิวเมนต์) | 3 | 19% |
| S (เปลี่ยนโครงสร้าง) | 4 | 25% |

> กฎประเภท S คือกฎที่สถาปัตยกรรมแบบแทนที่รายบรรทัดไม่สามารถแสดงออกได้
> และเป็นเหตุผลที่ระบบต้องใช้โครงสร้างข้อมูลกลาง (ดูหัวข้อ 3.2.3)

## ก.2 ตารางกฎการแปลงคำสั่ง

### ก.2.1 ระดับระบบ

| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |
|---|---|---|---|---|---|
| `system.hostname` | `hostname SW1` | `sysname SW1` | D | ยืนยันแล้ว (EX) | H-EX-VLAN |

**หมายเหตุ**

- `system.hostname` — ปรากฏในไฟล์กำหนดค่าตัวอย่างของ Huawei ในรูป `# sysname SwitchA`

### ก.2.2 VLAN

| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |
|---|---|---|---|---|---|
| `vlan.create` | `vlan 10` | `vlan 10` | D | ยืนยันแล้ว (DOC) | H-VLAN |
| `vlan.name` | `name SALES` | `name SALES` | D | **ยังไม่ยืนยัน** (UNVER) | H-VLANCMD |

**หมายเหตุ**

- `vlan.create` — Cisco รองรับ `vlan 10,20,30-35` ซึ่งระบบขยายเป็นบล็อกแยกรายการ; Huawei รองรับ `vlan batch` ซึ่งระบบขยายเช่นเดียวกัน
- `vlan.name` — **ยังไม่ยืนยัน** — ไม่ปรากฏในไฟล์ตัวอย่างทั้งสองฉบับ ต้องเปิดเอกสาร H-VLANCMD เพื่อยืนยัน

### ก.2.3 Interface

| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |
|---|---|---|---|---|---|
| `interface.name` | `interface GigabitEthernet0/0/1` | `interface GE0/0/1` | D | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `interface.description` | `description UPLINK` | `description UPLINK` | D | **ยังไม่ยืนยัน** (UNVER) | — |
| `interface.ip` | `ip address 10.0.0.1 255.255.255.0` | `ip address 10.0.0.1 255.255.255.0` | T | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `interface.shutdown` | `shutdown / no shutdown` | `shutdown / undo shutdown` | D | ยืนยันแล้ว (EX) | H-ETH |

**หมายเหตุ**

- `interface.name` — แปลงเฉพาะส่วนประเภท คงส่วนตัวเลขไว้ตามเดิม (ดูข้อจำกัด 2.3.2.4)
- `interface.description` — **ยังไม่ยืนยัน** — รูปแบบเหมือนกันทั้งสองผู้ผลิต ความเสี่ยงต่ำ
- `interface.ip` — Huawei รับรูปแบบความยาว Prefix ด้วย (`ip address 10.0.0.1 24`) ระบบรับทั้งสองรูปแบบเป็นข้อมูลเข้า และสร้างรูปแบบ Subnet Mask เป็นผลลัพธ์
- `interface.shutdown` — ค่าสามสถานะ: หากไฟล์ต้นทางไม่ระบุ ระบบไม่สร้างคำสั่งใด เพราะค่าเริ่มต้นของผู้ผลิตไม่ตรงกัน

### ก.2.4 รูปแบบพอร์ต

| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |
|---|---|---|---|---|---|
| `port.link-type` | `switchport mode access | trunk` | `port link-type access | trunk` | D | ยืนยันแล้ว (DOC) | H-VLAN |
| `port.access-vlan` | `switchport access vlan 10` | `port default vlan 10` | D | ยืนยันแล้ว (DOC) | H-VLAN |
| `port.trunk-allowed` | `switchport trunk allowed vlan 10,20,30-35` | `port trunk allow-pass vlan 10 20 30 to 35` | T | ยืนยันแล้ว (DOC) | H-VLAN |
| `port.trunk-native` | `switchport trunk native vlan 99` | `port trunk pvid vlan 99` | D | ยืนยันแล้ว (DOC) | H-VLAN |

**หมายเหตุ**

- `port.link-type` — `port link-type hybrid` ของ Huawei อยู่นอกขอบเขต
- `port.trunk-allowed` — เอกสารกำหนดรูปแบบเป็น `&<1-40>` คือสูงสุด 40 องค์ประกอบต่อคำสั่ง โดยช่วงนับเป็นหนึ่งองค์ประกอบ ระบบแบ่งเป็นหลายคำสั่งเมื่อเกิน; `allow-pass vlan all` อยู่นอกขอบเขต

### ก.2.5 การจัดเส้นทางคงที่

| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |
|---|---|---|---|---|---|
| `route.static` | `ip route 10.0.0.0 255.0.0.0 192.168.1.1 [200]` | `ip route-static 10.0.0.0 255.0.0.0 192.168.1.1 [preference 200]` | T | ยืนยันแล้ว (DOC) | H-ROUTE |

**หมายเหตุ**

- `route.static` — Cisco รับค่า Administrative Distance เป็นจำนวนเต็มต่อท้าย VRP ต้องใช้ คำสำคัญ `preference`; **ค่าเริ่มต้นไม่เท่ากัน** (Cisco 1, VRP 60) ระบบจึงแจ้งเตือนหนึ่งครั้งต่อไฟล์เมื่อมีเส้นทางที่อาศัยค่าเริ่มต้น

### ก.2.6 OSPF

| รหัสกฎ | Cisco IOS-XE | Huawei VRP | ประเภท | สถานะการตรวจสอบ | อ้างอิง |
|---|---|---|---|---|---|
| `ospf.process` | `router ospf 1` | `ospf 1 router-id 1.1.1.1` | S | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `ospf.router-id` | `router-id 1.1.1.1 (บรรทัดลูก)` | `(อยู่บนบรรทัด ospf)` | S | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `ospf.area` | `(เป็นอาร์กิวเมนต์ท้ายบรรทัด network)` | `area 0.0.0.0 (บล็อกแม่)` | S | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `ospf.network` | `network 10.0.0.0 0.0.0.255 area 0` | `network 10.0.0.0 0.0.0.255` | S | ยืนยันแล้ว (EX) | H-EX-OSPF |

**หมายเหตุ**

- `ospf.process` — VRP บรรจุ router-id บนบรรทัดประกาศ Process
- `ospf.router-id` — รหัสกฎนี้ปรากฏเฉพาะในตัวสร้างไฟล์ฝั่ง Cisco ตามความไม่สมมาตรเชิงโครงสร้าง
- `ospf.area` — รหัสกฎนี้ปรากฏเฉพาะในตัวสร้างไฟล์ฝั่ง Huawei; หมายเลข Area แปลงระหว่าง จำนวนเต็มและเลขฐานสิบแบบมีจุด โดย `area 1` คือ `0.0.0.1`
- `ospf.network` — ต้องจัดกลุ่มตาม Area จึงไม่สามารถสร้างผลลัพธ์ได้จนอ่านบล็อกจนจบ

## ก.3 ตารางแปลงชื่อประเภท Interface

| ชื่อภายในระบบ | Cisco (เต็ม) | Cisco (ย่อ) | Huawei | สถานะ | อ้างอิง |
|---|---|---|---|---|---|
| `gigabit` | `GigabitEthernet` | `Gi` | `GE` | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `tengigabit` | `TenGigabitEthernet` | `Te` | `XGE` | ยืนยันแล้ว (DOC) | H-IFBASE |
| `fast` | `FastEthernet` | `Fa` | `Ethernet` | **ยังไม่ยืนยัน** (UNVER) | — |
| `loopback` | `Loopback` | `Lo` | `LoopBack` | **ยังไม่ยืนยัน** (UNVER) | — |
| `vlan` | `Vlan` | `Vl` | `Vlanif` | ยืนยันแล้ว (EX) | H-EX-OSPF |
| `portchannel` | `Port-channel` | `Po` | `Eth-Trunk` | ยืนยันแล้ว (EX) | H-ETH |
| `null` | `Null` | `Nu` | `NULL` | ยืนยันแล้ว (EX) | H-EX-OSPF |

> ระบบแปลงเฉพาะส่วนที่เป็น**ประเภท**ของ Interface และคงส่วนที่เป็น
> **ตัวเลข**ไว้ตามเดิม เนื่องจากรูปแบบการนับหมายเลขพอร์ตสะท้อนโครงสร้าง
> ฮาร์ดแวร์ทางกายภาพ จึงไม่มีการแมปที่ถูกต้องสมบูรณ์ด้วยอัลกอริทึม
> (ดูข้อจำกัด 2.3.2.4)

## ก.4 คำสั่งที่ระบบปฏิเสธการแปลงโดยเจตนา

รายการต่อไปนี้ถูกส่งไปยังรายการคำสั่งที่ไม่มีกฎรองรับ **โดยเจตนา** ไม่ใช่ข้อบกพร่อง การออกแบบเลือกยอมเสียค่าความครอบคลุม เพื่อไม่ให้ข้อมูลสูญหายโดยไม่มีการแจ้งเตือน

| คำสั่ง | เหตุผล |
|---|---|
| `port trunk allow-pass vlan all` | ไม่สามารถแสดงเป็นรายการ VLAN ที่ระบุชัดเจนของ Cisco ในขอบเขตได้ |
| `port link-type hybrid` | ไม่มีคำสั่งเทียบเคียงใน Cisco ภายในขอบเขต |
| `ip route-static ... 150 (ไม่มีคำสำคัญ preference)` | ไม่ใช่ไวยากรณ์ที่ถูกต้องของ VRP |
| `ip route ... name BACKUP` | หากแปลงจะทิ้งชื่อเส้นทางโดยไม่แจ้งผู้ใช้ |
| `vlan 10,20 พร้อมคำสั่ง name` | ชื่อเดียวไม่สามารถใช้กับ VLAN หลายรายการได้ |
| `enable secret / local-user password (ข้อมูลรหัสผ่าน)` | ค่าแฮชเป็นฟังก์ชันทางเดียวและต่างอัลกอริทึม ไม่มีการแปลงในทางหลักการ |
| `interface Serial / Tunnel / ATM` | ประเภท Interface อยู่นอกขอบเขต |

## ก.5 รายการที่ยังไม่ได้ยืนยันกับเอกสารผู้ผลิต

รายการต่อไปนี้ยังไม่ได้ยืนยันกับแหล่งข้อมูลปฐมภูมิ และถูกระบุไว้เป็นข้อจำกัดในบทที่ 5 **ไม่ได้นำเสนอว่าเป็นรายการที่ผ่านการตรวจสอบแล้ว**

| รายการ | ประเภท | หมายเหตุ |
|---|---|---|
| `vlan.name` | กฎการแปลง | **ยังไม่ยืนยัน** — ไม่ปรากฏในไฟล์ตัวอย่างทั้งสองฉบับ ต้องเปิดเอกสาร H-VLANCMD เพื่อยืนยัน |
| `interface.description` | กฎการแปลง | **ยังไม่ยืนยัน** — รูปแบบเหมือนกันทั้งสองผู้ผลิต ความเสี่ยงต่ำ |
| `fast` | ชื่อ Interface | `FastEthernet` ↔ `Ethernet` — ยังไม่พบเอกสารอ้างอิง |
| `loopback` | ชื่อ Interface | `Loopback` ↔ `LoopBack` — ยังไม่พบเอกสารอ้างอิง |

## ก.6 เอกสารอ้างอิงที่ใช้ยืนยันกฎการแปลง

| รหัส | เอกสาร |
|---|---|
| **H-ETH** | Eth-Trunk Interface Configuration — NE5000E V800R022C00SPC500 Configuration Guide. support.huawei.com/enterprise/en/doc/EDOC1100278760/20c76fcd |
| **H-EX-OSPF** | Typical OSPF Configuration — same series, Typical Configuration Examples. support.huawei.com/enterprise/en/doc/EDOC1000069520/a25a2d1a |
| **H-EX-VLAN** | Typical VLAN Configuration — S300/S500/S2700/S3700/S5700/S6700/S7700/S9700 Typical Configuration Examples (V200). support.huawei.com/enterprise/en/doc/EDOC1000069520/b699322c |
| **H-IFBASE** | Basic Interface Configuration Commands — S1700/S2720/S5700/S6700 V200R019C10 Command Reference. support.huawei.com/enterprise/en/doc/EDOC1100127035/cdd85713 |
| **H-ROUTE** | ip route-static — S1700/S2720/S5700/S6700 V200R020C00 Command Reference. support.huawei.com/enterprise/en/doc/EDOC1100176877/ac7caed7 |
| **H-VLAN** | Configuring Interface-based VLAN Assignment — CloudEngine S5700/S6700 V600R022C00 Configuration Guide, Ethernet Switching. support.huawei.com/enterprise/en/doc/EDOC1100278261/c213d155 |
| **H-VLANCMD** | VLAN Configuration Commands — S5700/S6700 V200R025C00 Command Reference (NOT YET READ). support.huawei.com/enterprise/en/doc/EDOC1100514211/834147df |

> ต้องตรวจสอบเลขรุ่นเอกสารและวันที่เข้าถึงอีกครั้งก่อนส่งฉบับสมบูรณ์
> และจัดรูปแบบการอ้างอิงตามเกณฑ์ของภาควิชา

