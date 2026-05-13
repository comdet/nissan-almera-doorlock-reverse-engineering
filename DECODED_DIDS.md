# Nissan Almera N18 — Decoded Manufacturer DIDs

## วันที่ทดสอบ: 2026-04-15/16, อัพเดท 2026-04-17 (DID 0x1301 ยืนยันเป็น gear)

---

## DID 0x0109 — BCM (0x745) — Door & Body Status — 18 bytes

### Byte 6: Door Open/Close (bitmask) ✅ ยืนยันครบทุกบาน

| Bit | Mask | ประตู | ยืนยัน |
|---|---|---|---|
| bit 7 | 0x80 | คนขับ (Driver / FL) | ✅ |
| bit 6 | 0x40 | ผู้โดยสารหน้า (Passenger / FR) | ✅ |
| bit 5 | 0x20 | หลังฝั่งคนขับ (Rear Left / RL) | ✅ |
| bit 4 | 0x10 | หลังฝั่งผู้โดยสาร (Rear Right / RR) | ✅ |
| bit 3 | 0x08 | ท้าย (Trunk) | ✅ |
| bit 2-0 | 0x04-0x01 | ไม่ทราบ (อาจเป็น hood?) | ยังไม่ทดสอบ |

- เปิดหลายบาน = OR กัน เช่น Driver+Trunk = 0x80|0x08 = 0x88
- 0x00 = ประตูทุกบานปิด

### Byte 8: Door Lock Status ✅

| ค่า | สถานะ |
|---|---|
| 0x00 | LOCKED |
| 0x10 | UNLOCKED |

### Byte 17: Brake Pedal ✅

| ค่า | สถานะ |
|---|---|
| 0x00 | ไม่เหยียบเบรค |
| 0x0C | เหยียบเบรค |

### Byte 4: Lights & Signals (bitmask) ✅

| Bit | Mask | ความหมาย | ยืนยัน |
|---|---|---|---|
| bit 3 | 0x08 | Turn signal RIGHT | ✅ |
| bit 2 | 0x04 | Turn signal LEFT | ✅ |
| bit 1 | 0x02 | Parking lights (ไฟหรี่) | ✅ |
| bit 0 | 0x01 | High beam (ไฟสูง) | ✅ |

Hazard = bit 2 + bit 3 = 0x0C (สันนิษฐาน)

### Byte 5: Headlight State ✅

| ค่า | สถานะ | ยืนยัน |
|---|---|---|
| 0x42 | ไฟปิดหมด | ✅ |
| 0x02 | ไฟหรี่เท่านั้น | ✅ |
| 0x82 | ไฟหน้า (low/high beam) | ✅ |

bit 7 (0x80) = headlight ON, bit 6 (0x40) = headlight OFF indicator?

### Bytes ที่ยังไม่ decode

| Byte | Baseline | หมายเหตุ |
|---|---|---|
| 3 | 0x09 | ? |
| 7 | 0x00 | ? |
| 9-13 | 00 00 00 00 00 | ? |
| 14-15 | 01 98 | ? |
| 16-17 | 00 00 | ? |

---

## DID 0x0108 — ECU 0x74C — Body Data — 45 bytes ⚠️ DEPRECATED for gear

**หมายเหตุ:** ECU ตอบ NRC 0x78 (response pending) ต้องรอ ~3 วินาที
**ใช้ DID 0x1301 จาก ECU 0x7E1 แทน** — เร็วกว่า, แยก D/L ได้, ใช้ได้ตอนเครื่องดับ

### Byte 27: Gear Position (ไม่นิ่ง — ใช้ DID 0x1301 แทน)

| ค่า (เก่า) | เกียร์ | หมายเหตุ |
|---|---|---|
| 0x80 | P | ค่าไม่นิ่ง — bit 7,6 อ่านได้ แต่ lower bits เปลี่ยนตลอด |
| 0x00 | R | D กับ L แยกไม่ได้ (ทั้งคู่ 0xC0) |
| 0x40 | N | ตอนเครื่องดับค่าพังหมด |
| 0xC0 | D/L | ลอง 2026-04-17: ค่าวนไป N→P→R ทั้งที่เกียร์อยู่ P |

**ทำไมเลิกใช้:**
- ECU 0x74C ตอบช้า (NRC 0x78 รอ 3 วินาที)
- ค่าไม่นิ่ง — อ่าน 3 รอบติดกันได้คนละค่า
- แยก D กับ L ไม่ได้
- ตอนเครื่องดับ ค่าผสม handbrake/engine state เข้ามา

---

## DID 0x0E07 — ECU 0x743 — Light/Body — 22 bytes

### Bytes ที่สังเกตเห็นเปลี่ยน

| Byte | Baseline | เปิดประตู | หมายเหตุ |
|---|---|---|---|
| 3 | 0x00 | 0x04 | เปลี่ยนเมื่อเปิดประตู |
| 4 | 0x00 | 0x08 | เปลี่ยนเมื่อเปิดประตู |
| 5 | 0x00 | 0x10 | เปลี่ยนเมื่อเปิดประตู |
| 7 | 0x00 | 0x40 | เปลี่ยนเมื่อเปิดประตู |
| 11 | 0x00 | 0x10 | เปลี่ยนเมื่อเปิดประตู |
| 13 | 0x04 | 0x0C | เปลี่ยนเมื่อเปลี่ยนเกียร์ (P→N) |
| 19 | 0x10 | 0x10 | ไม่เปลี่ยน |

