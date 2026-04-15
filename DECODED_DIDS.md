# Nissan Almera N18 — Decoded Manufacturer DIDs

## วันที่ทดสอบ: 2026-04-15/16

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

### Bytes ที่ยังไม่ decode

| Byte | Baseline | หมายเหตุ |
|---|---|---|
| 3 | 0x09 | ? |
| 4 | 0x00 | ? |
| 5 | 0x42 | ? |
| 7 | 0x00 | ? |
| 9-13 | 00 00 00 00 00 | ? |
| 14-15 | 01 98 | ? |
| 16-17 | 00 00 | ? |

---

## DID 0x0108 — ECU 0x74C — Body Data — 45 bytes

**หมายเหตุ:** ECU ตอบ NRC 0x78 (response pending) ต้องรอ ~3 วินาที

### Byte 27: Gear Position ✅ ยืนยันครบทุกเกียร์

| ค่า | เกียร์ | ยืนยัน |
|---|---|---|
| 0x80 | **P** (Park) | ✅ |
| 0x00 | **R** (Reverse) | ✅ |
| 0x40 | **N** (Neutral) | ✅ |
| 0xC0 | **D/L** (Drive / Low) | ✅ |
| 0x10 | เครื่องดับ (Engine OFF) | ✅ |

**หมายเหตุ:** D กับ L ค่าเดียวกัน (0xC0) แยกไม่ได้จาก byte นี้อย่างเดียว

### Byte 4: Parking Indicator (สังเกต)

| ค่า | สถานะ |
|---|---|
| 0x00 | เกียร์ P (จอด) |
| 0x02 | เกียร์ R/N/D/L (ไม่ใช่ P) |

### Bytes ที่เปลี่ยนเมื่อเปลี่ยนเกียร์ (ยังไม่ decode ทั้งหมด)

Bytes 7, 23-24, 26-31, 33-35, 37-39, 41-42 เปลี่ยนเมื่อเปลี่ยนเกียร์
อาจเป็น transmission data, torque, speed sensor ภายใน

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

**ต้อง decode เพิ่ม:** เปิด/ปิดไฟหน้า, ไฟเลี้ยว, hazard

---

## DID 0x1301 — ECU 0x7E1 — Engine Status — 4 bytes

### Byte 3: Engine Running Status

| ค่า | สถานะ | ยืนยัน |
|---|---|---|
| 0x10 | เครื่อง idle (P) | ✅ |
| 0x40 | เครื่อง idle (N) | ✅ (เปลี่ยนตามเกียร์?) |

**ต้อง decode เพิ่ม:** ค่าตอนดับเครื่อง, ค่าตอนเร่งเครื่อง

---

## DID 0x1304 — ECU 0x7E1 — Engine Status 2 — 4 bytes

### Byte 3:

| ค่า | สถานะ |
|---|---|
| 0x02 | เครื่องทำงาน (ไม่เปลี่ยนตามเกียร์) |

**ต้อง decode เพิ่ม:** ค่าตอนดับเครื่อง

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

- [ ] DID 0x0109 byte 5 (0x42) — อาจเป็น handbrake?
- [ ] DID 0x0108 — fuel level, odometer (45 bytes ยังมีข้อมูลซ่อนเยอะ)
- [ ] DID 0x0E07 — headlight, turn signal, hazard
- [ ] DID 0x1301/0x1304 — engine off vs on, key position
- [ ] Handbrake status — ยังไม่รู้ว่าอยู่ DID ไหน
