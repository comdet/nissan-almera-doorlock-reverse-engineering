# Nissan Almera N18 — Car Companion Data Goals

## เป้าหมาย

สร้าง Car Companion device ด้วย ESP32-C3 + SN65HVD230 ที่อ่านข้อมูลรถและสั่งงานผ่าน CAN Bus

## Hardware

```
ESP32-C3 Super Mini → SN65HVD230 → OBD-II CAN Bus (500kbps)
GPIO4 = CAN TX, GPIO3 = CAN RX
```

---

## สิ่งที่ทำได้แล้ว ✅

| ฟังก์ชัน | DID/PID | วิธี | Script |
|---|---|---|---|
| Door Lock | DID 0x0202 [00 01] via 0x745 | IOControl | nissan_slcan.py |
| Door Unlock | DID 0x0202 [00 02] via 0x745 | IOControl | nissan_slcan.py |
| DRL ON | DID 0x023F [00 01] via 0x745 | IOControl + keep-alive | nissan_slcan.py |
| DRL OFF | DID 0x023F [00 00] via 0x745 | IOControl | nissan_slcan.py |
| Door Lock Status | DID 0x0109 byte 8 via 0x745 | ReadDataByID | nissan_status.py |

---

## เป้าหมายข้อมูลที่ต้องอ่าน

### 1. Engine / Powertrain

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 1.1 | Engine RPM | PID 0x0C | OBD 0x7DF | ★★★ | ยังไม่ทดสอบ |
| 1.2 | Vehicle Speed | PID 0x0D | OBD 0x7DF | ★★★ | ยังไม่ทดสอบ |
| 1.3 | Engine Load | PID 0x04 | OBD 0x7DF | ★★ | ยังไม่ทดสอบ |
| 1.4 | Coolant Temperature | PID 0x05 | OBD 0x7DF | ★★★ | ยังไม่ทดสอบ |
| 1.5 | Intake Air Temperature | PID 0x0F | OBD 0x7DF | ★ | ยังไม่ทดสอบ |
| 1.6 | Throttle Position | PID 0x11 | OBD 0x7DF | ★★ | ยังไม่ทดสอบ |
| 1.7 | MAF Air Flow Rate | PID 0x10 | OBD 0x7DF | ★ | ยังไม่ทดสอบ |
| 1.8 | Fuel System Status | PID 0x03 | OBD 0x7DF | ★ | ยังไม่ทดสอบ |
| 1.9 | Timing Advance | PID 0x0E | OBD 0x7DF | ★ | ยังไม่ทดสอบ |
| 1.10 | Runtime Since Start | PID 0x1F | OBD 0x7DF | ★★ | ยังไม่ทดสอบ |

### 2. Transmission / Gear

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 2.1 | Gear Position (P/R/N/D) | ต้อง scan | TCM 0x7E1 or manufacturer DID | ★★★ | ต้อง scan หา |
| 2.2 | Transmission Temperature | ต้อง scan | TCM manufacturer DID | ★★ | ต้อง scan หา |

### 3. Body / Safety

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 3.1 | Door Lock Status | DID 0x0109 byte 8 | BCM 0x745 | ★★★ | ✅ ยืนยันแล้ว |
| 3.2 | Door Open/Close (แต่ละบาน) | DID 0x0109 (bytes อื่น) | BCM 0x745 | ★★★ | ต้อง decode |
| 3.3 | Handbrake / Parking Brake | ต้อง scan | BCM or manufacturer DID | ★★★ | ต้อง scan หา |
| 3.4 | Seatbelt Status | ต้อง scan | BCM | ★ | ต้อง scan หา |
| 3.5 | Turn Signal / Hazard | ต้อง scan | BCM | ★ | ต้อง scan หา |
| 3.6 | Headlight Status | DID 0x0E07? | 0x743 | ★★ | ต้อง decode |
| 3.7 | Key Position (OFF/ACC/ON/START) | ต้อง scan | BCM or DID 0x1301? | ★★★ | ต้อง decode |

### 4. Fuel / Trip

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 4.1 | Fuel Level | PID 0x2F | OBD 0x7DF | ★★★ | ต้องเช็คว่ารองรับ |
| 4.2 | Fuel Consumption Rate | คำนวณจาก MAF+Speed | — | ★★ | ต้องมี 1.2+1.7 ก่อน |
| 4.3 | Distance with MIL | PID 0x21 | OBD 0x7DF | ★ | ต้องเช็ค |
| 4.4 | Odometer | ต้อง scan | manufacturer DID | ★★ | ต้อง scan หา |

### 5. Electrical

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 5.1 | Battery Voltage | PID 0x42 | OBD 0x7DF | ★★★ | ต้องเช็ค |
| 5.2 | Alternator Status | ต้อง scan | manufacturer DID | ★ | ต้อง scan หา |

### 6. Climate

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 6.1 | Outside Temperature | PID 0x46 | OBD 0x7DF | ★★ | ต้องเช็ค |
| 6.2 | AC Compressor Status | ต้อง scan | manufacturer DID | ★ | ต้อง scan หา |

### 7. Diagnostics

| # | ข้อมูล | PID/DID | วิธีอ่าน | ความสำคัญ | สถานะ |
|---|---|---|---|---|---|
| 7.1 | MIL (Check Engine Light) | PID 0x01 | OBD 0x7DF | ★★★ | ยังไม่ทดสอบ |
| 7.2 | DTC Count | PID 0x01 | OBD 0x7DF | ★★ | ยังไม่ทดสอบ |
| 7.3 | Read DTCs | OBD Mode 0x03 | OBD 0x7DF | ★★ | ยังไม่ทดสอบ |
| 7.4 | Clear DTCs | OBD Mode 0x04 | OBD 0x7DF | ★ ระวัง! | ยังไม่ทดสอบ |