### Byte 19: Handbrake ✅

| ค่า | สถานะ |
|---|---|
| 0x10 | Handbrake **ON** (ดึง) |
| 0x00 | Handbrake **OFF** (ปล่อย) |

**ต้อง decode เพิ่ม:** เปิด/ปิดไฟหน้า, ไฟเลี้ยว, hazard

---

## DID 0x1301 — ECU 0x7E1 — Gear Position ✅ ★ ใช้แทน DID 0x0108

**หมายเหตุ:** Single frame (4 bytes) — ตอบทันที ไม่มี NRC 0x78
**ใช้ได้ตอนเครื่องดับ (ACC on)** — แค่ต้องมี OBD query/DID query อื่นก่อน warm-up ECU

### Byte 3: Gear Position ✅ ยืนยันครบทุกเกียร์ (2026-04-17 บนรถจริง)

| ค่า | เกียร์ | ยืนยัน |
|---|---|---|
| 0x10 | **P** (Park) | ✅ นิ่ง 5/5 |
| 0x20 | **R** (Reverse) | ✅ นิ่ง 3/3 |
| 0x40 | **N** (Neutral) | ✅ นิ่ง 5/5 |
| 0x80 | **D** (Drive) | ✅ นิ่ง 3/3 |
| 0x08 | **L** (Low) | ✅ นิ่ง 3/3 |
| 0x01 | (idle, ECU ยังไม่ warm-up) | เกิดเฉพาะเมื่ออ่าน 0x1301 เป็น query แรกหลัง boot |

**ข้อดี vs DID 0x0108:**
- ⚡ **เร็วกว่า** — single frame, ไม่ต้องรอ NRC 0x78 3 วินาที
- 🎯 **แม่นยำ** — ค่านิ่ง อ่านซ้ำได้ผลเดียวกัน
- 🔢 **แยก D/L ได้** — DID 0x0108 ทั้งคู่ค่าเดียวกัน
- 🔌 **ใช้ได้เครื่องดับ** — DID 0x0108 ค่าพังตอนเครื่องดับ

**ข้อจำกัด:** ตอน cold start ถ้าอ่าน 0x1301 ก่อน query อื่นจะได้ 0x01 (idle)
ในการใช้งานจริง OBD PIDs ถูก poll ทุกรอบ → ECU warm-up เสมอ ไม่มีปัญหา

---

## DID 0x1304 — ECU 0x7E1 — Engine Status 2 — 4 bytes

### Byte 3: Engine Running ✅

| ค่า | สถานะ | ยืนยัน |
|---|---|---|
| 0x02 | ACC/ON แต่เครื่อง **ดับ** | ✅ |
| 0x06 | เครื่อง **ติด** (running) | ✅ |

**วิธีตรวจ engine on/off ที่แนะนำ:**
1. OBD PID 0x0C (RPM) — ดีที่สุด (0=off, >0=on)
2. DID 0x1304 byte 3 — ใช้ได้ (0x02=off, 0x06=on)

---

## Scripts

| Script | หน้าที่ |
|---|---|
| `nissan_car_status.py` | **อ่านสถานะรถครบ:** ประตู, เกียร์, ล็อค, RPM, Speed, Temp, Battery |
| `nissan_slcan.py` | สั่ง lock/unlock/DRL |
| `nissan_obd.py` | อ่าน OBD-II PIDs ทั้งหมด |
| `nissan_status.py` | อ่านสถานะ lock/unlock อย่างเดียว |
| `nissan_diff.py` | เทียบ DID bytes ก่อน/หลังเปลี่ยนสถานะ |

---

## สิ่งที่ยังต้อง Decode

- [x] Door open/close ทุกบาน — DID 0x0109 byte 6 ✅
- [x] Door lock status — DID 0x0109 byte 8 ✅
- [x] Brake pedal — DID 0x0109 byte 17 ✅
- [x] Gear position (P/R/N/D/L) — **DID 0x1301 byte 3** ✅ (ใช้แทน DID 0x0108)
- [x] Handbrake — DID 0x0E07 byte 19 ✅
- [x] Headlight / high beam / parking lights — DID 0x0109 byte 4+5 ✅
- [x] Turn signal L/R — DID 0x0109 byte 4 bit 2/3 ✅
- [x] Engine running detect — DID 0x1304 byte 3 (0x02=OFF, 0x06=ON) + RPM ✅
- [~] DID 0x0108 byte 5 — fuel level? (0x80=128≈50% เมื่อหน้าปัดบอก 49% ต้องยืนยันเพิ่ม)
- [ ] DID 0x0108 — odometer (ยังไม่เจอ ต้องเทียบกับ 75,194 km)

## CAN Bus Architecture (ค้นพบ 2026-04-17)

OBD-II port ของ Almera N18 ต่อผ่าน **CAN Gateway** → diagnostic-only CAN
**ไม่มี broadcast traffic** — ต้อง poll request-response ทุกอย่าง

ดูเพิ่ม: [STATE_MACHINE.md](STATE_MACHINE.md) — state machine + smart polling strategy