### 8. Control (สั่งงาน)

| # | ฟังก์ชัน | DID | controlState | สถานะ |
|---|---|---|---|---|
| 8.1 | Door Lock | DID 0x0202 [00 01] | via 0x745 BCM | ✅ ยืนยันแล้ว |
| 8.2 | Door Unlock | DID 0x0202 [00 02] | via 0x745 BCM | ✅ ยืนยันแล้ว |
| 8.3 | DRL ON | DID 0x023F [00 01] | via 0x745 BCM + keep-alive | ✅ ยืนยันแล้ว |
| 8.4 | DRL OFF | DID 0x023F [00 00] | via 0x745 BCM | ✅ ยืนยันแล้ว |
| 8.5 | Horn | ??? | ??? | อย่าแตะ! 🔇 |

---

## ECU ที่รู้จักแล้ว

| CAN ID Req | CAN ID Resp | ECU | ข้อมูล |
|---|---|---|---|
| 0x745 | 0x765 | BCM (Body Control Module) | Door lock, DRL, body status |
| 0x74C | 0x76C | BCM/Body ECU 2 | Body data 45 bytes (DID 0x0108) |
| 0x743 | 0x763 | Body/Light ECU | Light/body 22 bytes (DID 0x0E07) |
| 0x7E0 | 0x7E8 | ECM (Engine Control) | Standard OBD-II PIDs |
| 0x7E1 | 0x7E9 | TCM (Transmission) | Gear, engine status DIDs |
| 0x7DF | 0x7E8+0x7E9 | Broadcast | OBD-II standard queries |

## ECM Supported PIDs (จาก PID 0x00 probe)

**ECM (0x7E8): `BE 1F A8 13`**
```
PID 01 ✓ Monitor status / MIL / DTC count
PID 03 ✓ Fuel system status
PID 04 ✓ Engine load %
PID 05 ✓ Coolant temperature
PID 06 ✓ Short term fuel trim Bank 1
PID 07 ✓ Long term fuel trim Bank 1
PID 0C ✓ Engine RPM
PID 0D ✓ Vehicle speed
PID 0E ✓ Timing advance
PID 0F ✓ Intake air temperature
PID 10 ✓ MAF air flow rate
PID 11 ✓ Throttle position
PID 13 ✓ O2 sensors present
PID 15 ✓ O2 sensor voltage B1S2
PID 1C ✓ OBD standards compliance
PID 1F ✓ Runtime since engine start
PID 20 ✓ Supported PIDs [21-40] → ต้อง scan ต่อ
```

**TCM (0x7E9): `98 18 80 03`**
```
PID 01 ✓ Monitor status
PID 04 ✓ Engine load
PID 05 ✓ Coolant temperature
PID 0C ✓ Engine RPM
PID 0D ✓ Vehicle speed
PID 11 ✓ Throttle position
PID 1F ✓ Runtime since engine start
PID 20 ✓ Supported PIDs [21-40] → ต้อง scan ต่อ
```

## Manufacturer-Specific DIDs ที่ต้อง Decode

| DID | ECU (CAN ID) | ขนาด Response | สิ่งที่น่าจะอยู่ข้างใน |
|---|---|---|---|
| 0x0109 | BCM (0x745) | 18 bytes | Door status ทุกบาน, lock state, อื่น ๆ |
| 0x0108 | 0x74C | 45 bytes | Body data ขนาดใหญ่ — gear? handbrake? |
| 0x0E07 | 0x743 | 22 bytes | Light status, turn signal, headlight? |
| 0x1301 | 0x7E1 | ? | Engine/ignition status, key position? |
| 0x1304 | 0x7E1 | ? | Engine status เพิ่มเติม |

---

## ลำดับการทำงาน (Roadmap)

### Phase 1: OBD Standard PIDs (ง่าย — ใช้ broadcast 0x7DF)
- [ ] RPM (0x0C), Speed (0x0D), Coolant (0x05), Throttle (0x11)
- [ ] MIL/DTC status (0x01)
- [ ] Scan PID 0x20 → PIDs 0x21-0x40 (fuel level? battery voltage?)
- [ ] Runtime (0x1F), Engine Load (0x04)

### Phase 2: Decode Manufacturer DIDs (เทียบค่าทีละ byte)
- [ ] DID 0x0109 ครบทุก byte — เปิด/ปิดประตูแต่ละบาน
- [ ] DID 0x0108 (45 bytes) — เปลี่ยนเกียร์ P/R/N/D แล้วเทียบ
- [ ] DID 0x0E07 (22 bytes) — เปิด/ปิดไฟ แล้วเทียบ
- [ ] DID 0x1301, 0x1304 — เปิด/ปิดเครื่อง แล้วเทียบ

### Phase 3: Scan หาข้อมูลเพิ่ม
- [ ] Scan TCM DIDs สำหรับ gear position
- [ ] Scan BCM DIDs สำหรับ handbrake, seatbelt
- [ ] Extended OBD PIDs (0x21-0x40, 0x41-0x60)

### Phase 4: Integration
- [ ] รวมทุกอย่างใส่ nissan_slcan.py
- [ ] สร้าง dashboard / real-time display
- [ ] สร้าง daemon mode (auto lock/unlock based on conditions)
